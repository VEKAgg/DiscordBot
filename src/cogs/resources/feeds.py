"""Feeds Cog — dynamic RSS feed management backed by the database."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import FEED_MAX_POSTS_PER_GUILD_PER_CYCLE, FEED_MAX_POSTS_PER_POLL, FEED_MAX_SUBSCRIPTIONS
from src.database.database import db
from src.services.rss_service import RSSService
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import (
    DatabaseUnavailableError,
    manage_guild_only,
    safe_background_task,
    safe_send,
    safe_slash_command,
)

logger = logging.getLogger('VEKA.feeds')


class Feeds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rss_service = RSSService(bot=bot)
        # Serialize quota checks and inserts in this bot process.
        self._management_lock = asyncio.Lock()

    async def cog_ready(self):
        if not self.feed_update.is_running():
            self.feed_update.start()

    def cog_unload(self):
        self.feed_update.cancel()

    # ============================================================
    # Background Task — DB-backed feed polling
    # ============================================================

    @tasks.loop(minutes=1)
    @safe_background_task(name='feed_update')
    async def feed_update(self):
        """Poll all subscribed feeds and post new entries to configured channels."""
        try:
            subscriptions = await db.fetch_many(
                """SELECT id, guild_id, channel_id, feed_url, feed_name, poll_interval_minutes, last_polled_at,
                          consecutive_failures, next_retry_at
                   FROM feed_subscriptions WHERE paused = FALSE"""
            )
        except DatabaseUnavailableError:
            logger.debug('Skipping feed update: database unavailable')
            return

        posted_by_guild: dict[int, int] = {}
        for sub in subscriptions:
            remaining = FEED_MAX_POSTS_PER_GUILD_PER_CYCLE - posted_by_guild.get(sub['guild_id'], 0)
            if remaining <= 0:
                continue
            # Seeded subscriptions have channel_id 0 until staff configure them with /feed add.
            if not sub['channel_id']:
                continue
            if sub['next_retry_at'] and datetime.now(UTC) < sub['next_retry_at']:
                continue
            # Respect per-feed polling interval, including unsuccessful attempts.
            if sub['last_polled_at']:
                last = sub['last_polled_at']
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if datetime.now(UTC) - last < timedelta(minutes=sub['poll_interval_minutes'] or 30):
                    continue

            try:
                guild = self.bot.get_guild(sub['guild_id'])
                channel = guild.get_channel(sub['channel_id']) if guild else None
                if not isinstance(channel, nextcord.TextChannel) or self._channel_problem(guild, channel):
                    continue
                feed_data = await self.rss_service.fetch_feed(sub['feed_url'])
                if not feed_data:
                    await self._record_poll_result(sub, succeeded=False)
                    continue

                await self._record_poll_result(sub, succeeded=True)
                new_entries = await self.rss_service.process_and_dedupe(
                    sub['feed_url'], feed_data['entries'], subscription_id=sub['id'], mark_seen=False
                )

                for entry in new_entries[: min(FEED_MAX_POSTS_PER_POLL, remaining)]:
                    embed = await self._create_feed_embed(entry, sub['feed_name'])
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        logger.error('Failed to send feed to channel %s: %s', sub['channel_id'], e)
                        break
                    posted_by_guild[sub['guild_id']] = posted_by_guild.get(sub['guild_id'], 0) + 1
                    await self.rss_service.process_and_dedupe(sub['feed_url'], [entry], subscription_id=sub['id'])

            except Exception as e:
                logger.error('Error polling feed %s: %s', sub['feed_url'], e)

    async def _record_poll_result(self, sub, *, succeeded: bool):
        """Persist before notifying: one warning per outage, including across restarts.

        Backoff doubles from the configured interval, capped at one day (never
        shorter than the configured interval). Failed feeds remain recoverable.
        Notification delivery is best-effort, as with other admin alerts.
        """
        previous = sub['consecutive_failures']
        failures = 0 if succeeded else previous + 1
        interval = max(10, sub['poll_interval_minutes'] or 30)
        delay = max(interval, min(1440, interval * 2 ** min(failures - 1, 10))) if failures else 0
        await db.execute(
            """UPDATE feed_subscriptions
               SET last_polled_at = NOW(), consecutive_failures = $2,
                   next_retry_at = $3
               WHERE id = $1""",
            sub['id'],
            failures,
            datetime.now(UTC) + timedelta(minutes=delay) if failures else None,
        )
        notifier = getattr(self.bot, 'notifier', None)
        if notifier is None:
            return
        if failures == 3:
            await notifier.send_alert(
                title='RSS Feed Failing',
                description=(
                    f'The RSS feed `{sub["feed_url"]}` has failed 3 consecutive polls. '
                    'Further warnings are suppressed until recovery. Retries use backoff up to once daily '
                    '(or the configured interval if longer). Check the bot logs for the error; '
                    'use `/feed remove` to remove an obsolete feed.'
                ),
                severity='WARN',
                guild_id=sub['guild_id'],
            )
        elif succeeded and previous >= 3:
            await notifier.send_alert(
                title='RSS Feed Recovered',
                description=f'The RSS feed `{sub["feed_url"]}` is now responding correctly.',
                severity='INFO',
                guild_id=sub['guild_id'],
            )

    @feed_update.before_loop
    async def before_feed_update(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # /feed — Management Commands
    # ============================================================

    @nextcord.slash_command(
        name='feed',
        description='Manage RSS feed subscriptions',
        contexts=[nextcord.InteractionContextType.guild],
    )
    @safe_slash_command()
    async def feed_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Feed Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/feed add` — Subscribe to a new RSS feed\n'
                '• `/feed edit` — Change channel, name, or interval\n'
                '• `/feed pause` / `/feed resume` — Stop or restart posting\n'
                '• `/feed remove` — Remove a feed subscription\n'
                '• `/feed list [page]` — View subscriptions and health\n'
                '• `/feed test` — Preview the latest entry from a feed'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @feed_group.subcommand(name='add', description='Subscribe to a new RSS feed')
    @manage_guild_only()
    @safe_slash_command(requires_db=True)
    async def feed_add(
        self,
        interaction: nextcord.Interaction,
        url: str,
        channel: nextcord.TextChannel,
        name: str = '',
        interval_minutes: int = nextcord.SlashOption(
            description='Poll interval in minutes',
            min_value=10,
            max_value=1440,
            default=30,
        ),
    ):
        if not interaction.guild:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Server Only',
                    'This command can only be used in a server.',
                    contributor_source=__name__,
                    user=interaction.user,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        problem = self._channel_problem(interaction.guild, channel)
        if problem:
            await self._management_reply(interaction, 'Invalid Channel', problem, error=True)
            return
        url = url.strip()
        if len(url) > 2000:
            await self._management_reply(
                interaction, 'Invalid URL', 'Feed URLs must be at most 2000 characters.', error=True
            )
            return
        # Validate the RSS feed
        try:
            feed_data = await self.rss_service.fetch_feed(url)
            if not feed_data:
                await safe_send(
                    interaction,
                    embed=await error_embed(
                        'Invalid Feed',
                        'Could not fetch or parse the RSS feed at that URL.',
                        contributor_source=__name__,
                        user=interaction.user,
                    ),
                    ephemeral=True,
                )
                return
        except Exception:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Invalid Feed',
                    'Could not fetch or parse the RSS feed at that URL.',
                    contributor_source=__name__,
                    user=interaction.user,
                ),
                ephemeral=True,
            )
            return

        feed_name = (name.strip() or feed_data.get('title', '').strip() or url)[:64]

        try:
            async with self._management_lock:
                existing = await db.fetchval(
                    'SELECT id FROM feed_subscriptions WHERE guild_id = $1 AND feed_url = $2',
                    interaction.guild.id,
                    url,
                )
                count = await db.fetchval(
                    'SELECT COUNT(*) FROM feed_subscriptions WHERE guild_id = $1', interaction.guild.id
                )
                if existing is None and count >= FEED_MAX_SUBSCRIPTIONS:
                    await self._management_reply(
                        interaction,
                        'Feed Limit Reached',
                        f'This server allows {FEED_MAX_SUBSCRIPTIONS} subscriptions, including paused feeds. Remove one first.',
                        error=True,
                    )
                    return
                await db.execute(
                    """INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name, poll_interval_minutes)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (guild_id, feed_url) DO UPDATE SET
                           channel_id = $2, feed_name = $4, poll_interval_minutes = $5""",
                    interaction.guild.id,
                    channel.id,
                    url,
                    feed_name[:64],
                    interval_minutes,
                )
        except DatabaseUnavailableError:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Database Unavailable',
                    'Could not save feed subscription.',
                    contributor_source=__name__,
                    user=interaction.user,
                ),
                ephemeral=True,
            )
            return

        embed = await success_embed(
            'Feed Subscribed',
            f'**{feed_name[:64]}** is configured for {channel.mention} with a {interval_minutes}-minute interval. '
            'Existing pause and outage state are preserved; use `/feed resume` to restart a paused feed.',
            contributor_source=__name__,
            user=interaction.user,
        )
        embed.add_field(name='Feed URL', value=url[:100], inline=False)
        await safe_send(interaction, embed=embed, ephemeral=True)

    async def _management_reply(self, interaction, title: str, description: str, *, error: bool = False):
        factory = error_embed if error else success_embed
        embed = await factory(title, description, contributor_source=__name__, user=interaction.user)
        await safe_send(interaction, embed=embed, ephemeral=True)

    @staticmethod
    def _channel_problem(guild, channel) -> str | None:
        if not isinstance(channel, nextcord.TextChannel) or channel.guild.id != guild.id:
            return 'Choose a text channel in this server.'
        if guild.me is None:
            return 'The bot could not resolve its membership in this server.'
        permissions = channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            return 'The bot needs View Channel, Send Messages, and Embed Links in that channel.'
        return None

    @feed_group.subcommand(name='edit', description='Change a subscribed feed channel, name, or polling interval')
    @manage_guild_only()
    @safe_slash_command(requires_db=True)
    async def feed_edit(
        self,
        interaction: nextcord.Interaction,
        feed_url: str,
        channel: nextcord.TextChannel | None = nextcord.SlashOption(required=False),
        name: str | None = nextcord.SlashOption(required=False, max_length=64),
        interval_minutes: int | None = nextcord.SlashOption(required=False, min_value=10, max_value=1440),
    ):
        if not interaction.guild:
            await self._management_reply(interaction, 'Server Only', 'Use this command in a server.', error=True)
            return
        if channel is None and name is None and interval_minutes is None:
            await self._management_reply(
                interaction, 'No Changes', 'Choose a channel, name, or interval to change.', error=True
            )
            return
        if channel is not None and (problem := self._channel_problem(interaction.guild, channel)):
            await self._management_reply(interaction, 'Invalid Channel', problem, error=True)
            return
        if name is not None and not name.strip():
            await self._management_reply(interaction, 'Invalid Name', 'The name cannot be blank.', error=True)
            return
        row = await db.fetch_one(
            """UPDATE feed_subscriptions
               SET channel_id = COALESCE($3, channel_id), feed_name = COALESCE($4, feed_name),
                   poll_interval_minutes = COALESCE($5, poll_interval_minutes)
               WHERE guild_id = $1 AND feed_url = $2 RETURNING id""",
            interaction.guild.id,
            feed_url.strip(),
            channel.id if channel else None,
            name.strip() if name is not None else None,
            interval_minutes,
        )
        await self._management_reply(
            interaction,
            'Feed Updated' if row else 'Not Found',
            'Settings updated. Pause state, outage backoff, and delivery history were preserved.'
            if row
            else 'No subscription found for that URL in this server.',
            error=row is None,
        )

    async def _set_paused(self, interaction, feed_url: str, paused: bool):
        if not interaction.guild:
            await self._management_reply(interaction, 'Server Only', 'Use this command in a server.', error=True)
            return
        async with self._management_lock:
            sub = await db.fetch_one(
                'SELECT * FROM feed_subscriptions WHERE guild_id = $1 AND feed_url = $2',
                interaction.guild.id,
                feed_url.strip(),
            )
            if sub is None:
                await self._management_reply(
                    interaction, 'Not Found', 'No subscription found for that URL in this server.', error=True
                )
                return
            if not paused:
                channel = interaction.guild.get_channel(sub['channel_id'])
                problem = self._channel_problem(interaction.guild, channel)
                if problem:
                    await self._management_reply(interaction, 'Invalid Channel', problem, error=True)
                    return
            await db.execute(
                'UPDATE feed_subscriptions SET paused = $3 WHERE guild_id = $1 AND feed_url = $2',
                interaction.guild.id,
                feed_url.strip(),
                paused,
            )
        await self._management_reply(
            interaction,
            'Feed Paused' if paused else 'Feed Resumed',
            'Automatic posting is paused. Delivery history is retained.'
            if paused
            else 'Automatic polling is enabled. Existing interval and outage backoff remain in effect.',
        )

    @feed_group.subcommand(name='pause', description='Pause automatic feed posting without removing its history')
    @manage_guild_only()
    @safe_slash_command(requires_db=True)
    async def feed_pause(self, interaction: nextcord.Interaction, feed_url: str):
        await self._set_paused(interaction, feed_url, True)

    @feed_group.subcommand(name='resume', description='Resume automatic polling of a paused feed')
    @manage_guild_only()
    @safe_slash_command(requires_db=True)
    async def feed_resume(self, interaction: nextcord.Interaction, feed_url: str):
        await self._set_paused(interaction, feed_url, False)

    @feed_group.subcommand(name='remove', description='Remove a feed subscription')
    @manage_guild_only()
    @safe_slash_command(requires_db=True)
    async def feed_remove(
        self,
        interaction: nextcord.Interaction,
        feed_url: str,
    ):
        if not interaction.guild:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Server Only',
                    'This command can only be used in a server.',
                    contributor_source=__name__,
                    user=interaction.user,
                ),
                ephemeral=True,
            )
            return

        try:
            result = await db.execute(
                'DELETE FROM feed_subscriptions WHERE guild_id = $1 AND feed_url = $2',
                interaction.guild.id,
                feed_url.strip(),
            )
            # asyncpg returns 'DELETE N'
            deleted = int(result.split()[-1]) if result else 0
        except DatabaseUnavailableError:
            await self._management_reply(
                interaction, 'Database Unavailable', 'Could not remove the subscription. Try again later.', error=True
            )
            return

        if deleted:
            embed = await success_embed(
                'Feed Removed',
                f'Unsubscribed from `{feed_url[:80]}`.',
                contributor_source=__name__,
                user=interaction.user,
            )
        else:
            embed = await error_embed(
                'Not Found',
                'No subscription found for that URL in this server.',
                contributor_source=__name__,
                user=interaction.user,
            )
        await safe_send(interaction, embed=embed, ephemeral=True)

    async def _autocomplete_subscription(self, interaction: nextcord.Interaction, feed_url: str):
        """Suggest this server's subscriptions so staff don't have to retype exact feed URLs."""
        if not interaction.guild:
            await interaction.response.send_autocomplete([])
            return
        try:
            rows = await db.fetch_many(
                """SELECT feed_url, feed_name, paused FROM feed_subscriptions
                   WHERE guild_id = $1 AND (feed_url ILIKE $2 OR feed_name ILIKE $2)
                   ORDER BY feed_name, id LIMIT 25""",
                interaction.guild.id,
                f'%{(feed_url or "").strip()}%',
            )
            # Discord caps choice names and values at 100 characters; longer URLs must be typed.
            choices = {
                f'{row["feed_name"]}{" (paused)" if row["paused"] else ""} — {row["feed_url"]}'[:100]: row['feed_url']
                for row in rows
                if len(row['feed_url']) <= 100
            }
            await interaction.response.send_autocomplete(choices)
        except Exception:
            await interaction.response.send_autocomplete([])

    @feed_edit.on_autocomplete('feed_url')
    async def feed_edit_autocomplete(self, interaction: nextcord.Interaction, feed_url: str):
        await self._autocomplete_subscription(interaction, feed_url)

    @feed_pause.on_autocomplete('feed_url')
    async def feed_pause_autocomplete(self, interaction: nextcord.Interaction, feed_url: str):
        await self._autocomplete_subscription(interaction, feed_url)

    @feed_resume.on_autocomplete('feed_url')
    async def feed_resume_autocomplete(self, interaction: nextcord.Interaction, feed_url: str):
        await self._autocomplete_subscription(interaction, feed_url)

    @feed_remove.on_autocomplete('feed_url')
    async def feed_remove_autocomplete(self, interaction: nextcord.Interaction, feed_url: str):
        await self._autocomplete_subscription(interaction, feed_url)

    @feed_group.subcommand(name='list', description='List all guild feed subscriptions')
    @safe_slash_command(requires_db=True)
    async def feed_list(
        self, interaction: nextcord.Interaction, page: int = nextcord.SlashOption(min_value=1, default=1)
    ):
        if not interaction.guild:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Server Only',
                    'This command can only be used in a server.',
                    contributor_source=__name__,
                    user=interaction.user,
                ),
                ephemeral=True,
            )
            return

        try:
            subs = await db.fetch_many(
                """SELECT feed_url, feed_name, channel_id, poll_interval_minutes, last_polled_at,
                          paused, consecutive_failures, next_retry_at
                   FROM feed_subscriptions
                   WHERE guild_id = $1
                   ORDER BY feed_name, id""",
                interaction.guild.id,
            )
        except DatabaseUnavailableError:
            await self._management_reply(
                interaction, 'Database Unavailable', 'Could not load subscriptions. Try again later.', error=True
            )
            return

        if not subs:
            embed = await info_embed(
                'No Feed Subscriptions',
                'No RSS feeds are subscribed in this server. Use `/feed add` to subscribe.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        pages = max(1, (len(subs) + 9) // 10)
        if page > pages:
            await self._management_reply(interaction, 'Invalid Page', f'Choose a page from 1 to {pages}.', error=True)
            return
        embed = await info_embed(
            title=f'Feed Subscriptions ({len(subs)}) — Page {page}/{pages}',
            description=f'Server limit: {FEED_MAX_SUBSCRIPTIONS}. Use `/feed list page:` to view other pages.',
            contributor_source=__name__,
            user=interaction.user,
        )

        for sub in subs[(page - 1) * 10 : page * 10]:
            channel_mention = f'<#{sub["channel_id"]}>' if sub['channel_id'] else 'Not set'
            last = sub.get('last_polled_at')
            last_text = f'<t:{int(last.timestamp())}:R>' if last else 'Never'
            channel = interaction.guild.get_channel(sub['channel_id'])
            problem = (
                self._channel_problem(interaction.guild, channel) if channel else 'Channel not configured or deleted'
            )
            status = (
                'Paused'
                if sub['paused']
                else (
                    f'Channel unavailable: {problem}'
                    if problem
                    else (
                        f'Failing ({sub["consecutive_failures"]} attempts)'
                        if sub['consecutive_failures']
                        else ('Healthy' if last else 'Not polled yet')
                    )
                )
            )
            retry = sub['next_retry_at'] or (
                last + timedelta(minutes=sub['poll_interval_minutes'] or 30) if last else None
            )
            retry_text = (
                'Paused' if sub['paused'] else (f'<t:{int(retry.timestamp())}:R>' if retry else 'Next polling cycle')
            )
            embed.add_field(
                name=sub['feed_name'][:50],
                value=(
                    f'Status: {status}\nChannel: {channel_mention}\nNext attempt: {retry_text}\n'
                    f'Interval: {sub["poll_interval_minutes"]}m | Last polled: {last_text}\n'
                    f'`{sub["feed_url"][:60]}`'
                ),
                inline=False,
            )

        await safe_send(interaction, embed=embed, ephemeral=False)

    @feed_group.subcommand(name='test', description='Preview the latest entry from a feed URL')
    @manage_guild_only()
    @safe_slash_command()
    async def feed_test(
        self,
        interaction: nextcord.Interaction,
        feed_url: str,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            feed_data = await self.rss_service.fetch_feed(feed_url)
        except Exception:
            feed_data = None

        if not feed_data or not feed_data.get('entries'):
            embed = await error_embed(
                'No Entries',
                'Could not fetch any entries from that feed URL.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        entry = feed_data['entries'][0]
        embed = await self._create_feed_embed(entry, feed_data.get('title', 'Feed'))
        embed.set_footer(text=f'Feed: {feed_url[:80]}')
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ============================================================
    # Legacy /resource commands (kept for backward compatibility)
    # ============================================================

    @nextcord.slash_command(
        name='resource',
        description='Browse community resources and RSS feeds',
    )
    async def resource(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Resource Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/resource sources` — View this server’s subscriptions\n'
                '• `/resource latest` — Show latest entries\n'
                '• Use `/feed` for feed management'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @resource.subcommand(name='sources', description='List available resource sources')
    @safe_slash_command()
    async def feed_sources(self, interaction: nextcord.Interaction):
        if not interaction.guild:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Server Only',
                    'This command can only be used in a server.',
                    contributor_source=__name__,
                    user=interaction.user,
                ),
                ephemeral=True,
            )
            return

        await self.feed_list.callback(self, interaction, page=1)

    @resource.subcommand(name='latest', description='Show latest entries from a feed')
    @safe_slash_command()
    async def feed_latest(
        self,
        interaction: nextcord.Interaction,
        feed_url: str = nextcord.SlashOption(name='feed_url', description='RSS feed URL', required=True),
    ):
        await interaction.response.defer()

        feed_data = await self.rss_service.fetch_feed(feed_url)
        if not feed_data or not feed_data.get('entries'):
            embed = await info_embed(
                'No Entries Found',
                'No entries found for that feed.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.followup.send(embed=embed)
            return

        for entry in feed_data['entries'][:5]:
            embed = await self._create_feed_embed(entry, feed_data.get('title', 'Feed'))
            await interaction.followup.send(embed=embed)

    # ============================================================
    # Helpers
    # ============================================================

    async def _create_feed_embed(self, entry: dict, source_name: str) -> nextcord.Embed:
        desc = entry.get('description', '')
        if len(desc) > 1000:
            desc = desc[:1000] + '...'

        embed = await info_embed(
            title=entry.get('title', 'Untitled')[:256],
            description=desc,
            contributor_source=__name__,
        )
        link = entry.get('link', '')
        try:
            parsed_link = urlsplit(link)
            if parsed_link.scheme in ('http', 'https') and parsed_link.hostname and len(link) <= 2000:
                embed.url = link
        except ValueError:
            pass

        embed.add_field(name='Source', value=source_name[:50], inline=True)
        embed.add_field(name='Author', value=entry.get('author', 'Unknown')[:50], inline=True)
        embed.add_field(name='Published', value=entry.get('published', 'Unknown')[:100], inline=True)

        return embed


def setup(bot):
    bot.add_cog(Feeds(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.resources.feeds')
