"""
Moderation Cog — Warnings, auto-escalation, lockdown, and mod stats.

Founders can toggle server lockdown. Staff can warn, view, and clear warnings.
Auto-escalation applies mute/ban when warning thresholds are reached.
"""

from __future__ import annotations

import logging

import nextcord
from nextcord.ext import commands

from src.config.config import STAFF_CHANNEL_ID
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import alert_embed, error_embed, info_embed, success_embed, veka_embed
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security import require_mod, require_staff
from src.utils.security.rbac import require_founder

logger = logging.getLogger('VEKA.admin.moderation')


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.lockdown_active = False

    # ============================================================
    # Panic / Lockdown (Founder only)
    # ============================================================

    async def panic_slash(self, interaction: nextcord.Interaction) -> None:
        """Toggle server lockdown. Sends critical alert to staff channel with @everyone."""
        await self._toggle_lockdown(interaction)

    @commands.command(name='panic')
    @require_founder()
    async def panic_prefix(self, ctx: commands.Context) -> None:
        """Toggle server lockdown (Founder only)"""
        await self._toggle_lockdown(ctx)

    async def lockdown_slash(self, interaction: nextcord.Interaction) -> None:
        """Alias for /panic"""
        await self._toggle_lockdown(interaction)

    @commands.command(name='lockdown')
    @require_founder()
    async def lockdown_prefix(self, ctx: commands.Context) -> None:
        """Alias for !panic"""
        await self._toggle_lockdown(ctx)

    async def _toggle_lockdown(self, target: commands.Context | nextcord.Interaction) -> None:
        self.lockdown_active = not self.lockdown_active
        status = 'ACTIVATED' if self.lockdown_active else 'DEACTIVATED'

        staff_channel = self.bot.get_channel(STAFF_CHANNEL_ID)
        if staff_channel:
            embed = await alert_embed(
                title=f'LOCKDOWN {status}',
                description=(
                    f'Server lockdown has been **{status.lower()}** by a Founder.\n\n'
                    f'**All non-essential operations are suspended.**'
                    if self.lockdown_active
                    else f'Server lockdown has been **{status.lower()}**.\n\nNormal operations have resumed.'
                ),
                severity='CRITICAL' if self.lockdown_active else 'INFO',
            )
            try:
                await staff_channel.send(content='@everyone', embed=embed)
            except Exception as e:
                logger.error('Failed to send lockdown alert: %s', e)

        embed = await alert_embed(
            title=f'Lockdown {status}',
            description=f'Server lockdown has been **{status.lower()}**.',
            severity='CRITICAL' if self.lockdown_active else 'INFO',
        )
        await safe_send(target, embed=embed, ephemeral=True)

    # ============================================================
    # /warn — Issue a warning with auto-escalation
    # ============================================================

    @nextcord.slash_command(name='warn', description='Issue a warning to a member')
    @require_mod()
    @safe_slash_command(requires_db=True)
    async def warn_slash(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member = nextcord.SlashOption(description='Member to warn'),
        reason: str = nextcord.SlashOption(description='Reason for the warning'),
    ) -> None:
        await self._warn(interaction, user, reason)

    @commands.command(name='warn')
    @require_mod()
    async def warn_prefix(self, ctx: commands.Context, user: nextcord.Member, *, reason: str) -> None:
        """Warn a member (Staff only)"""
        await self._warn(ctx, user, reason)

    async def _warn(
        self,
        target: commands.Context | nextcord.Interaction,
        user: nextcord.Member,
        reason: str,
    ) -> None:
        guild = getattr(target, 'guild', None)
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        moderator = target.user if isinstance(target, nextcord.Interaction) else target.author

        # Insert warning
        if runtime_state.db_available:
            try:
                await db.execute(
                    """INSERT INTO warnings (guild_id, user_id, moderator_id, reason)
                       VALUES ($1, $2, $3, $4)""",
                    guild.id,
                    user.id,
                    moderator.id,
                    reason,
                )
            except Exception:
                logger.error('Failed to insert warning for %s in %s', user.id, guild.id, exc_info=True)
                embed = await error_embed('DB Error', 'Failed to record the warning.', contributor_source=__name__)
                await safe_send(target, embed=embed, ephemeral=True)
                return

            # Count active warnings
            try:
                active_count = await db.fetchval(
                    'SELECT COUNT(*) FROM warnings WHERE guild_id = $1 AND user_id = $2 AND active = TRUE',
                    guild.id,
                    user.id,
                )
            except Exception:
                active_count = 0
        else:
            embed = await error_embed('DB Unavailable', 'Cannot issue warnings right now.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # DM the warned user
        try:
            dm_embed = await veka_embed(
                title=f'Warning — {guild.name}',
                description=(
                    f'You have been warned in **{guild.name}**.\n\n'
                    f'**Reason:** {reason}\n'
                    f'**Active warnings:** {active_count}'
                ),
                contributor_source=__name__,
            )
            await user.send(embed=dm_embed)
        except nextcord.Forbidden:
            logger.info('Could not DM user %s about warning', user.id)
        except Exception:
            logger.warning('Failed to DM warned user %s', user.id, exc_info=True)

        # Auto-escalation
        settings = await guild_settings_service.get_settings(guild.id)
        mute_threshold = settings.warn_mute_threshold or 3
        ban_threshold = settings.warn_ban_threshold or 5

        escalation_msg = ''
        if active_count >= ban_threshold:
            try:
                await guild.ban(user, reason=f'Auto-ban: reached {active_count} warnings')
                escalation_msg = f'\n\n:rotating_light: **Auto-ban triggered** — {active_count} active warnings reached the ban threshold ({ban_threshold}).'
                logger.info('Auto-banned %s in %s after %d warnings', user.id, guild.id, active_count)
            except nextcord.Forbidden:
                escalation_msg = '\n\n:warning: Auto-ban could not be applied — missing permissions.'
            except Exception:
                escalation_msg = '\n\n:warning: Auto-ban failed due to an error.'
        elif active_count >= mute_threshold:
            muted_role_id = settings.muted_role_id
            if muted_role_id:
                muted_role = guild.get_role(muted_role_id)
                if muted_role:
                    try:
                        await user.add_roles(muted_role, reason=f'Auto-mute: reached {active_count} warnings')
                        escalation_msg = f'\n\n:mute: **Auto-mute triggered** — {active_count} active warnings reached the mute threshold ({mute_threshold}).'
                        logger.info('Auto-muted %s in %s after %d warnings', user.id, guild.id, active_count)
                    except nextcord.Forbidden:
                        escalation_msg = '\n\n:warning: Auto-mute could not be applied — missing permissions.'
                    except Exception:
                        escalation_msg = '\n\n:warning: Auto-mute failed due to an error.'
                else:
                    escalation_msg = f'\n\n:mute: **Auto-mute threshold reached** ({mute_threshold}) but muted role not found. Configure it with `/setup set`.'
            else:
                escalation_msg = f'\n\n:mute: **Auto-mute threshold reached** ({mute_threshold}) but no muted role configured. Configure it with `/setup set`.'

        embed = await success_embed(
            'Warning Issued',
            f'**User:** {user.mention}\n**Reason:** {reason}\n**Active warnings:** {active_count}{escalation_msg}',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    # ============================================================
    # /warnings — View warnings for a user
    # ============================================================

    @nextcord.slash_command(name='warnings', description='View warnings for a member')
    @require_mod()
    @safe_slash_command(requires_db=True)
    async def warnings_slash(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member = nextcord.SlashOption(description='Member to inspect'),
    ) -> None:
        await self._warnings(interaction, user)

    @commands.command(name='warnings')
    @require_mod()
    async def warnings_prefix(self, ctx: commands.Context, user: nextcord.Member) -> None:
        """View warnings for a member (Staff only)"""
        await self._warnings(ctx, user)

    async def _warnings(
        self,
        target: commands.Context | nextcord.Interaction,
        user: nextcord.Member,
    ) -> None:
        guild = getattr(target, 'guild', None)
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        if not runtime_state.db_available:
            embed = await error_embed('DB Unavailable', 'Cannot fetch warnings right now.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        try:
            rows = await db.fetch(
                """SELECT id, moderator_id, reason, created_at, active
                   FROM warnings WHERE guild_id = $1 AND user_id = $2
                   ORDER BY created_at DESC""",
                guild.id,
                user.id,
            )
        except Exception:
            logger.error('Failed to fetch warnings for %s in %s', user.id, guild.id, exc_info=True)
            embed = await error_embed('DB Error', 'Failed to fetch warnings.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        if not rows:
            embed = await info_embed('No Warnings', f'{user.mention} has no warnings.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        active_count = sum(1 for r in rows if r['active'])

        lines = []
        for row in rows[:25]:  # Cap at 25 to avoid embed field limits
            status = '**Active**' if row['active'] else '~~Cleared~~'
            ts = f'<t:{int(row["created_at"].timestamp())}:R>' if row['created_at'] else 'Unknown'
            moderator = f'<@{row["moderator_id"]}>' if row['moderator_id'] else 'Unknown'
            lines.append(f'`#{row["id"]}` — {status} — {ts}\n  Reason: {row["reason"]}\n  Moderator: {moderator}')

        description = f'**{user.mention}** — {active_count} active / {len(rows)} total warnings\n\n'
        description += '\n\n'.join(lines)

        if len(rows) > 25:
            description += f'\n\n*...and {len(rows) - 25} more warnings.*'

        embed = await veka_embed(
            title=f'Warnings — {user}',
            description=description,
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed, ephemeral=True)

    # ============================================================
    # /clearwarnings — Clear all active warnings
    # ============================================================

    @nextcord.slash_command(name='clearwarnings', description='Clear all active warnings for a member')
    @require_mod()
    @safe_slash_command(requires_db=True)
    async def clearwarnings_slash(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member = nextcord.SlashOption(description='Member to clear warnings for'),
    ) -> None:
        await self._clearwarnings(interaction, user)

    @commands.command(name='clearwarnings')
    @require_mod()
    async def clearwarnings_prefix(self, ctx: commands.Context, user: nextcord.Member) -> None:
        """Clear all active warnings for a member (Staff only)"""
        await self._clearwarnings(ctx, user)

    async def _clearwarnings(
        self,
        target: commands.Context | nextcord.Interaction,
        user: nextcord.Member,
    ) -> None:
        guild = getattr(target, 'guild', None)
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        if not runtime_state.db_available:
            embed = await error_embed('DB Unavailable', 'Cannot clear warnings right now.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        try:
            result = await db.execute(
                """UPDATE warnings SET active = FALSE
                   WHERE guild_id = $1 AND user_id = $2 AND active = TRUE""",
                guild.id,
                user.id,
            )
            count = int(result.split()[-1]) if result and 'UPDATE' in result else 0
        except Exception:
            logger.error('Failed to clear warnings for %s in %s', user.id, guild.id, exc_info=True)
            embed = await error_embed('DB Error', 'Failed to clear warnings.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        embed = await success_embed(
            'Warnings Cleared',
            f'Cleared **{count}** active warning(s) for {user.mention}.',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed)

    # ============================================================
    # /modstats — Moderation activity over past 30 days
    # ============================================================

    @nextcord.slash_command(name='modstats', description='Moderation activity over the past 30 days')
    @require_staff()
    @safe_slash_command(requires_db=True)
    async def modstats_slash(self, interaction: nextcord.Interaction) -> None:
        await self._modstats(interaction)

    @commands.command(name='modstats')
    @require_staff()
    async def modstats_prefix(self, ctx: commands.Context) -> None:
        """Moderation activity over the past 30 days (Staff only)"""
        await self._modstats(ctx)

    async def _modstats(self, target: commands.Context | nextcord.Interaction) -> None:
        guild = getattr(target, 'guild', None)
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        if not runtime_state.db_available:
            embed = await error_embed(
                'DB Unavailable', 'Cannot fetch mod stats right now.', contributor_source=__name__
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        try:
            # Audit log actions
            audit_rows = await db.fetch(
                """SELECT moderator_id, action_type, COUNT(*) as cnt
                   FROM audit_logs WHERE guild_id = $1 AND created_at >= NOW() - INTERVAL '30 days'
                   GROUP BY moderator_id, action_type""",
                guild.id,
            )

            # Warning counts
            warn_rows = await db.fetch(
                """SELECT moderator_id, COUNT(*) as cnt
                   FROM warnings WHERE guild_id = $1 AND created_at >= NOW() - INTERVAL '30 days'
                   GROUP BY moderator_id""",
                guild.id,
            )
        except Exception:
            logger.error('Failed to fetch mod stats for %s', guild.id, exc_info=True)
            embed = await error_embed('DB Error', 'Failed to fetch moderation statistics.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Aggregate by moderator
        stats: dict[int, dict[str, int]] = {}
        for row in audit_rows:
            mid = row['moderator_id']
            if mid not in stats:
                stats[mid] = {'bans': 0, 'kicks': 0, 'mutes': 0, 'warns': 0}
            action = row['action_type']
            if action in ('ban', 'softban'):
                stats[mid]['bans'] += row['cnt']
            elif action == 'kick':
                stats[mid]['kicks'] += row['cnt']
            elif action in ('timeout', 'mute'):
                stats[mid]['mutes'] += row['cnt']

        for row in warn_rows:
            mid = row['moderator_id']
            if mid not in stats:
                stats[mid] = {'bans': 0, 'kicks': 0, 'mutes': 0, 'warns': 0}
            stats[mid]['warns'] += row['cnt']

        if not stats:
            embed = await info_embed(
                'No Activity', 'No moderation activity in the past 30 days.', contributor_source=__name__
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Sort by total actions descending
        sorted_stats = sorted(stats.items(), key=lambda x: sum(x[1].values()), reverse=True)

        lines = []
        for mid, counts in sorted_stats[:15]:
            total = sum(counts.values())
            lines.append(
                f'<@{mid}> — **{total}** actions\n'
                f'  Bans: {counts["bans"]} | Kicks: {counts["kicks"]} | Mutes: {counts["mutes"]} | Warns: {counts["warns"]}'
            )

        embed = await veka_embed(
            title='Moderation Stats — Past 30 Days',
            description='\n\n'.join(lines),
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed, ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Moderation(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.moderation')
