import logging
import time
from datetime import timedelta

import nextcord
from nextcord.ext import commands

from src.database.database import db
from src.utils.embeds import error_embed, info_embed, success_embed, veka_embed
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security import require_admin

logger = logging.getLogger('VEKA.admin.honeypot')

# Dedup cooldown: ignore repeat triggers from same user in same channel within N seconds
_TRIGGER_COOLDOWN_SECONDS = 5


class Honeypot(commands.Cog):
    """Trap channels that automatically punish spam bots."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._trigger_cooldowns: dict[tuple[int, int], float] = {}
        self._honeypot_cache: dict[int, dict] = {}
        self._cache_loaded = False

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def _load_cache(self) -> None:
        """Load all enabled honeypots into memory for fast on_message lookups."""
        if self._cache_loaded:
            return
        try:
            rows = await db.fetch('SELECT * FROM honeypots WHERE enabled = TRUE')
            self._honeypot_cache = {row['channel_id']: dict(row) for row in rows}
            self._cache_loaded = True
        except Exception:
            logger.warning('Failed to load honeypot cache', exc_info=True)

    def _invalidate_cache(self) -> None:
        self._cache_loaded = False
        self._honeypot_cache.clear()

    # ------------------------------------------------------------------
    # /honeypot slash command group
    # ------------------------------------------------------------------

    @nextcord.slash_command(
        name='honeypot',
        description='Honeypot anti-spam trap management',
    )
    async def honeypot_group(self, interaction: nextcord.Interaction) -> None:
        embed = await info_embed(
            title='Honeypot Commands',
            description=(
                '**Available subcommands:**\n\n'
                '\u2022 `/honeypot create` \u2014 Create a trap channel\n'
                '\u2022 `/honeypot list` \u2014 List all honeypots\n'
                '\u2022 `/honeypot view` \u2014 View honeypot details\n'
                '\u2022 `/honeypot delete` \u2014 Remove a honeypot\n'
                '\u2022 `/honeypot enable` \u2014 Enable a honeypot\n'
                '\u2022 `/honeypot disable` \u2014 Disable a honeypot\n'
                '\u2022 `/honeypot edit` \u2014 Edit honeypot settings\n'
                '\u2022 `/honeypot test` \u2014 Test honeypot permissions'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @honeypot_group.subcommand(name='create', description='Create a softban honeypot for a channel')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_create_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel to trap'),
        delete_messages_days: int = nextcord.SlashOption(
            description='Days of messages to delete (0-7)', default=1, required=False
        ),
    ) -> None:
        await self._create_honeypot(interaction, channel, delete_messages_days)

    @honeypot_group.subcommand(name='list', description='List all honeypots in this server')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_list_slash(self, interaction: nextcord.Interaction) -> None:
        await self._list_honeypots(interaction)

    @honeypot_group.subcommand(name='view', description='View details of a channel honeypot')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_view_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel to inspect'),
    ) -> None:
        await self._view_honeypot(interaction, channel)

    @honeypot_group.subcommand(name='delete', description='Remove a honeypot trap')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_delete_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel to untrap'),
    ) -> None:
        await self._delete_honeypot(interaction, channel)

    @honeypot_group.subcommand(name='enable', description='Enable a honeypot')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_enable_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel to enable'),
    ) -> None:
        await self._toggle_honeypot(interaction, channel, True)

    @honeypot_group.subcommand(name='disable', description='Disable a honeypot')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_disable_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel to disable'),
    ) -> None:
        await self._toggle_honeypot(interaction, channel, False)

    @honeypot_group.subcommand(name='edit', description='Edit honeypot action type')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_edit_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel to edit'),
        action_type: str = nextcord.SlashOption(
            description='New action type',
            choices={
                'Softban': 'softban',
                'Ban': 'ban',
                'Timeout': 'timeout',
                'Role': 'role',
            },
        ),
        delete_messages_days: int = nextcord.SlashOption(
            description='Days of messages to delete (0-7)', default=1, required=False
        ),
        timeout_hours: int = nextcord.SlashOption(
            description='Timeout duration in hours (1-672)', default=24, required=False
        ),
        role: nextcord.Role = nextcord.SlashOption(description='Role to assign (for role action type)', required=False),
    ) -> None:
        await self._edit_honeypot(interaction, channel, action_type, delete_messages_days, timeout_hours, role)

    @honeypot_group.subcommand(name='test', description='Dry-run test a honeypot channel')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def honeypot_test_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel to test'),
    ) -> None:
        await self._test_honeypot(interaction, channel)

    # ------------------------------------------------------------------
    # /logging slash command group
    # ------------------------------------------------------------------

    @nextcord.slash_command(
        name='logging',
        description='Honeypot logging configuration',
    )
    async def logging_group(self, interaction: nextcord.Interaction) -> None:
        embed = await info_embed(
            title='Logging Commands',
            description=(
                '**Available subcommands:**\n\n'
                '\u2022 `/logging setchannel` \u2014 Set alert channel\n'
                '\u2022 `/logging setrole` \u2014 Set notification role\n'
                '\u2022 `/logging clearrole` \u2014 Clear notification role\n'
                '\u2022 `/logging view` \u2014 View current config'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @logging_group.subcommand(name='setchannel', description='Set the logging channel for honeypot alerts')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def logging_set_channel_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Logging output channel'),
    ) -> None:
        await self._set_logging_channel(interaction, channel)

    @logging_group.subcommand(name='setrole', description='Set the notification role for honeypot alerts')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def logging_set_role_slash(
        self,
        interaction: nextcord.Interaction,
        role: nextcord.Role = nextcord.SlashOption(description='Role to ping on trigger'),
    ) -> None:
        await self._set_logging_role(interaction, role)

    @logging_group.subcommand(name='clearrole', description='Clear the notification role')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def logging_clear_role_slash(self, interaction: nextcord.Interaction) -> None:
        await self._clear_logging_role(interaction)

    @logging_group.subcommand(name='view', description='View the current logging configuration')
    @require_admin()
    @safe_slash_command(requires_db=True)
    async def logging_view_slash(self, interaction: nextcord.Interaction) -> None:
        await self._view_logging(interaction)

    # ------------------------------------------------------------------
    # !honeypot prefix command group
    # ------------------------------------------------------------------

    @commands.group(name='honeypot', invoke_without_command=True)
    @require_admin()
    async def honeypot_prefix(self, ctx: commands.Context) -> None:
        embed = await info_embed(
            title='Honeypot Commands',
            description='Trap channels to catch spam bots. Use `/honeypot` for the best experience.',
            user=ctx.author,
            contributor_source=__name__,
        )
        embed.add_field(
            name='Commands',
            value=(
                '`!honeypot create <channel> [delete_days]` - Create a softban honeypot\n'
                '`!honeypot list` - List all honeypots\n'
                '`!honeypot view <channel>` - View channel honeypot details\n'
                '`!honeypot delete <channel>` - Remove a honeypot\n'
                '`!honeypot enable <channel>` - Enable a honeypot\n'
                '`!honeypot disable <channel>` - Disable a honeypot\n'
                '`!honeypot edit <channel> <type>` - Edit action type\n'
                '`!honeypot test <channel>` - Dry-run test'
            ),
            inline=False,
        )
        await safe_send(ctx, embed=embed)

    @honeypot_prefix.command(name='create')
    @require_admin()
    async def honeypot_create_prefix(
        self, ctx: commands.Context, channel: nextcord.TextChannel, delete_days: int = 1
    ) -> None:
        await self._create_honeypot(ctx, channel, delete_days)

    @honeypot_prefix.command(name='list')
    @require_admin()
    async def honeypot_list_prefix(self, ctx: commands.Context) -> None:
        await self._list_honeypots(ctx)

    @honeypot_prefix.command(name='view')
    @require_admin()
    async def honeypot_view_prefix(self, ctx: commands.Context, channel: nextcord.TextChannel) -> None:
        await self._view_honeypot(ctx, channel)

    @honeypot_prefix.command(name='delete')
    @require_admin()
    async def honeypot_delete_prefix(self, ctx: commands.Context, channel: nextcord.TextChannel) -> None:
        await self._delete_honeypot(ctx, channel)

    @honeypot_prefix.command(name='enable')
    @require_admin()
    async def honeypot_enable_prefix(self, ctx: commands.Context, channel: nextcord.TextChannel) -> None:
        await self._toggle_honeypot(ctx, channel, True)

    @honeypot_prefix.command(name='disable')
    @require_admin()
    async def honeypot_disable_prefix(self, ctx: commands.Context, channel: nextcord.TextChannel) -> None:
        await self._toggle_honeypot(ctx, channel, False)

    @honeypot_prefix.command(name='test')
    @require_admin()
    async def honeypot_test_prefix(self, ctx: commands.Context, channel: nextcord.TextChannel) -> None:
        await self._test_honeypot(ctx, channel)

    # ------------------------------------------------------------------
    # !logging prefix command group
    # ------------------------------------------------------------------

    @commands.group(name='logging', invoke_without_command=True)
    @require_admin()
    async def logging_prefix(self, ctx: commands.Context) -> None:
        embed = await info_embed(
            title='Honeypot Logging Commands',
            description='Configure logging for honeypot triggers.',
            user=ctx.author,
            contributor_source=__name__,
        )
        embed.add_field(
            name='Commands',
            value=(
                '`!logging setchannel <channel>` - Set logging channel\n'
                '`!logging setrole <role>` - Set notification role\n'
                '`!logging clearrole` - Clear notification role\n'
                '`!logging view` - View logging config'
            ),
            inline=False,
        )
        await safe_send(ctx, embed=embed)

    @logging_prefix.command(name='setchannel')
    @require_admin()
    async def logging_set_channel_prefix(self, ctx: commands.Context, channel: nextcord.TextChannel) -> None:
        await self._set_logging_channel(ctx, channel)

    @logging_prefix.command(name='setrole')
    @require_admin()
    async def logging_set_role_prefix(self, ctx: commands.Context, role: nextcord.Role) -> None:
        await self._set_logging_role(ctx, role)

    @logging_prefix.command(name='clearrole')
    @require_admin()
    async def logging_clear_role_prefix(self, ctx: commands.Context) -> None:
        await self._clear_logging_role(ctx)

    @logging_prefix.command(name='view')
    @require_admin()
    async def logging_view_prefix(self, ctx: commands.Context) -> None:
        await self._view_logging(ctx)

    # ------------------------------------------------------------------
    # on_message listener — trigger honeypots
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message) -> None:
        if message.author.bot or message.webhook_id is not None or not message.guild:
            return

        await self._load_cache()

        honeypot = self._honeypot_cache.get(message.channel.id)
        if not honeypot or not honeypot.get('enabled'):
            return

        # Dedup cooldown
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        last = self._trigger_cooldowns.get(key, 0.0)
        if (now - last) < _TRIGGER_COOLDOWN_SECONDS:
            return
        self._trigger_cooldowns[key] = now

        action_type: str = honeypot['action_type']
        result = 'failed'
        delete_days = honeypot.get('delete_message_days') or 1

        try:
            member = message.guild.get_member(message.author.id)
            if member is None:
                return

            # Delete user's messages across ALL channels before taking action
            try:
                cross_deleted = await self._delete_user_messages_across_channels(
                    message.guild, message.author.id, delete_days
                )
                if cross_deleted > 0:
                    logger.info(
                        'Cross-channel cleanup: deleted %d messages from user %s in guild %s',
                        cross_deleted,
                        message.author.id,
                        message.guild.id,
                    )
            except Exception:
                logger.warning(
                    'Cross-channel message deletion failed for user %s',
                    message.author.id,
                    exc_info=True,
                )

            if action_type == 'softban':
                result = await self._execute_softban(message.guild, member, delete_days)
            elif action_type == 'ban':
                result = await self._execute_ban(message.guild, member, delete_days)
            elif action_type == 'timeout':
                result = await self._execute_timeout(message.guild, member, honeypot.get('timeout_hours') or 24)
            elif action_type == 'role':
                result = await self._execute_role(message.guild, member, honeypot.get('role_id'))
        except Exception:
            logger.error('Honeypot trigger failed for %s', message.author.id, exc_info=True)
            result = 'failed'

        # Log event (best effort — don't let logging failure crash moderation)
        try:
            preview = message.content[:500] if message.content else None
            await db.execute(
                """INSERT INTO honeypot_events
                   (guild_id, channel_id, user_id, honeypot_id, action_type,
                    action_result, message_id, message_content_preview)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                message.guild.id,
                message.channel.id,
                message.author.id,
                honeypot['id'],
                action_type,
                result,
                message.id,
                preview,
            )
        except Exception:
            logger.warning('Failed to log honeypot event', exc_info=True)

        # Send alert to logging channel
        await self._send_alert(message, honeypot, action_type, result)

    # ------------------------------------------------------------------
    # Moderation action executors
    # ------------------------------------------------------------------

    async def _delete_user_messages_across_channels(self, guild: nextcord.Guild, user_id: int, days: int) -> int:
        """Delete a user's messages across all accessible text channels.

        Scans every text channel the bot can see, fetches messages from the
        specified user within the time window, and bulk-deletes them.

        Returns the total number of messages deleted.
        """
        if days < 1:
            return 0

        cutoff = nextcord.utils.utcnow() - timedelta(days=days)
        total_deleted = 0

        for channel in guild.text_channels:
            try:
                # Skip channels where bot lacks permissions
                perms = channel.permissions_for(guild.me)
                if not perms.read_message_history or not perms.manage_messages:
                    continue

                deleted_in_channel = 0
                # Iterate in batches of 100 (Discord API limit)
                async for msg in channel.history(limit=None, after=cutoff, oldest_first=False):
                    if msg.author.id == user_id:
                        try:
                            await msg.delete()
                            deleted_in_channel += 1
                        except nextcord.NotFound:
                            pass  # Already deleted
                        except nextcord.Forbidden:
                            break  # No permission to delete in this channel
                        except Exception:
                            logger.debug('Failed to delete message %s in %s', msg.id, channel.id)

                if deleted_in_channel > 0:
                    total_deleted += deleted_in_channel
                    logger.info(
                        'Deleted %d messages from user %s in #%s',
                        deleted_in_channel,
                        user_id,
                        channel.name,
                    )
            except nextcord.Forbidden:
                continue
            except Exception:
                logger.debug('Failed to scan channel %s for user messages', channel.id, exc_info=True)

        return total_deleted

    async def _execute_softban(self, guild: nextcord.Guild, member: nextcord.Member, delete_days: int) -> str:
        try:
            await guild.ban(member, reason='Honeypot: spam bot detected', delete_message_seconds=delete_days * 86400)
            await guild.unban(member, reason='Honeypot: softban — ban + unban')
            return 'success'
        except nextcord.Forbidden:
            logger.warning('Missing permissions to softban %s in %s', member.id, guild.id)
            return 'failed'
        except Exception:
            logger.error('Softban failed for %s', member.id, exc_info=True)
            return 'failed'

    async def _execute_ban(self, guild: nextcord.Guild, member: nextcord.Member, delete_days: int) -> str:
        try:
            await guild.ban(member, reason='Honeypot: spam bot detected', delete_message_seconds=delete_days * 86400)
            return 'success'
        except nextcord.Forbidden:
            logger.warning('Missing permissions to ban %s in %s', member.id, guild.id)
            return 'failed'
        except Exception:
            logger.error('Ban failed for %s', member.id, exc_info=True)
            return 'failed'

    async def _execute_timeout(self, guild: nextcord.Guild, member: nextcord.Member, hours: int) -> str:
        try:
            # Discord limit: max 28 days
            hours = max(1, min(hours, 672))
            duration = timedelta(hours=hours)
            await member.timeout(duration, reason='Honeypot: spam bot detected')
            return 'success'
        except nextcord.Forbidden:
            logger.warning('Missing permissions to timeout %s in %s', member.id, guild.id)
            return 'failed'
        except Exception:
            logger.error('Timeout failed for %s', member.id, exc_info=True)
            return 'failed'

    async def _execute_role(self, guild: nextcord.Guild, member: nextcord.Member, role_id: int | None) -> str:
        if not role_id:
            logger.warning('Honeypot role action configured but no role_id set')
            return 'failed'
        try:
            role = guild.get_role(role_id)
            if not role:
                logger.warning('Role %s not found in guild %s', role_id, guild.id)
                return 'failed'
            # Validate hierarchy: bot's highest role must be above target role
            bot_member = guild.me
            if bot_member and bot_member.top_role <= role:
                logger.warning('Bot role hierarchy too low to assign role %s', role_id)
                return 'failed'
            await member.add_roles(role, reason='Honeypot: spam bot detected')
            return 'success'
        except nextcord.Forbidden:
            logger.warning('Missing permissions to assign role to %s', member.id)
            return 'failed'
        except Exception:
            logger.error('Role assignment failed for %s', member.id, exc_info=True)
            return 'failed'

    # ------------------------------------------------------------------
    # Alert sender
    # ------------------------------------------------------------------

    async def _send_alert(
        self,
        message: nextcord.Message,
        honeypot: dict,
        action_type: str,
        result: str,
    ) -> None:
        try:
            config = await db.fetch_one(
                'SELECT * FROM honeypot_logging_config WHERE guild_id = $1',
                message.guild.id,  # type: ignore[union-attr]
            )
            if not config or not config.get('logging_channel_id'):
                return

            log_channel = message.guild.get_channel(config['logging_channel_id'])  # type: ignore[union-attr]
            if not log_channel:
                return

            action_desc = {
                'softban': f'Softban (deleted {honeypot.get("delete_message_days", 1)} day(s) of messages)',
                'ban': f'Ban (deleted {honeypot.get("delete_message_days", 0)} day(s) of messages)',
                'timeout': f'Timeout ({honeypot.get("timeout_hours", 24)}h)',
                'role': f'Role assigned (<@&{honeypot.get("role_id")}>)',
            }.get(action_type, action_type)

            embed = await veka_embed(
                title='Honeypot Triggered',
                description=(
                    f'**User:** {message.author.mention} (`{message.author.id}`)\n'
                    f'**Channel:** {message.channel.mention}\n'
                    f'**Action:** {action_desc}\n'
                    f'**Result:** {result.title()}\n'
                    f'**Content preview:** {message.content[:200] if message.content else "*No text content*"}'
                ),
                color=nextcord.Color.orange(),
                user=message.author,
                guild=message.guild,
                contributor_source=__name__,
            )

            content = None
            if config.get('notification_role_id'):
                content = f'<@&{config["notification_role_id"]}>'

            await log_channel.send(content=content, embed=embed)  # type: ignore[union-attr]
        except Exception:
            logger.warning('Failed to send honeypot alert', exc_info=True)

    # ------------------------------------------------------------------
    # Shared command logic (slash + prefix delegate here)
    # ------------------------------------------------------------------

    async def _create_honeypot(
        self, target: commands.Context | nextcord.Interaction, channel: nextcord.TextChannel, delete_days: int
    ) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        existing = await db.fetch_one(
            'SELECT id FROM honeypots WHERE guild_id = $1 AND channel_id = $2',
            guild.id,
            channel.id,
        )
        if existing:
            embed = await error_embed(
                'Already Exists',
                f'{channel.mention} already has a honeypot configured.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author
        await db.execute(
            """INSERT INTO honeypots (guild_id, channel_id, action_type, delete_message_days, enabled, created_by)
               VALUES ($1, $2, 'softban', $3, TRUE, $4)""",
            guild.id,
            channel.id,
            delete_days,
            user.id,
        )
        self._invalidate_cache()

        embed = await success_embed(
            'Honeypot Created',
            f'{channel.mention} is now a softban honeypot (delete {delete_days} day(s) of messages).',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    async def _list_honeypots(self, target: commands.Context | nextcord.Interaction) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        rows = await db.fetch('SELECT * FROM honeypots WHERE guild_id = $1 ORDER BY created_at DESC', guild.id)
        if not rows:
            embed = await info_embed(
                'No Honeypots', 'No honeypots configured for this server.', contributor_source=__name__
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        lines: list[str] = []
        for row in rows:
            status = 'Enabled' if row['enabled'] else 'Disabled'
            ch = guild.get_channel(row['channel_id'])
            ch_name = ch.mention if ch else f'<#{row["channel_id"]}>'
            lines.append(f'• {ch_name} — **{row["action_type"]}** ({status})')

        embed = await veka_embed(
            title='Honeypots',
            description='\n'.join(lines),
            color=nextcord.Color.orange(),
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    async def _view_honeypot(
        self, target: commands.Context | nextcord.Interaction, channel: nextcord.TextChannel
    ) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        row = await db.fetch_one(
            'SELECT * FROM honeypots WHERE guild_id = $1 AND channel_id = $2',
            guild.id,
            channel.id,
        )
        if not row:
            embed = await error_embed('Not Found', f'No honeypot for {channel.mention}.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        status = 'Enabled' if row['enabled'] else 'Disabled'
        details = [
            f'**Channel:** {channel.mention}',
            f'**Action:** {row["action_type"]}',
            f'**Status:** {status}',
        ]
        if row.get('delete_message_days'):
            details.append(f'**Delete days:** {row["delete_message_days"]}')
        if row.get('timeout_hours'):
            details.append(f'**Timeout hours:** {row["timeout_hours"]}')
        if row.get('role_id'):
            details.append(f'**Role:** <@&{row["role_id"]}>')
        details.append(f'**Created:** <t:{int(row["created_at"].timestamp())}:R>')

        embed = await veka_embed(
            title='Honeypot Details',
            description='\n'.join(details),
            color=nextcord.Color.orange(),
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    async def _delete_honeypot(
        self, target: commands.Context | nextcord.Interaction, channel: nextcord.TextChannel
    ) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        result = await db.execute(
            'DELETE FROM honeypots WHERE guild_id = $1 AND channel_id = $2',
            guild.id,
            channel.id,
        )
        self._invalidate_cache()

        if 'DELETE 0' in result:
            embed = await error_embed('Not Found', f'No honeypot for {channel.mention}.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        embed = await success_embed(
            'Honeypot Deleted', f'Removed honeypot from {channel.mention}.', contributor_source=__name__
        )
        await safe_send(target, embed=embed)

    async def _toggle_honeypot(
        self, target: commands.Context | nextcord.Interaction, channel: nextcord.TextChannel, enabled: bool
    ) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author
        result = await db.execute(
            'UPDATE honeypots SET enabled = $1, updated_at = NOW(), updated_by = $2 WHERE guild_id = $3 AND channel_id = $4',
            enabled,
            user.id,
            guild.id,
            channel.id,
        )
        self._invalidate_cache()

        if 'UPDATE 0' in result:
            embed = await error_embed('Not Found', f'No honeypot for {channel.mention}.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        state = 'enabled' if enabled else 'disabled'
        embed = await success_embed(
            'Honeypot Updated', f'{channel.mention} honeypot {state}.', contributor_source=__name__
        )
        await safe_send(target, embed=embed)

    async def _edit_honeypot(
        self,
        target: commands.Context | nextcord.Interaction,
        channel: nextcord.TextChannel,
        action_type: str,
        delete_days: int,
        timeout_hours: int,
        role: nextcord.Role | None,
    ) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        row = await db.fetch_one(
            'SELECT id FROM honeypots WHERE guild_id = $1 AND channel_id = $2',
            guild.id,
            channel.id,
        )
        if not row:
            embed = await error_embed('Not Found', f'No honeypot for {channel.mention}.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Validate role hierarchy if assigning role action
        if action_type == 'role' and role:
            bot_member = guild.me
            if bot_member and bot_member.top_role <= role:
                embed = await error_embed(
                    'Role Hierarchy',
                    'Cannot assign a role equal to or above my highest role.',
                    contributor_source=__name__,
                )
                await safe_send(target, embed=embed, ephemeral=True)
                return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author
        await db.execute(
            """UPDATE honeypots
               SET action_type = $1, delete_message_days = $2, timeout_hours = $3,
                   role_id = $4, updated_at = NOW(), updated_by = $5
               WHERE guild_id = $6 AND channel_id = $7""",
            action_type,
            delete_days if action_type in ('softban', 'ban') else None,
            timeout_hours if action_type == 'timeout' else None,
            role.id if action_type == 'role' and role else None,
            user.id,
            guild.id,
            channel.id,
        )
        self._invalidate_cache()

        embed = await success_embed(
            'Honeypot Updated',
            f'{channel.mention} action type changed to **{action_type}**.',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    async def _test_honeypot(
        self, target: commands.Context | nextcord.Interaction, channel: nextcord.TextChannel
    ) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        checks: list[str] = []
        bot_member = guild.me
        if not bot_member:
            checks.append('Bot member not found')
        else:
            perms = channel.permissions_for(bot_member)
            checks.append(f'Ban members: {"OK" if perms.ban_members else "MISSING"}')
            checks.append(f'Moderate members: {"OK" if perms.moderate_members else "MISSING"}')
            checks.append(f'Manage roles: {"OK" if perms.manage_roles else "MISSING"}')
            checks.append(f'Send messages: {"OK" if perms.send_messages else "MISSING"}')

        row = await db.fetch_one(
            'SELECT * FROM honeypots WHERE guild_id = $1 AND channel_id = $2',
            guild.id,
            channel.id,
        )
        if row:
            status = 'Enabled' if row['enabled'] else 'Disabled'
            checks.append(f'Honeypot config: {status} ({row["action_type"]})')
        else:
            checks.append('Honeypot config: Not found')

        embed = await veka_embed(
            title=f'Test Results — {channel.name}',
            description='\n'.join(f'• {c}' for c in checks),
            color=nextcord.Color.orange(),
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    # ------------------------------------------------------------------
    # Logging config logic
    # ------------------------------------------------------------------

    async def _set_logging_channel(
        self, target: commands.Context | nextcord.Interaction, channel: nextcord.TextChannel
    ) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author
        await db.execute(
            """INSERT INTO honeypot_logging_config (guild_id, logging_channel_id, enabled, updated_by, updated_at)
               VALUES ($1, $2, TRUE, $3, NOW())
               ON CONFLICT (guild_id) DO UPDATE SET logging_channel_id = $2, updated_by = $3, updated_at = NOW()""",
            guild.id,
            channel.id,
            user.id,
        )

        embed = await success_embed(
            'Logging Channel Set',
            f'Honeypot alerts will be sent to {channel.mention}.',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    async def _set_logging_role(self, target: commands.Context | nextcord.Interaction, role: nextcord.Role) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author
        await db.execute(
            """INSERT INTO honeypot_logging_config (guild_id, notification_role_id, enabled, updated_by, updated_at)
               VALUES ($1, $2, TRUE, $3, NOW())
               ON CONFLICT (guild_id) DO UPDATE SET notification_role_id = $2, updated_by = $3, updated_at = NOW()""",
            guild.id,
            role.id,
            user.id,
        )

        embed = await success_embed(
            'Notification Role Set',
            f'{role.mention} will be pinged on honeypot triggers.',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    async def _clear_logging_role(self, target: commands.Context | nextcord.Interaction) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author
        await db.execute(
            """INSERT INTO honeypot_logging_config (guild_id, notification_role_id, enabled, updated_by, updated_at)
               VALUES ($1, NULL, TRUE, $2, NOW())
               ON CONFLICT (guild_id) DO UPDATE SET notification_role_id = NULL, updated_by = $2, updated_at = NOW()""",
            guild.id,
            user.id,
        )

        embed = await success_embed(
            'Notification Role Cleared', 'No role will be pinged on triggers.', contributor_source=__name__
        )
        await safe_send(target, embed=embed)

    async def _view_logging(self, target: commands.Context | nextcord.Interaction) -> None:
        guild = target.guild
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        row = await db.fetch_one('SELECT * FROM honeypot_logging_config WHERE guild_id = $1', guild.id)
        if not row:
            embed = await info_embed('Logging Config', 'No logging configuration set.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        ch = guild.get_channel(row['logging_channel_id']) if row.get('logging_channel_id') else None
        role = guild.get_role(row['notification_role_id']) if row.get('notification_role_id') else None
        status = 'Enabled' if row['enabled'] else 'Disabled'

        lines = [
            f'**Channel:** {ch.mention if ch else "Not set"}',
            f'**Notification role:** {role.mention if role else "Not set"}',
            f'**Enabled:** {status}',
        ]

        embed = await veka_embed(
            title='Logging Configuration',
            description='\n'.join(lines),
            color=nextcord.Color.orange(),
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Honeypot(bot))
    logger.info('Loaded cog: src.cogs.admin.honeypot')
