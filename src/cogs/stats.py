"""
Stats Cog — Most Streamed, Most Played, Most Listened, Most Coded leaderboards.

Provides community statistics for activity types tracked by the RPG manager.
"""

import logging
from datetime import UTC, datetime

import nextcord
from nextcord.ext import commands

from src.database.database import db
from src.utils.embeds import info_embed, success_embed
from src.utils.safety import safe_slash_command

logger = logging.getLogger('VEKA.stats')


class Stats(commands.Cog):
    """Community activity statistics and leaderboards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ============================================================
    # DB helpers
    # ============================================================

    async def _get_top_activity_details(
        self, activity_type: str, limit: int = 10
    ) -> list[dict]:
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

    async def _get_top_activity_names_overall(
        self, activity_type: str, limit: int = 10
    ) -> list[dict]:
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

    async def _get_top_activity_by_user(
        self, activity_type: str, user_id: int, limit: int = 10
    ) -> list[dict]:
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

    def _resolve_member_name(self, user_id: str) -> str:
        """Resolve a user ID to a display name."""
        uid = int(user_id)
        member = self.bot.get_user(uid)
        return member.display_name if member else f'User {uid}'

    # ============================================================
    # Commands — Most Streamed
    # ============================================================

    @nextcord.slash_command(name='most', description='Community activity leaderboards')
    async def most_group(self, interaction: nextcord.Interaction):
        pass

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
                name = self._resolve_member_name(row['discord_id'])
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
                top_member = self.bot.get_user(int(data[0]['discord_id']))
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
                name = self._resolve_member_name(row['discord_id'])
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
                top_member = self.bot.get_user(int(data[0]['discord_id']))
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
                name = self._resolve_member_name(row['user_id'])
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
                name = self._resolve_member_name(row['discord_id'])
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
                top_member = self.bot.get_user(int(data[0]['discord_id']))
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
                name = self._resolve_member_name(row['user_id'])
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
                top_member = self.bot.get_user(int(data[0]['user_id']))
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


def setup(bot: commands.Bot):
    bot.add_cog(Stats(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.stats')
    return True
