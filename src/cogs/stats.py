"""
Stats Cog — activity leaderboards (/most) and per-server analytics (/serverstats, /stats).

- Joins/leaves are written to ``server_stats_daily`` as they happen (UTC date), so restarts lose nothing.
- Member count, peak online and boost level are snapshotted every 30 minutes.
- Server analytics come from this server's ``user_activity_daily`` rollups, not global totals.
- Presence-derived boards (games, coding, streaming) only cover servers that turned activity tracking
  on, and exclude members who ran ``/privacy optout``. Listening/Spotify is never tracked (content policy).
"""

import logging
from datetime import UTC, datetime, timedelta

import nextcord
from nextcord.ext import commands, tasks

from src.core.runtime_state import runtime_state
from src.database.database import db
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import DatabaseUnavailableError, safe_background_task, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.stats')

# Unicode sparkline blocks (empty → full)
SPARKLINE_BLOCKS = [' ', '▂', '▃', '▄', '▅', '▆', '▇', '█']
MEDALS = ['\U0001f947', '\U0001f948', '\U0001f949']

_UTC_TODAY = "(NOW() AT TIME ZONE 'UTC')::date"

_JOIN_LEAVE_SQL = f"""
INSERT INTO server_stats_daily (guild_id, stat_date, total_members, joins, leaves)
VALUES ($1, {_UTC_TODAY}, $2, $3, $4)
ON CONFLICT (guild_id, stat_date) DO UPDATE SET
    total_members = EXCLUDED.total_members,
    joins = server_stats_daily.joins + EXCLUDED.joins,
    leaves = server_stats_daily.leaves + EXCLUDED.leaves
"""

_SNAPSHOT_SQL = f"""
INSERT INTO server_stats_daily (guild_id, stat_date, total_members, max_online, boost_level)
VALUES ($1, {_UTC_TODAY}, $2, $3, $4)
ON CONFLICT (guild_id, stat_date) DO UPDATE SET
    total_members = EXCLUDED.total_members,
    max_online = GREATEST(server_stats_daily.max_online, EXCLUDED.max_online),
    boost_level = EXCLUDED.boost_level
"""


def _sparkline(values: list[int]) -> str:
    """Render a list of integers as a Unicode sparkline string."""
    if not values:
        return ''
    max_val = max(values) if max(values) > 0 else 1
    return ''.join(
        SPARKLINE_BLOCKS[min(len(SPARKLINE_BLOCKS) - 1, int(v / max_val * (len(SPARKLINE_BLOCKS) - 1)))] for v in values
    )


def _format_minutes(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes < 60:
        return f'{minutes}m'
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f'{hours}h {mins}m'
    days, hours = divmod(hours, 24)
    return f'{days}d {hours}h'


def _ranked(rows: list[dict], name_of, value_of) -> str:
    lines = []
    for i, row in enumerate(rows):
        medal = MEDALS[i] if i < 3 else f'#{i + 1}'
        lines.append(f'**{medal}** {name_of(row)}: {value_of(row)}')
    return '\n'.join(lines)


class Stats(commands.Cog):
    """Community activity statistics and leaderboards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_ready(self):
        if not self.daily_stats_collector.is_running():
            self.daily_stats_collector.start()

    def cog_unload(self):
        self.daily_stats_collector.cancel()

    # ============================================================
    # Daily server stats
    # ============================================================

    @tasks.loop(minutes=30)
    @safe_background_task(name='daily_stats_collector')
    async def daily_stats_collector(self):
        """Snapshot member count, peak online and boost level into today's (UTC) row."""
        if not runtime_state.db_available:
            return
        for guild in self.bot.guilds:
            try:
                online_count = sum(1 for m in guild.members if m.status != nextcord.Status.offline and not m.bot)
                await db.execute(
                    _SNAPSHOT_SQL, guild.id, guild.member_count or 0, online_count, guild.premium_tier or 0
                )
            except DatabaseUnavailableError:
                break
            except Exception as e:
                logger.debug('Failed to snapshot stats for guild %s: %s', guild.id, type(e).__name__)

    @daily_stats_collector.before_loop
    async def before_daily_stats(self):
        await self.bot.wait_until_ready()

    async def _record_join_leave(self, guild: nextcord.Guild, joins: int, leaves: int) -> None:
        if not runtime_state.db_available:
            return
        try:
            await db.execute(_JOIN_LEAVE_SQL, guild.id, guild.member_count or 0, joins, leaves)
        except Exception:
            logger.debug('Failed to record join/leave for guild %s', guild.id, exc_info=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        if not member.bot:
            await self._record_join_leave(member.guild, 1, 0)

    @commands.Cog.listener()
    async def on_member_remove(self, member: nextcord.Member):
        if not member.bot:
            await self._record_join_leave(member.guild, 0, 1)

    # ============================================================
    # DB helpers (presence data: opted-in members only)
    # ============================================================

    async def _top_names(self, activity_type: str, limit: int = 10) -> list[dict]:
        """Top activity names (games/apps) by total minutes across opted-in members."""
        try:
            rows = await db.fetch(
                """
                SELECT d.activity_name, SUM(d.duration_minutes) AS total_minutes
                FROM user_activity_details d
                JOIN users u ON u.discord_id = d.user_id AND u.presence_opt_in
                WHERE d.activity_type = $1
                GROUP BY d.activity_name
                ORDER BY total_minutes DESC
                LIMIT $2
                """,
                activity_type,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch top names for %s: %s', activity_type, type(exc).__name__)
            return []

    async def _top_users(self, column: str, limit: int = 10) -> list[dict]:
        """Top opted-in members by an all-time presence total (global)."""
        if column not in ('total_streaming_minutes', 'total_gaming_minutes', 'total_coding_minutes'):
            raise ValueError(column)
        try:
            rows = await db.fetch(
                f"""
                SELECT discord_id, {column} AS minutes
                FROM users
                WHERE presence_opt_in AND {column} > 0
                ORDER BY {column} DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch top users for %s: %s', column, type(exc).__name__)
            return []

    def _resolve_member_name(self, user_id, guild: nextcord.Guild | None = None) -> str:
        uid = int(user_id)
        member = guild.get_member(uid) if guild else None
        if member:
            return member.display_name
        user = self.bot.get_user(uid)
        return user.display_name if user else f'User {uid}'

    async def _send_board(
        self,
        interaction: nextcord.Interaction,
        title: str,
        rows: list[dict],
        name_of,
        value_of,
        empty: str,
        thumbnail_id=None,
    ) -> None:
        if not rows:
            embed = await info_embed(
                title=title,
                description=empty,
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await interaction.followup.send(embed=embed)
            return
        embed = await success_embed(
            title=title,
            description=_ranked(rows, name_of, value_of)
            + '\n\n*Tracked only in servers that enabled activity tracking; members can `/privacy optout`.*',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        if thumbnail_id is not None and interaction.guild:
            top = interaction.guild.get_member(int(thumbnail_id))
            if top:
                embed.set_thumbnail(url=top.display_avatar.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)

    # ============================================================
    # /most
    # ============================================================

    @nextcord.slash_command(name='most', description='Community activity leaderboards')
    async def most_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Activity Leaderboards',
            description=(
                '**Available subcommands:**\n\n'
                '• `/most streamed` — Top streamers and games\n'
                '• `/most played` — Most popular games\n'
                '• `/most coded` — Top coders and apps\n\n'
                'Tracked only in servers that enabled activity tracking; members can `/privacy optout`.'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @most_group.subcommand(name='streamed', description='Top streamers and most streamed games')
    @safe_slash_command(requires_db=True)
    async def most_streamed(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(description='What to show', required=False, choices=['hours', 'games']),
    ):
        await interaction.response.defer()
        if (category or 'hours') == 'hours':
            rows = await self._top_users('total_streaming_minutes')
            await self._send_board(
                interaction,
                'Most Streamed — Hours',
                rows,
                lambda r: self._resolve_member_name(r['discord_id'], interaction.guild),
                lambda r: _format_minutes(r['minutes']),
                'No streaming data recorded yet.',
                rows[0]['discord_id'] if rows else None,
            )
        else:
            rows = await self._top_names('streaming_game')
            await self._send_board(
                interaction,
                'Most Streamed — Games',
                rows,
                lambda r: r['activity_name'],
                lambda r: _format_minutes(r['total_minutes']),
                'No streaming game data recorded yet.',
            )

    @most_group.subcommand(name='played', description='Most popular games and top gamers')
    @safe_slash_command(requires_db=True)
    async def most_played(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(description='What to show', required=False, choices=['games', 'users']),
    ):
        await interaction.response.defer()
        if (category or 'games') == 'games':
            rows = await self._top_names('game')
            await self._send_board(
                interaction,
                'Most Played — Games',
                rows,
                lambda r: r['activity_name'],
                lambda r: _format_minutes(r['total_minutes']),
                'No gaming data recorded yet.',
            )
        else:
            rows = await self._top_users('total_gaming_minutes')
            await self._send_board(
                interaction,
                'Most Played — Users',
                rows,
                lambda r: self._resolve_member_name(r['discord_id'], interaction.guild),
                lambda r: _format_minutes(r['minutes']),
                'No gaming data recorded yet.',
                rows[0]['discord_id'] if rows else None,
            )

    @most_group.subcommand(name='coded', description='Top coders and most used coding apps')
    @safe_slash_command(requires_db=True)
    async def most_coded(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(description='What to show', required=False, choices=['users', 'apps']),
    ):
        await interaction.response.defer()
        if (category or 'users') == 'users':
            rows = await self._top_users('total_coding_minutes')
            await self._send_board(
                interaction,
                'Most Coded — Users',
                rows,
                lambda r: self._resolve_member_name(r['discord_id'], interaction.guild),
                lambda r: _format_minutes(r['minutes']),
                'No coding data recorded yet.',
                rows[0]['discord_id'] if rows else None,
            )
        else:
            rows = await self._top_names('coding')
            await self._send_board(
                interaction,
                'Most Coded — Apps',
                rows,
                lambda r: r['activity_name'],
                lambda r: _format_minutes(r['total_minutes']),
                'No coding app data recorded yet.',
            )

    # ============================================================
    # /serverstats — this server, from per-day rollups
    # ============================================================

    async def _guild_activity(self, guild_id: int, days: int | None) -> dict:
        """Sum this server's rollups over the last ``days`` UTC days (None = all time)."""
        today = datetime.now(UTC).date()
        since = today - timedelta(days=days - 1) if days else today.replace(year=2000, month=1, day=1)
        row = await db.fetch_one(
            """
            SELECT COUNT(DISTINCT user_id) AS active_users,
                   COALESCE(SUM(messages), 0) AS messages,
                   COALESCE(SUM(voice_minutes), 0) AS voice,
                   COALESCE(SUM(xp_earned), 0) AS xp
            FROM user_activity_daily
            WHERE guild_id = $1 AND activity_date >= $2
            """,
            guild_id,
            since,
        )
        return dict(row) if row else {'active_users': 0, 'messages': 0, 'voice': 0, 'xp': 0}

    @nextcord.slash_command(name='serverstats', description="This server's activity overview")
    @safe_slash_command(requires_db=True)
    async def serverstats_command(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        if not guild:
            await interaction.followup.send('This command can only be used in a server.')
            return

        week = await self._guild_activity(guild.id, 7)
        month = await self._guild_activity(guild.id, 30)
        alltime = await self._guild_activity(guild.id, None)
        top = await db.fetch_one(
            """SELECT user_id, SUM(xp_earned) AS xp FROM user_activity_daily
               WHERE guild_id = $1 AND activity_date >= $2
               GROUP BY user_id ORDER BY xp DESC LIMIT 1""",
            guild.id,
            datetime.now(UTC).date() - timedelta(days=29),
        )

        description = (
            f'\U0001f465 **Members**: {guild.member_count or 0:,} • active: '
            f'{week["active_users"]} this week, {month["active_users"]} in 30 days\n\n'
            f'\U0001f4ac **Messages**: {week["messages"]:,} (7d) • {month["messages"]:,} (30d) • '
            f'{alltime["messages"]:,} (all time)\n'
            f'\U0001f50a **Voice**: {_format_minutes(week["voice"])} (7d) • {_format_minutes(month["voice"])} '
            f'(30d) • {_format_minutes(alltime["voice"])} (all time)\n'
        )
        if top and top['xp']:
            description += f'\n\U0001f3c6 **Most active (30d)**: <@{top["user_id"]}> ({int(top["xp"]):,} XP)'
        description += '\n\n*Counted since per-server tracking began; XP and levels themselves are global.*'

        embed = await success_embed(
            title=f'\U0001f3d7️ Server Stats — {guild.name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=guild,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)

    # ============================================================
    # /stats
    # ============================================================

    @nextcord.slash_command(name='stats', description='Server analytics and demographics')
    async def stats_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Stats Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/stats server` — Server overview with 7-day growth sparkline\n'
                '• `/stats demographics` — Member activity tiers in this server'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @stats_group.subcommand(name='server', description='Server overview with 7-day member growth trend')
    @safe_slash_command(requires_db=True)
    async def stats_server(self, interaction: nextcord.Interaction):
        if not interaction.guild:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Server Only', 'This command can only be used in a server.', contributor_source=__name__
                ),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        guild = interaction.guild
        today = datetime.now(UTC).date()
        days = [today - timedelta(days=6 - i) for i in range(7)]
        try:
            rows = await db.fetch(
                """SELECT stat_date, total_members, joins, leaves
                   FROM server_stats_daily
                   WHERE guild_id = $1 AND stat_date BETWEEN $2 AND $3""",
                guild.id,
                days[0],
                today,
            )
            by_day = {r['stat_date']: r for r in rows}
            joins = [int(by_day[d]['joins'] or 0) if d in by_day else 0 for d in days]
            leaves = [int(by_day[d]['leaves'] or 0) if d in by_day else 0 for d in days]
            members: list[int] = []
            last = guild.member_count or 0
            for d in days:
                if d in by_day and by_day[d]['total_members']:
                    last = by_day[d]['total_members']
                members.append(last)
            online_count = sum(1 for m in guild.members if m.status != nextcord.Status.offline and not m.bot)
            active = await db.fetch_one(
                """SELECT user_id, SUM(messages) AS total_msgs FROM user_activity_daily
                   WHERE guild_id = $1 AND activity_date >= $2
                   GROUP BY user_id ORDER BY total_msgs DESC LIMIT 1""",
                guild.id,
                days[0],
            )
            active_text = (
                f'<@{active["user_id"]}> ({int(active["total_msgs"]):,} messages)'
                if active and active['total_msgs']
                else 'N/A'
            )
            description = (
                f'\U0001f465 **Members**: {guild.member_count or 0:,} total • {online_count} online\n\n'
                f'\U0001f4e3 **7-Day Growth**: +{sum(joins)} joins — {sum(leaves)} leaves '
                f'= **{sum(joins) - sum(leaves):+d}** net\n'
                f'`{_sparkline(members)}` (member count trend)\n'
                f'`{_sparkline(joins)}` (daily joins, UTC)\n\n'
                f'\U0001f451 **Boosts**: Level {guild.premium_tier or 0} • '
                f'{guild.premium_subscription_count or 0} boosts\n'
                f'\U0001f4ac **Most Active Member (7d)**: {active_text}'
            )
        except Exception as exc:
            logger.warning('Failed to fetch server stats: %s', type(exc).__name__)
            description = 'Could not fetch server statistics.'

        embed = await success_embed(
            title=f'\U0001f3d7️ Server Analytics — {guild.name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=guild,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)

    @stats_group.subcommand(name='demographics', description='Member activity tiers in this server')
    @safe_slash_command(requires_db=True)
    async def stats_demographics(self, interaction: nextcord.Interaction):
        if not interaction.guild:
            await safe_send(
                interaction,
                embed=await error_embed(
                    'Server Only', 'This command can only be used in a server.', contributor_source=__name__
                ),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        guild = interaction.guild
        humans = [m.id for m in guild.members if not m.bot]
        total = len(humans)
        today = datetime.now(UTC).date()
        try:
            row = await db.fetch_one(
                """
                SELECT COUNT(DISTINCT user_id) FILTER (WHERE activity_date >= $2) AS active_7d,
                       COUNT(DISTINCT user_id) FILTER (WHERE activity_date >= $3) AS active_30d
                FROM user_activity_daily WHERE guild_id = $1
                """,
                guild.id,
                today - timedelta(days=6),
                today - timedelta(days=29),
            )
            tiers = await db.fetch_one(
                """
                SELECT COUNT(*) FILTER (WHERE points >= 1000) AS power,
                       COUNT(*) FILTER (WHERE points >= 100 AND points < 1000) AS regular,
                       COUNT(*) FILTER (WHERE points > 0 AND points < 100) AS newcomer
                FROM users WHERE discord_id = ANY($1::text[])
                """,
                [str(uid) for uid in humans],
            )
            active_7d = row['active_7d'] if row else 0
            active_30d = row['active_30d'] if row else 0
            power, regular, newcomer = (tiers['power'], tiers['regular'], tiers['newcomer']) if tiers else (0, 0, 0)
            no_xp = max(0, total - power - regular - newcomer)
            inactive = max(0, total - active_30d)

            def pct(n: int) -> str:
                return f'{n / max(total, 1) * 100:.1f}%'

            description = (
                f'**Activity tiers** (of {total:,} members in this server)\n\n'
                f'\U0001f525 **Active (7d)**: {active_7d:,} ({pct(active_7d)})\n'
                f'\U0001f4a1 **Active (30d)**: {active_30d:,} ({pct(active_30d)})\n'
                f'\U0001f4a4 **Inactive (30d)**: {inactive:,} ({pct(inactive)})\n\n'
                f'**XP distribution** (global XP of these members)\n'
                f'\U0001f31f **Power users** (1000+ XP): {power:,}\n'
                f'⭐ **Regulars** (100–999 XP): {regular:,}\n'
                f'\U0001f331 **Newcomers** (1–99 XP): {newcomer:,}\n'
                f'\U0001f6ab **No XP**: {no_xp:,}'
            )
        except Exception as exc:
            logger.warning('Failed to fetch demographics: %s', type(exc).__name__)
            description = 'Could not fetch demographics data.'

        embed = await success_embed(
            title=f'\U0001f3d7️ Demographics — {guild.name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=guild,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Stats(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.stats')
    return True
