"""
Stats Cog — Most Streamed, Most Played, Most Listened, Most Coded leaderboards
and server analytics with daily tracking.
"""

import logging
from datetime import UTC, datetime

import nextcord
from nextcord.ext import commands, tasks

from src.core.runtime_state import runtime_state
from src.database.database import db
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import (
    DatabaseUnavailableError,
    safe_background_task,
    safe_send,
    safe_slash_command,
)

logger = logging.getLogger('VEKA.stats')

# Unicode sparkline blocks (empty → full)
SPARKLINE_BLOCKS = [' ', '\u2582', '\u2583', '\u2584', '\u2585', '\u2586', '\u2587', '\u2588']


def _sparkline(values: list[int]) -> str:
    """Render a list of integers as a Unicode sparkline string."""
    if not values:
        return ''
    max_val = max(values) if max(values) > 0 else 1
    return ''.join(
        SPARKLINE_BLOCKS[min(len(SPARKLINE_BLOCKS) - 1, int(v / max_val * (len(SPARKLINE_BLOCKS) - 1)))] for v in values
    )


class Stats(commands.Cog):
    """Community activity statistics and leaderboards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._daily_joins: dict[int, int] = {}  # guild_id → join count today
        self._daily_leaves: dict[int, int] = {}  # guild_id → leave count today
        self.daily_stats_collector.start()

    def cog_unload(self):
        self.daily_stats_collector.cancel()

    # ============================================================
    # Daily Stats Background Task
    # ============================================================

    @tasks.loop(minutes=30)
    @safe_background_task(name='daily_stats_collector')
    async def daily_stats_collector(self):
        """Snapshot server metrics into server_stats_daily every 30 minutes."""
        if not runtime_state.db_available:
            return

        for guild in self.bot.guilds:
            try:
                online_count = sum(1 for m in guild.members if m.status != nextcord.Status.offline and not m.bot)
                await db.execute(
                    """INSERT INTO server_stats_daily (guild_id, stat_date, total_members, joins, leaves, max_online, boost_level)
                       VALUES ($1, CURRENT_DATE, $2, $3, $4, $5, $6)
                       ON CONFLICT (guild_id, stat_date)
                       DO UPDATE SET
                           total_members = $2,
                           joins = server_stats_daily.joins + $3,
                           leaves = server_stats_daily.leaves + $4,
                           max_online = GREATEST(server_stats_daily.max_online, $5),
                           boost_level = $6""",
                    guild.id,
                    guild.member_count or 0,
                    self._daily_joins.get(guild.id, 0),
                    self._daily_leaves.get(guild.id, 0),
                    online_count,
                    guild.premium_tier or 0,
                )
                # Reset daily counters after persisting
                self._daily_joins[guild.id] = 0
                self._daily_leaves[guild.id] = 0
            except DatabaseUnavailableError:
                break
            except Exception as e:
                logger.debug('Failed to snapshot stats for guild %s: %s', guild.id, e)

    @daily_stats_collector.before_loop
    async def before_daily_stats(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        if member.bot:
            return
        self._daily_joins[member.guild.id] = self._daily_joins.get(member.guild.id, 0) + 1

    @commands.Cog.listener()
    async def on_member_remove(self, member: nextcord.Member):
        if member.bot:
            return
        self._daily_leaves[member.guild.id] = self._daily_leaves.get(member.guild.id, 0) + 1

    # ============================================================
    # DB helpers
    # ============================================================

    async def _get_top_activity_details(self, activity_type: str, limit: int = 10) -> list[dict]:
        """Get top entries for an activity type, aggregated by total duration."""
        try:
            rows = await db.fetch(
                """
                SELECT user_id, activity_name, SUM(duration_minutes) AS total_minutes
                FROM user_activity_details
                WHERE activity_type = $1
                GROUP BY user_id, activity_name
                ORDER BY total_minutes DESC
                LIMIT $2
                """,
                activity_type,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch activity details for %s: %s', activity_type, exc)
            return []

    async def _get_top_activity_names_overall(self, activity_type: str, limit: int = 10) -> list[dict]:
        """Get top activity names aggregated across all users by total duration."""
        try:
            rows = await db.fetch(
                """
                SELECT activity_name, SUM(duration_minutes) AS total_minutes
                FROM user_activity_details
                WHERE activity_type = $1
                GROUP BY activity_name
                ORDER BY total_minutes DESC
                LIMIT $2
                """,
                activity_type,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch top activity names for %s: %s', activity_type, exc)
            return []

    async def _get_top_activity_by_user(self, activity_type: str, user_id: int, limit: int = 10) -> list[dict]:
        """Get a specific user's top entries for an activity type."""
        try:
            rows = await db.fetch(
                """
                SELECT activity_name, SUM(duration_minutes) AS total_minutes
                FROM user_activity_details
                WHERE activity_type = $1 AND user_id = $2
                GROUP BY activity_name
                ORDER BY total_minutes DESC
                LIMIT $3
                """,
                activity_type,
                str(user_id),
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch activity details for user %s: %s', user_id, exc)
            return []

    async def _get_top_streamers(self, limit: int = 10) -> list[dict]:
        """Get top streamers by total streaming minutes."""
        try:
            rows = await db.fetch(
                """
                SELECT discord_id, username, total_streaming_minutes
                FROM users
                WHERE total_streaming_minutes > 0
                ORDER BY total_streaming_minutes DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch top streamers: %s', exc)
            return []

    async def _get_top_gamers(self, limit: int = 10) -> list[dict]:
        """Get top gamers by total gaming minutes."""
        try:
            rows = await db.fetch(
                """
                SELECT discord_id, username, total_gaming_minutes
                FROM users
                WHERE total_gaming_minutes > 0
                ORDER BY total_gaming_minutes DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch top gamers: %s', exc)
            return []

    async def _get_top_listeners(self, limit: int = 10) -> list[dict]:
        """Get top listeners by total listening minutes."""
        try:
            rows = await db.fetch(
                """
                SELECT discord_id, username, total_listening_minutes
                FROM users
                WHERE total_listening_minutes > 0
                ORDER BY total_listening_minutes DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch top listeners: %s', exc)
            return []

    async def _get_top_radio_listeners(self, limit: int = 10) -> list[dict]:
        """Get top radio listeners from activity details."""
        return await self._get_top_activity_details('radio', limit)

    async def _get_top_coders(self, limit: int = 10) -> list[dict]:
        """Get top coders by total coding minutes."""
        try:
            rows = await db.fetch(
                """
                SELECT user_id, SUM(duration_minutes) AS total_minutes
                FROM user_activity_details
                WHERE activity_type = 'coding'
                GROUP BY user_id
                ORDER BY total_minutes DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug('Failed to fetch top coders: %s', exc)
            return []

    # ============================================================
    # Formatting helpers
    # ============================================================

    def _format_minutes(self, minutes: int) -> str:
        """Format minutes into a human-readable string."""
        if minutes < 60:
            return f'{minutes}m'
        hours, mins = divmod(minutes, 60)
        if hours < 24:
            return f'{hours}h {mins}m'
        days, hours = divmod(hours, 24)
        return f'{days}d {hours}h'

    def _resolve_member_name(self, user_id: str, guild: nextcord.Guild | None = None) -> str:
        """Resolve a user ID to a display name."""
        uid = int(user_id)
        if guild:
            member = guild.get_member(uid)
            if member:
                return member.display_name
        user = self.bot.get_user(uid)
        return user.display_name if user else f'User {uid}'

    # ============================================================
    # Commands — Most Streamed
    # ============================================================

    @nextcord.slash_command(
        name='most',
        description='Community activity leaderboards',
    )
    async def most_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Activity Leaderboards',
            description=(
                '**Available subcommands:**\n\n'
                '\u2022 `/most streamed` \u2014 Top streamers and games\n'
                '\u2022 `/most played` \u2014 Most popular games\n'
                '\u2022 `/most listened` \u2014 Top Spotify and listening\n'
                '\u2022 `/most coded` \u2014 Top coders and apps'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @most_group.subcommand(name='streamed', description='Top streamers and most streamed games')
    @safe_slash_command()
    async def most_streamed(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            description='What to show',
            required=False,
            choices=['hours', 'games'],
        ),
    ):
        """Show top streamers by hours or most popular games while streaming."""
        await interaction.response.defer()
        category = category or 'hours'

        if category == 'hours':
            data = await self._get_top_streamers()
            if not data:
                embed = await info_embed(
                    title='Most Streamed — Hours',
                    description='No streaming data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                name = self._resolve_member_name(row['discord_id'], guild=interaction.guild)
                minutes = row.get('total_streaming_minutes') or 0
                lines.append(f'**{medal}** {name}: {self._format_minutes(minutes)}')

            embed = await success_embed(
                title='Most Streamed — Hours',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            if data:
                top_member = interaction.guild.get_member(int(data[0]['discord_id'])) if interaction.guild else None
                if top_member:
                    embed.set_thumbnail(
                        url=top_member.avatar.url if top_member.avatar else top_member.default_avatar.url
                    )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

        elif category == 'games':
            data = await self._get_top_activity_names_overall('streaming_game', 10)
            if not data:
                embed = await info_embed(
                    title='Most Streamed — Games',
                    description='No streaming game data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                lines.append(f'**{medal}** {row["activity_name"]}: {self._format_minutes(row["total_minutes"])}')

            embed = await success_embed(
                title='Most Streamed — Games',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

    # ============================================================
    # Commands — Most Played (Games)
    # ============================================================

    @most_group.subcommand(name='played', description='Most popular games and top gamers')
    @safe_slash_command()
    async def most_played(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            description='What to show',
            required=False,
            choices=['games', 'users'],
        ),
    ):
        """Show most popular games server-wide or top gamers."""
        await interaction.response.defer()
        category = category or 'games'

        if category == 'games':
            data = await self._get_top_activity_names_overall('game', 10)
            if not data:
                embed = await info_embed(
                    title='Most Played — Games',
                    description='No gaming data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                lines.append(f'**{medal}** {row["activity_name"]}: {self._format_minutes(row["total_minutes"])}')

            embed = await success_embed(
                title='Most Played — Games',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

        elif category == 'users':
            data = await self._get_top_gamers()
            if not data:
                embed = await info_embed(
                    title='Most Played — Users',
                    description='No gaming data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                name = self._resolve_member_name(row['discord_id'], guild=interaction.guild)
                minutes = row.get('total_gaming_minutes') or 0
                lines.append(f'**{medal}** {name}: {self._format_minutes(minutes)}')

            embed = await success_embed(
                title='Most Played — Users',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            if data:
                top_member = interaction.guild.get_member(int(data[0]['discord_id'])) if interaction.guild else None
                if top_member:
                    embed.set_thumbnail(
                        url=top_member.avatar.url if top_member.avatar else top_member.default_avatar.url
                    )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

    # ============================================================
    # Commands — Most Listened
    # ============================================================

    @most_group.subcommand(name='listened', description='Top Spotify listening and radio listeners')
    @safe_slash_command()
    async def most_listened(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            description='What to show',
            required=False,
            choices=['spotify', 'radio', 'users'],
        ),
    ):
        """Show top Spotify songs/artists, radio listeners, or top listeners."""
        await interaction.response.defer()
        category = category or 'spotify'

        if category == 'spotify':
            data = await self._get_top_activity_names_overall('listening', 10)
            if not data:
                embed = await info_embed(
                    title='Most Listened — Spotify',
                    description='No listening data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                lines.append(f'**{medal}** {row["activity_name"]}: {self._format_minutes(row["total_minutes"])}')

            embed = await success_embed(
                title='Most Listened — Spotify',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

        elif category == 'radio':
            data = await self._get_top_radio_listeners()
            if not data:
                embed = await info_embed(
                    title='Most Listened — Radio',
                    description='No radio listening data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                name = self._resolve_member_name(row['user_id'], guild=interaction.guild)
                minutes = row.get('total_minutes') or 0
                lines.append(f'**{medal}** {name}: {self._format_minutes(minutes)}')

            embed = await success_embed(
                title='Most Listened — Radio',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

        elif category == 'users':
            data = await self._get_top_listeners()
            if not data:
                embed = await info_embed(
                    title='Most Listened — Users',
                    description='No listening data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                name = self._resolve_member_name(row['discord_id'], guild=interaction.guild)
                minutes = row.get('total_listening_minutes') or 0
                lines.append(f'**{medal}** {name}: {self._format_minutes(minutes)}')

            embed = await success_embed(
                title='Most Listened — Users',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            if data:
                top_member = interaction.guild.get_member(int(data[0]['discord_id'])) if interaction.guild else None
                if top_member:
                    embed.set_thumbnail(
                        url=top_member.avatar.url if top_member.avatar else top_member.default_avatar.url
                    )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

    # ============================================================
    # Commands — Most Coded
    # ============================================================

    @most_group.subcommand(name='coded', description='Top coders and most used coding apps')
    @safe_slash_command()
    async def most_coded(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            description='What to show',
            required=False,
            choices=['users', 'apps'],
        ),
    ):
        """Show top coders by hours or most used coding apps."""
        await interaction.response.defer()
        category = category or 'users'

        if category == 'users':
            data = await self._get_top_coders()
            if not data:
                embed = await info_embed(
                    title='Most Coded — Users',
                    description='No coding data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                name = self._resolve_member_name(row['user_id'], guild=interaction.guild)
                minutes = row.get('total_minutes') or 0
                lines.append(f'**{medal}** {name}: {self._format_minutes(minutes)}')

            embed = await success_embed(
                title='Most Coded — Users',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            if data:
                top_member = interaction.guild.get_member(int(data[0]['user_id'])) if interaction.guild else None
                if top_member:
                    embed.set_thumbnail(
                        url=top_member.avatar.url if top_member.avatar else top_member.default_avatar.url
                    )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

        elif category == 'apps':
            data = await self._get_top_activity_names_overall('coding', 10)
            if not data:
                embed = await info_embed(
                    title='Most Coded — Apps',
                    description='No coding app data recorded yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await interaction.followup.send(embed=embed)
                return

            medals = ['\U0001f947', '\U0001f948', '\U0001f949']
            lines = []
            for i, row in enumerate(data):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                lines.append(f'**{medal}** {row["activity_name"]}: {self._format_minutes(row["total_minutes"])}')

            embed = await success_embed(
                title='Most Coded — Apps',
                description='\n'.join(lines),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)

    @nextcord.slash_command(
        name='serverstats',
        description='View server-wide analytics and activity overview',
    )
    @safe_slash_command()
    async def serverstats_command(self, interaction: nextcord.Interaction):
        """Show server-wide analytics dashboard."""
        await interaction.response.defer()

        if not interaction.guild:
            await interaction.followup.send('This command can only be used in a server.')
            return

        try:
            # Total users with XP
            total_users_row = await db.fetch_one('SELECT COUNT(*) as count FROM users WHERE points > 0')
            total_users = total_users_row['count'] if total_users_row else 0

            # Total messages
            total_msgs_row = await db.fetch_one('SELECT SUM(total_messages) as total FROM users')
            total_messages = total_msgs_row['total'] if total_msgs_row else 0

            # Total voice minutes
            total_voice_row = await db.fetch_one('SELECT SUM(total_voice_minutes) as total FROM users')
            total_voice = total_voice_row['total'] if total_voice_row else 0

            # Total streaming minutes
            total_streaming_row = await db.fetch_one('SELECT SUM(total_streaming_minutes) as total FROM users')
            total_streaming = total_streaming_row['total'] if total_streaming_row else 0

            # Total gaming minutes
            total_gaming_row = await db.fetch_one('SELECT SUM(total_gaming_minutes) as total FROM users')
            total_gaming = total_gaming_row['total'] if total_gaming_row else 0

            # Total listening minutes
            total_listening_row = await db.fetch_one('SELECT SUM(total_listening_minutes) as total FROM users')
            total_listening = total_listening_row['total'] if total_listening_row else 0

            # Active users (active in last 7 days)
            active_week_row = await db.fetch_one(
                "SELECT COUNT(*) as count FROM users WHERE last_active >= NOW() - INTERVAL '7 days'"
            )
            active_week = active_week_row['count'] if active_week_row else 0

            # Active users (active in last 30 days)
            active_month_row = await db.fetch_one(
                "SELECT COUNT(*) as count FROM users WHERE last_active >= NOW() - INTERVAL '30 days'"
            )
            active_month = active_month_row['count'] if active_month_row else 0

            # Top XP holder
            top_xp_row = await db.fetch_one(
                'SELECT discord_id, points, level FROM users WHERE points > 0 ORDER BY points DESC LIMIT 1'
            )

            # Average level
            avg_level_row = await db.fetch_one('SELECT AVG(level) as avg_level FROM users WHERE points > 0')
            avg_level = round(avg_level_row['avg_level'], 1) if avg_level_row and avg_level_row['avg_level'] else 0

        except Exception as exc:
            logger.warning('Failed to fetch server stats: %s', exc)
            embed = await info_embed(
                title='Error',
                description='Could not fetch server statistics.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await interaction.followup.send(embed=embed)
            return

        def _format_min(m):
            if not m:
                return '0'
            if m >= 60:
                return f'{m / 60:.1f}h'
            return f'{m:,}'

        description = (
            f'\U0001f465 **Members**: {total_users:,} active \u2022 {active_week} this week \u2022 {active_month} this month\n\n'
            f'\U0001f4ac **Total Messages**: {total_messages:,}\n'
            f'\U0001f50a **Voice Time**: {_format_min(total_voice)}\n'
            f'\U0001f4fa **Streaming**: {_format_min(total_streaming)}\n'
            f'\U0001f3ae **Gaming**: {_format_min(total_gaming)}\n'
            f'\U0001f3b5 **Listening**: {_format_min(total_listening)}\n\n'
            f'\U0001f3af **Average Level**: {avg_level}'
        )

        if top_xp_row:
            top_uid = int(top_xp_row['discord_id'])
            top_member = interaction.guild.get_member(top_uid)
            top_name = top_member.display_name if top_member else f'User {top_uid}'
            description += (
                f'\n\U0001f3c6 **Top Member**: {top_name} '
                f'(Level {top_xp_row["level"] or 0} | {top_xp_row["points"] or 0:,} XP)'
            )

        embed = await success_embed(
            title=f'\U0001f3d7\ufe0f Server Stats \u2014 {interaction.guild.name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)

    # ============================================================
    # /stats server — Member growth with sparkline
    # ============================================================

    @nextcord.slash_command(name='stats', description='Server analytics and demographics')
    @safe_slash_command()
    async def stats_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Stats Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/stats server` — Server overview with 7-day growth sparkline\n'
                '• `/stats demographics` — Member activity tier breakdown'
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
                    'Server Only',
                    'This command can only be used in a server.',
                    contributor_source=__name__,
                    user=interaction.user,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            # Current totals
            total_members = interaction.guild.member_count or 0
            online_count = sum(
                1 for m in interaction.guild.members if m.status != nextcord.Status.offline and not m.bot
            )

            # 7-day daily stats from server_stats_daily
            rows = await db.fetch_many(
                """SELECT stat_date, total_members, joins, leaves
                   FROM server_stats_daily
                   WHERE guild_id = $1 AND stat_date >= CURRENT_DATE - INTERVAL '7 days'
                   ORDER BY stat_date ASC""",
                interaction.guild.id,
            )

            # 7-day join/leave totals
            week_joins = sum(r['joins'] or 0 for r in rows)
            week_leaves = sum(r['leaves'] or 0 for r in rows)

            # Sparkline: total_members over 7 days
            member_counts = [r['total_members'] or 0 for r in rows]
            if len(member_counts) < 7:
                # Pad with current count if not enough data
                member_counts = [total_members] * (7 - len(member_counts)) + member_counts
            growth_sparkline = _sparkline(member_counts[-7:])

            # Join sparkline
            join_counts = [r['joins'] or 0 for r in rows]
            if len(join_counts) < 7:
                join_counts = [0] * (7 - len(join_counts)) + join_counts
            join_sparkline = _sparkline(join_counts[-7:])

            # Boost level
            boost_level = interaction.guild.premium_tier or 0
            boost_count = interaction.guild.premium_subscription_count or 0

            # Most active channel (from user_activity_daily)
            active_channel_row = await db.fetch_one(
                """SELECT channel_id, SUM(messages) as total_msgs
                   FROM user_activity_daily
                   WHERE guild_id = $1 AND activity_date >= CURRENT_DATE - INTERVAL '7 days'
                   GROUP BY channel_id
                   ORDER BY total_msgs DESC LIMIT 1""",
                interaction.guild.id,
            )
            active_channel_text = 'N/A'
            if active_channel_row and active_channel_row['channel_id']:
                ch = interaction.guild.get_channel(active_channel_row['channel_id'])
                active_channel_text = ch.mention if ch else f'Channel {active_channel_row["channel_id"]}'

            description = (
                f'\U0001f465 **Members**: {total_members:,} total \u2022 {online_count} online\n\n'
                f'\U0001f4e3 **7-Day Growth**: +{week_joins} joins \u2014 {week_leaves} leaves '
                f'= **{week_joins - week_leaves:+d}** net\n'
                f'`{growth_sparkline}` (member count trend)\n'
                f'`{join_sparkline}` (daily joins)\n\n'
                f'\U0001f451 **Boosts**: Level {boost_level} \u2022 {boost_count} boosts\n'
                f'\U0001f4ac **Most Active Channel**: {active_channel_text}'
            )

        except Exception as exc:
            logger.warning('Failed to fetch server stats: %s', exc)
            description = 'Could not fetch server statistics.'

        embed = await success_embed(
            title=f'\U0001f3d7\ufe0f Server Analytics \u2014 {interaction.guild.name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)

    @stats_group.subcommand(name='demographics', description='Member activity tier breakdown')
    @safe_slash_command(requires_db=True)
    async def stats_demographics(self, interaction: nextcord.Interaction):
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

        await interaction.response.defer()

        try:
            total = await db.fetchval('SELECT COUNT(*) FROM users') or 0

            # Active: messaged in last 7 days
            active_7d = (
                await db.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '7 days'") or 0
            )

            # Active: last 30 days
            active_30d = (
                await db.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '30 days'") or 0
            )

            # Inactive: never active or last active > 30 days ago
            inactive = total - active_30d

            # XP tiers
            tier_active = await db.fetchval('SELECT COUNT(*) FROM users WHERE points >= 1000') or 0
            tier_regular = await db.fetchval('SELECT COUNT(*) FROM users WHERE points >= 100 AND points < 1000') or 0
            tier_new = await db.fetchval('SELECT COUNT(*) FROM users WHERE points > 0 AND points < 100') or 0
            tier_zero = await db.fetchval('SELECT COUNT(*) FROM users WHERE points = 0 OR points IS NULL') or 0

            description = (
                f'**Activity Tiers** (of {total:,} tracked users)\n\n'
                f'\U0001f525 **Active (7d)**: {active_7d:,} ({active_7d / max(total, 1) * 100:.1f}%)\n'
                f'\U0001f4a1 **Active (30d)**: {active_30d:,} ({active_30d / max(total, 1) * 100:.1f}%)\n'
                f'\U0001f4a4 **Inactive**: {inactive:,} ({inactive / max(total, 1) * 100:.1f}%)\n\n'
                f'**XP Distribution**\n'
                f'\U0001f31f **Power Users** (1000+ XP): {tier_active:,}\n'
                f'\u2b50 **Regulars** (100\u2013999 XP): {tier_regular:,}\n'
                f'\U0001f331 **Newcomers** (1\u201399 XP): {tier_new:,}\n'
                f'\U0001f6ab **No XP**: {tier_zero:,}'
            )

        except Exception as exc:
            logger.warning('Failed to fetch demographics: %s', exc)
            description = 'Could not fetch demographics data.'

        embed = await success_embed(
            title=f'\U0001f3d7\ufe0f Demographics \u2014 {interaction.guild.name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Stats(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.stats')
    return True
