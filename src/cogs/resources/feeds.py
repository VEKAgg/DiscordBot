"""Feeds Cog — dynamic RSS feed management backed by the database."""

import logging

import nextcord
from nextcord.ext import commands, tasks

from src.database.database import db
from src.services.rss_service import RSSService
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import (
    DatabaseUnavailableError,
    safe_background_task,
    safe_send,
    safe_slash_command,
)

logger = logging.getLogger('VEKA.feeds')


class Feeds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rss_service = RSSService(bot=bot)
        self.feed_update.start()

    def cog_unload(self):
        self.feed_update.cancel()

    # ============================================================
    # Background Task — DB-backed feed polling
    # ============================================================

    @tasks.loop(minutes=15)
    @safe_background_task(name='feed_update')
    async def feed_update(self):
        """Poll all subscribed feeds and post new entries to configured channels."""
        try:
            subscriptions = await db.fetch_many(
                """SELECT id, guild_id, channel_id, feed_url, feed_name, poll_interval_minutes, last_polled_at
                   FROM feed_subscriptions"""
            )
        except DatabaseUnavailableError:
            logger.debug('Skipping feed update: database unavailable')
            return

        for sub in subscriptions:
            # Respect per-feed polling interval
            if sub['last_polled_at']:
                from datetime import UTC, datetime, timedelta

                last = sub['last_polled_at']
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if datetime.now(UTC) - last < timedelta(minutes=sub['poll_interval_minutes'] or 30):
                    continue

            try:
                feed_data = await self.rss_service.fetch_feed(sub['feed_url'])
                if not feed_data:
                    continue

                new_entries = await self.rss_service.process_and_dedupe(sub['feed_url'], feed_data['entries'])

                if new_entries:
                    channel = self.bot.get_channel(sub['channel_id'])
                    if channel and isinstance(channel, nextcord.TextChannel):
                        for entry in new_entries[:3]:
                            embed = await self._create_feed_embed(entry, sub['feed_name'])
                            try:
                                await channel.send(embed=embed)
                            except Exception as e:
                                logger.error('Failed to send feed to channel %s: %s', sub['channel_id'], e)

                # Update last_polled_at
                await db.execute(
                    'UPDATE feed_subscriptions SET last_polled_at = NOW() WHERE id = $1',
                    sub['id'],
                )

            except Exception as e:
                logger.error('Error polling feed %s: %s', sub['feed_url'], e)

    @feed_update.before_loop
    async def before_feed_update(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # /feed — Management Commands
    # ============================================================

    @nextcord.slash_command(name='feed', description='Manage RSS feed subscriptions')
    @safe_slash_command()
    async def feed_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Feed Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/feed add` — Subscribe to a new RSS feed\n'
                '• `/feed remove` — Remove a feed subscription\n'
                '• `/feed list` — List all guild feed subscriptions\n'
                '• `/feed test` — Preview the latest entry from a feed'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @feed_group.subcommand(name='add', description='Subscribe to a new RSS feed')
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

        feed_name = name or feed_data.get('title', url[:64])

        try:
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
            f'**{feed_name}** will post to {channel.mention} every {interval_minutes} minutes.',
            contributor_source=__name__,
            user=interaction.user,
        )
        embed.add_field(name='Feed URL', value=url[:100], inline=False)
        await safe_send(interaction, embed=embed, ephemeral=False)

    @feed_group.subcommand(name='remove', description='Remove a feed subscription')
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
                feed_url,
            )
            # asyncpg returns 'DELETE N'
            deleted = int(result.split()[-1]) if result else 0
        except DatabaseUnavailableError:
            deleted = 0

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

    @feed_group.subcommand(name='list', description='List all guild feed subscriptions')
    @safe_slash_command(requires_db=True)
    async def feed_list(self, interaction: nextcord.Interaction):
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
                """SELECT feed_url, feed_name, channel_id, poll_interval_minutes, last_polled_at
                   FROM feed_subscriptions
                   WHERE guild_id = $1
                   ORDER BY feed_name""",
                interaction.guild.id,
            )
        except DatabaseUnavailableError:
            subs = []

        if not subs:
            embed = await info_embed(
                'No Feed Subscriptions',
                'No RSS feeds are subscribed in this server. Use `/feed add` to subscribe.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = await info_embed(
            title=f'Feed Subscriptions ({len(subs)})',
            description='Active RSS feed subscriptions for this server.',
            contributor_source=__name__,
            user=interaction.user,
        )

        for sub in subs[:25]:
            channel_mention = f'<#{sub["channel_id"]}>' if sub['channel_id'] else 'Not set'
            last = sub.get('last_polled_at')
            last_text = f'<t:{int(last.timestamp())}:R>' if last else 'Never'
            embed.add_field(
                name=sub['feed_name'][:50],
                value=(
                    f'Channel: {channel_mention}\n'
                    f'Interval: {sub["poll_interval_minutes"]}m | Last polled: {last_text}\n'
                    f'`{sub["feed_url"][:60]}`'
                ),
                inline=False,
            )

        await safe_send(interaction, embed=embed, ephemeral=False)

    @feed_group.subcommand(name='test', description='Preview the latest entry from a feed URL')
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
                '• `/resource sources` — List feed categories\n'
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

        try:
            subs = await db.fetch_many(
                'SELECT DISTINCT feed_name FROM feed_subscriptions WHERE guild_id = $1 ORDER BY feed_name',
                interaction.guild.id,
            )
        except DatabaseUnavailableError:
            subs = []

        embed = await info_embed(
            title='Available Feeds',
            description=f'{len(subs)} feed source{"s" if len(subs) != 1 else ""} subscribed in this server.',
            contributor_source=__name__,
            user=interaction.user,
        )

        for sub in subs:
            embed.add_field(name=sub['feed_name'], value='\u200b', inline=True)

        if not subs:
            embed.description = 'No feeds subscribed yet. Use `/feed add` to subscribe.'

        await safe_send(interaction, embed=embed)

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
            title=entry.get('title', 'Untitled'),
            description=desc,
            contributor_source=__name__,
        )
        if entry.get('link') and entry['link'] != '#':
            embed.url = entry['link']

        embed.add_field(name='Source', value=source_name[:50], inline=True)
        embed.add_field(name='Author', value=entry.get('author', 'Unknown')[:50], inline=True)
        embed.add_field(name='Published', value=entry.get('published', 'Unknown'), inline=True)

        return embed


def setup(bot):
    bot.add_cog(Feeds(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.resources.feeds')
