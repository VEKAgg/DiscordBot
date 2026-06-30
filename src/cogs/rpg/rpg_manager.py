"""
RPG Manager Cog — XP tracking, activity roles, level progression, and leaderboard.

Tracks user activity (messages, commands, voice time), awards XP with role-based
multipliers, manages dynamic activity roles, and maintains a leaderboard.
"""

import logging
import math
import time
from datetime import UTC, datetime, timedelta, timezone

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    ACTIVITY_ROLE_INACTIVITY_DAYS,
    ACTIVITY_ROLES,
    INACTIVITY_CHECK_HOUR,
    INACTIVITY_CHECK_MINUTE,
    INACTIVITY_MONTH_DAYS,
    INACTIVITY_WEEK_DAYS,
    IST_UTC_OFFSET,
    LEADERBOARD_CHANNEL_ID,
    LEADERBOARD_TOP_N,
    LEADERBOARD_UPDATE_INTERVAL,
    LIVE_ROLE_ID,
    LOGS_CHANNEL_ID,
    MESSAGE_XP_COOLDOWN,
    RPG_POINTS,
    XP_MULTIPLIERS,
)
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.services import inactivity_service
from src.utils.embeds import alert_embed, error_embed, info_embed, success_embed
from src.utils.safety import admin_only, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.rpg')

# ============================================================
# Helpers
# ============================================================

# Map role name strings to their Discord role names
_ACTIVITY_ROLE_NAMES = {
    'active_member': 'Active Member',
    'active_plus': 'Active+',
    'active_star': 'Active Star',
}

# Sorted ascending by threshold so we can find the highest matching role
_ACTIVITY_ROLE_THRESHOLDS = sorted(ACTIVITY_ROLES.items(), key=lambda kv: kv[1])


def calculate_level(points: int) -> int:
    """Calculate level from total points using sqrt-based formula."""
    if points <= 0:
        return 0
    return int(math.sqrt(points / 100))


def points_to_next_level(points: int) -> int:
    """Calculate points needed to reach the next level."""
    current_level = calculate_level(points)
    next_level_points = (current_level + 1) ** 2 * 100
    return max(0, next_level_points - points)


def _progress_bar(points: int, width: int = 10) -> str:
    """Build a simple text progress bar to the next level."""
    current_level = calculate_level(points)
    level_start = current_level**2 * 100
    next_level = (current_level + 1) ** 2 * 100
    if next_level == level_start:
        return '[' + '=' * width + ']'
    progress = (points - level_start) / (next_level - level_start)
    filled = int(progress * width)
    return '[' + '=' * filled + '-' * (width - filled) + ']'


# ============================================================
# Cog
# ============================================================


class RPGManager(commands.Cog):
    """XP tracking, activity roles, and leaderboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._message_cooldowns: dict[int, float] = {}  # user_id -> last_message_time
        self._voice_join_times: dict[int, float] = {}  # user_id -> join_timestamp
        self._leaderboard_message: nextcord.Message | None = None
        # Activity duration tracking (streaming / gaming / listening)
        self._activity_start_times: dict[str, dict[int, float]] = {
            'streaming': {},
            'gaming': {},
            'listening': {},
        }

    async def cog_load(self):
        """Start background tasks."""
        self.update_leaderboard.start()
        self.evaluate_activity_roles.start()
        self.check_inactivity.start()
        # Restore leaderboard message reference if channel is configured
        if LEADERBOARD_CHANNEL_ID:
            await self._restore_leaderboard_message()

    async def cog_unload(self):
        """Stop background tasks."""
        self.update_leaderboard.stop()
        self.evaluate_activity_roles.stop()
        self.check_inactivity.stop()

    # ============================================================
    # DB helpers
    # ============================================================

    async def _ensure_user(self, discord_id: int) -> None:
        """Ensure a user row exists."""
        await db.execute(
            """
            INSERT INTO users (discord_id) VALUES ($1)
            ON CONFLICT (discord_id) DO NOTHING
            """,
            str(discord_id),
        )

    async def _award_points(
        self, user_id: int, activity_type: str, base_points: int, guild_id: int = 0, channel_id: int = 0
    ) -> int:
        """Award points to a user with role-based multipliers. Returns actual points awarded."""
        try:
            await self._ensure_user(user_id)

            # Fetch user to check role for multiplier
            user_row = await db.fetch_one('SELECT points FROM users WHERE discord_id = $1', str(user_id))
            if not user_row:
                return 0

            member = self.bot.get_user(user_id)
            multiplier = 1.0
            if member:
                # Check for DONATOR or ACTIVE_PRO role (by Discord role name)
                for role in getattr(member, 'roles', []):
                    role_lower = role.name.lower().replace(' ', '_')
                    if role_lower in XP_MULTIPLIERS:
                        multiplier = max(multiplier, XP_MULTIPLIERS[role_lower])

            actual_points = max(1, int(base_points * multiplier))

            await db.execute(
                """
                UPDATE users
                SET points = points + $1,
                    experience = experience + $1,
                    last_active = NOW(),
                    inactive_week_notified = FALSE,
                    inactive_month_notified = FALSE
                WHERE discord_id = $2
                """,
                actual_points,
                str(user_id),
            )

            # Update level
            new_points = (user_row['points'] or 0) + actual_points
            new_level = calculate_level(new_points)
            await db.execute(
                'UPDATE users SET level = $1 WHERE discord_id = $2',
                new_level,
                str(user_id),
            )

            # Update activity totals
            if activity_type == 'message':
                await db.execute(
                    'UPDATE users SET total_messages = total_messages + 1 WHERE discord_id = $1',
                    str(user_id),
                )
            elif activity_type == 'voice':
                await db.execute(
                    'UPDATE users SET total_voice_minutes = total_voice_minutes + 1 WHERE discord_id = $1',
                    str(user_id),
                )
            elif activity_type == 'command':
                await db.execute(
                    'UPDATE users SET total_commands = total_commands + 1 WHERE discord_id = $1',
                    str(user_id),
                )

            # Log activity
            await db.execute(
                """
                INSERT INTO user_activity_log (user_id, activity_type, points_awarded, channel_id, guild_id)
                VALUES ($1, $2, $3, $4, $5)
                """,
                str(user_id),
                activity_type,
                actual_points,
                channel_id,
                guild_id,
            )

            return actual_points
        except Exception as exc:
            logger.warning('Failed to award %s points to user %s: %s', activity_type, user_id, exc)
            return 0

    async def _get_user_rank(self, user_id: int) -> int | None:
        """Get a user's rank (1-indexed) from the leaderboard."""
        try:
            rank = await db.fetchval(
                """
                SELECT COUNT(*) + 1 FROM users
                WHERE points > (SELECT COALESCE(points, 0) FROM users WHERE discord_id = $1)
                """,
                str(user_id),
            )
            return rank
        except Exception:
            return None

    async def _get_leaderboard_data(self) -> list[dict]:
        """Fetch top N users for the leaderboard."""
        try:
            rows = await db.fetch(
                """
                SELECT discord_id, username, points, experience, level
                FROM users
                WHERE points > 0
                ORDER BY points DESC
                LIMIT $1
                """,
                LEADERBOARD_TOP_N,
            )
            return [dict(row) for row in rows]
        except Exception:
            return []

    async def _restore_leaderboard_message(self):
        """Restore the leaderboard message reference from the channel."""
        if not LEADERBOARD_CHANNEL_ID:
            return
        try:
            channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
            if channel is None:
                channel = await self.bot.fetch_channel(LEADERBOARD_CHANNEL_ID)
            # Look for the most recent bot message in the channel
            async for message in channel.history(limit=10):  # type: ignore[union-attr]
                if message.author == self.bot.user:
                    self._leaderboard_message = message
                    return
        except Exception as exc:
            logger.debug('Could not restore leaderboard message: %s', exc)

    # ============================================================
    # Build leaderboard embed
    # ============================================================

    async def _build_leaderboard_embed(self) -> nextcord.Embed | None:
        """Build the full leaderboard embed with all stat categories."""
        xp_data = await self._get_leaderboard_data()
        if not xp_data:
            return None

        embed = nextcord.Embed(
            title='Community Leaderboard',
            color=nextcord.Color.gold(),
        )
        embed.set_author(name='VEKA Bot', url='https://veka.gg')
        embed.timestamp = datetime.now(UTC)

        # XP leaderboard
        medals = ['1st', '2nd', '3rd']
        lines = []
        for i, row in enumerate(xp_data):
            medal = medals[i] if i < 3 else f'#{i + 1}'
            uid = int(row['discord_id'])
            member = self.bot.get_user(uid)
            name = member.display_name if member else row.get('username') or f'User {uid}'
            level = row.get('level') or calculate_level(row.get('points', 0))
            lines.append(f'**{medal}** — {name} | Level {level} | {row["points"]:,} XP')
        embed.add_field(name='⭐ XP (All Time)', value='\n'.join(lines), inline=False)

        # Stat leaderboards
        stat_configs = [
            ('total_messages', '💬 Messages', None),
            ('total_voice_minutes', '🔊 Voice Minutes', None),
            ('total_streaming_minutes', '📺 Streaming Minutes', None),
            ('total_gaming_minutes', '🎮 Gaming Minutes', None),
            ('total_listening_minutes', '🎵 Listening Minutes', None),
        ]

        for column, title, _period in stat_configs:
            rows = await self._get_stat_leaderboard(column)
            if not rows:
                continue
            stat_lines = []
            for i, row in enumerate(rows):
                medal = medals[i] if i < 3 else f'#{i + 1}'
                uid = int(row['discord_id'])
                member = self.bot.get_user(uid)
                name = member.display_name if member else f'User {uid}'
                val = row.get(column) or 0
                stat_lines.append(f'**{medal}** — {name}: {val:,}')
            embed.add_field(name=title, value='\n'.join(stat_lines), inline=False)

        return embed

    async def _get_stat_leaderboard(self, column: str, period: str | None = None, limit: int = 10) -> list[dict]:
        """Fetch top N users for a given stat column, optionally filtered by period."""
        try:
            if period == 'month':
                rows = await db.fetch(
                    """
                    SELECT u.discord_id, SUM(a.points_awarded) AS stat_val
                    FROM users u
                    JOIN user_activity_log a ON a.user_id = u.discord_id
                    WHERE a.activity_type = $1
                      AND a.created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY u.discord_id
                    ORDER BY stat_val DESC
                    LIMIT $2
                    """,
                    column.replace('total_', '').replace('_minutes', ''),
                    limit,
                )
            elif period == 'week':
                rows = await db.fetch(
                    """
                    SELECT u.discord_id, SUM(a.points_awarded) AS stat_val
                    FROM users u
                    JOIN user_activity_log a ON a.user_id = u.discord_id
                    WHERE a.activity_type = $1
                      AND a.created_at >= NOW() - INTERVAL '7 days'
                    GROUP BY u.discord_id
                    ORDER BY stat_val DESC
                    LIMIT $2
                    """,
                    column.replace('total_', '').replace('_minutes', ''),
                    limit,
                )
            else:
                rows = await db.fetch(
                    f"""
                    SELECT discord_id, {column}
                    FROM users
                    WHERE {column} > 0
                    ORDER BY {column} DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [dict(row) for row in rows]
        except Exception:
            return []

    # ============================================================
    # Event listeners for XP
    # ============================================================

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Award XP for messages (with cooldown)."""
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        now = time.monotonic()

        # Cooldown check
        last_time = self._message_cooldowns.get(user_id, 0.0)
        if (now - last_time) < MESSAGE_XP_COOLDOWN:
            return

        self._message_cooldowns[user_id] = now
        await self._award_points(
            user_id,
            'message',
            RPG_POINTS['message'],
            guild_id=message.guild.id,
            channel_id=message.channel.id,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: nextcord.Member,
        before: nextcord.VoiceState | None,
        after: nextcord.VoiceState | None,
    ):
        """Track voice channel time for XP."""
        if member.bot:
            return

        user_id = member.id

        # User joined a voice channel
        if before is None and after is not None:
            self._voice_join_times[user_id] = time.monotonic()

        # User left a voice channel
        elif before is not None and after is None:
            join_time = self._voice_join_times.pop(user_id, None)
            if join_time:
                minutes = int((time.monotonic() - join_time) / 60)
                if minutes >= 1:
                    # Award XP for each minute spent
                    for _ in range(min(minutes, 60)):  # Cap at 60 minutes per session
                        await self._award_points(
                            user_id,
                            'voice',
                            RPG_POINTS['voice_per_minute'],
                            guild_id=member.guild.id,
                            channel_id=before.channel.id if before.channel else 0,
                        )

        # User moved channels — track as if they left and rejoined
        elif before is not None and after is not None and before.channel != after.channel:
            join_time = self._voice_join_times.pop(user_id, None)
            if join_time:
                minutes = int((time.monotonic() - join_time) / 60)
                if minutes >= 1:
                    for _ in range(min(minutes, 60)):
                        await self._award_points(
                            user_id,
                            'voice',
                            RPG_POINTS['voice_per_minute'],
                            guild_id=member.guild.id,
                            channel_id=before.channel.id if before.channel else 0,
                        )
            self._voice_join_times[user_id] = time.monotonic()

    @commands.Cog.listener()
    async def on_application_command(self, interaction: nextcord.Interaction):
        """Award XP for slash command usage."""
        if not interaction.guild or interaction.user.bot:
            return

        await self._award_points(
            interaction.user.id,
            'command',
            RPG_POINTS['command'],
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id if interaction.channel else 0,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: nextcord.Member, after: nextcord.Member):
        """Track activity durations (streaming/gaming/listening) and live role."""
        if after.bot:
            return

        was_streaming = self._is_streaming(before)
        is_streaming = self._is_streaming(after)
        is_gaming = self._has_activity_type(after, nextcord.ActivityType.playing)
        is_listening = self._has_activity_type(after, nextcord.ActivityType.listening)

        # --- Live role (streaming start/stop) ---
        if LIVE_ROLE_ID and was_streaming != is_streaming:
            live_role = after.guild.get_role(LIVE_ROLE_ID)
            if live_role:
                try:
                    if is_streaming and live_role not in after.roles:
                        await after.add_roles(live_role, reason='Started streaming')
                        logger.info('Added live role to %s', after)
                        stream_url = self._get_stream_url(after)
                        if stream_url:
                            from src.services.networking_service import NetworkingService

                            svc = NetworkingService()
                            await svc.append_profile_link(str(after.id), stream_url)
                    elif not was_streaming and live_role in after.roles:
                        await after.remove_roles(live_role, reason='Stopped streaming')
                        logger.info('Removed live role from %s', after)
                except Exception as exc:
                    logger.warning('Failed to update live role for %s: %s', after, exc)

        # --- Activity duration tracking ---
        await self._track_activity_duration(after, 'streaming', is_streaming)
        await self._track_activity_duration(after, 'gaming', is_gaming)
        await self._track_activity_duration(after, 'listening', is_listening)

    @staticmethod
    def _is_streaming(member: nextcord.Member) -> bool:
        for activity in member.activities:
            if activity.type == nextcord.ActivityType.streaming:
                return True
        return False

    @staticmethod
    def _get_stream_url(member: nextcord.Member) -> str | None:
        for activity in member.activities:
            if activity.type == nextcord.ActivityType.streaming:
                return activity.url
        return None

    @staticmethod
    def _has_activity_type(member: nextcord.Member, activity_type: nextcord.ActivityType) -> bool:
        return any(a.type == activity_type for a in member.activities)

    async def _track_activity_duration(self, member: nextcord.Member, category: str, is_active: bool) -> None:
        """Record start/stop of an activity and persist elapsed minutes."""
        uid = member.id
        bucket = self._activity_start_times[category]

        if is_active and uid not in bucket:
            bucket[uid] = time.monotonic()
        elif not is_active and uid in bucket:
            start = bucket.pop(uid)
            minutes = int((time.monotonic() - start) / 60)
            if minutes < 1:
                return
            column = f'total_{category}_minutes'
            try:
                await db.execute(
                    f'UPDATE users SET {column} = {column} + $1 WHERE discord_id = $2',
                    minutes,
                    str(uid),
                )
            except Exception as exc:
                logger.debug('Failed to update %s for %s: %s', column, member, exc)

    # ============================================================
    # Background tasks
    # ============================================================

    @tasks.loop(seconds=LEADERBOARD_UPDATE_INTERVAL)
    async def update_leaderboard(self):
        """Periodically update the leaderboard embed."""
        if not LEADERBOARD_CHANNEL_ID or not runtime_state.db_available:
            return

        try:
            channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
            if channel is None:
                channel = await self.bot.fetch_channel(LEADERBOARD_CHANNEL_ID)

            embed = await self._build_leaderboard_embed()
            if not embed:
                return

            if self._leaderboard_message:
                try:
                    await self._leaderboard_message.edit(embed=embed)
                    return
                except Exception:
                    pass  # Message deleted or inaccessible, send a new one

            # Send new leaderboard message
            self._leaderboard_message = await channel.send(embed=embed)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning('Failed to update leaderboard: %s', exc)

    @update_leaderboard.before_loop
    async def before_update_leaderboard(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def evaluate_activity_roles(self):
        """Evaluate and assign/remove activity roles based on activity."""
        if not runtime_state.db_available:
            return

        try:
            # Get all members with points > 0
            rows = await db.fetch(
                """
                SELECT discord_id, points, last_active FROM users
                WHERE points > 0
                """
            )

            now = datetime.now(UTC)
            inactivity_cutoff = now - timedelta(days=ACTIVITY_ROLE_INACTIVITY_DAYS)

            for row in rows:
                user_id = int(row['discord_id'])
                points = row.get('points', 0) or 0
                last_active = row.get('last_active')

                member = self.bot.get_guild(self.bot.guilds[0].id).get_member(user_id) if self.bot.guilds else None
                if not member:
                    continue

                # Determine the highest activity role the user qualifies for
                target_role_name = None
                for role_key, threshold in reversed(_ACTIVITY_ROLE_THRESHOLDS):
                    if points >= threshold:
                        target_role_name = _ACTIVITY_ROLE_NAMES[role_key]
                        break

                # Check inactivity — if last_active is older than cutoff, remove all activity roles
                is_inactive = False
                if last_active:
                    if last_active.tzinfo is None:
                        last_active = last_active.replace(tzinfo=UTC)
                    if last_active < inactivity_cutoff:
                        is_inactive = True
                elif points > 0:
                    # If no last_active but has points, check created_at as fallback
                    is_inactive = True

                if is_inactive:
                    target_role_name = None

                # Find the activity roles on the guild
                guild = member.guild
                current_activity_roles = []
                for role_name in _ACTIVITY_ROLE_NAMES.values():
                    discord_role = nextcord.utils.get(guild.roles, name=role_name)
                    if discord_role and discord_role in member.roles:
                        current_activity_roles.append(discord_role)

                # Determine which role to keep/add
                target_discord_role = None
                if target_role_name:
                    target_discord_role = nextcord.utils.get(guild.roles, name=target_role_name)

                # Remove roles that shouldn't be there
                for role in current_activity_roles:
                    if role != target_discord_role:
                        try:
                            await member.remove_roles(role, reason='Activity role update')
                        except Exception as exc:
                            logger.debug('Failed to remove role %s from %s: %s', role.name, member, exc)

                # Add the target role if not already present
                if target_discord_role and target_discord_role not in current_activity_roles:
                    try:
                        await member.add_roles(target_discord_role, reason='Activity role update')
                    except Exception as exc:
                        logger.debug('Failed to add role %s to %s: %s', target_discord_role.name, member, exc)

                # Update tracking table
                await db.execute(
                    """
                    INSERT INTO user_rpg_roles (user_id, active_role, last_evaluated)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET active_role = $2, last_evaluated = NOW()
                    """,
                    str(user_id),
                    target_role_name or '',
                )

            logger.info('Activity role evaluation complete')
        except Exception as exc:
            logger.error('Activity role evaluation failed: %s', exc, exc_info=True)

    @evaluate_activity_roles.before_loop
    async def before_evaluate_activity_roles(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------
    # Inactivity monitoring — daily at 9:00 AM IST
    # ------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def check_inactivity(self):
        """Run inactivity check once per day at the configured IST hour."""
        now = datetime.now(timezone(timedelta(hours=IST_UTC_OFFSET)))
        if now.hour != INACTIVITY_CHECK_HOUR or now.minute != INACTIVITY_CHECK_MINUTE:
            return
        if not runtime_state.db_available or not LOGS_CHANNEL_ID:
            return

        try:
            inactive_users = await inactivity_service.get_inactive_users(
                INACTIVITY_WEEK_DAYS,
                INACTIVITY_MONTH_DAYS,
            )
            if not inactive_users:
                return

            logs_channel = self.bot.get_channel(LOGS_CHANNEL_ID)
            if logs_channel is None:
                logs_channel = await self.bot.fetch_channel(LOGS_CHANNEL_ID)

            guild = self.bot.guilds[0] if self.bot.guilds else None

            for entry in inactive_users:
                user_id = int(entry['discord_id'])
                member = guild.get_member(user_id) if guild else self.bot.get_user(user_id)
                if member is None:
                    continue

                days = entry['days_inactive']
                last_seen = entry['last_active']

                # 1-week threshold — log to logs channel
                if entry['notify_week']:
                    embed = alert_embed(
                        '⏰ Inactivity Alert — 1 Week',
                        f'{member.mention} has been inactive for **{days} days**.\n'
                        f'Last active: {last_seen.strftime("%Y-%m-%d %H:%M UTC")}',
                    )
                    await safe_send(logs_channel, embed=embed)
                    await inactivity_service.mark_week_notified(entry['discord_id'])

                # 1-month threshold — DM the user + log to logs channel
                if entry['notify_month']:
                    try:
                        dm_embed = info_embed(
                            '👋 We miss you!',
                            (
                                f"Hey there! We noticed you haven't been around **VEKA** in a while — "
                                f'about **{days} days** to be exact.\n\n'
                                "Everything okay? We'd love to see you back in the community. "
                                "If there's anything going on or you need help with anything, "
                                'feel free to reach out to our mods!'
                            ),
                        )
                        await member.send(embed=dm_embed)
                    except nextcord.Forbidden:
                        logger.debug('Cannot DM %s — DMs disabled', member)
                    except Exception as exc:
                        logger.warning('Failed to DM inactive user %s: %s', member, exc)

                    embed = alert_embed(
                        '⚠️ Inactivity Alert — 1 Month',
                        (
                            f'{member.mention} has been inactive for **{days} days**.\n'
                            f'Last active: {last_seen.strftime("%Y-%m-%d %H:%M UTC")}\n'
                            'A friendly DM has been sent to the user.'
                        ),
                    )
                    await safe_send(logs_channel, embed=embed)
                    await inactivity_service.mark_month_notified(entry['discord_id'])

            logger.info('Inactivity check complete — %d users processed', len(inactive_users))
        except Exception as exc:
            logger.error('Inactivity check failed: %s', exc, exc_info=True)

    @check_inactivity.before_loop
    async def before_check_inactivity(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # Commands
    # ============================================================

    @nextcord.slash_command(name='level', description='Check your level and XP progress')
    @safe_slash_command()
    async def level_command(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = nextcord.SlashOption(
            description='User to check (defaults to you)', required=False
        ),
    ):
        """Show level, XP, and rank for yourself or another user."""
        target = user or interaction.user
        await self._ensure_user(target.id)

        try:
            row = await db.fetch_one(
                'SELECT points, level FROM users WHERE discord_id = $1',
                str(target.id),
            )
        except Exception:
            embed = await error_embed(
                title='Error',
                description='Could not fetch user data.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        points = row['points'] if row else 0
        level = row['level'] if row else calculate_level(points or 0)
        next_level_pts = points_to_next_level(points or 0)
        rank = await self._get_user_rank(target.id)
        progress = _progress_bar(points or 0)

        rank_text = f'#{rank}' if rank else 'Unranked'

        description = (
            f'**{target.display_name}**\n\n'
            f'**Level**: {level}\n'
            f'**XP**: {points or 0:,}\n'
            f'**Progress**: {progress} ({next_level_pts:,} XP to next level)\n'
            f'**Rank**: {rank_text}'
        )

        embed = await success_embed(
            title='Level Status',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        await safe_send(interaction, embed=embed)

    @nextcord.slash_command(name='leaderboard', description='View the community leaderboard')
    @safe_slash_command()
    async def leaderboard_command(
        self,
        interaction: nextcord.Interaction,
        stat: str = nextcord.SlashOption(
            description='Stat to rank by',
            required=False,
            choices=['xp', 'messages', 'voice', 'streaming', 'gaming', 'listening'],
        ),
        period: str = nextcord.SlashOption(
            description='Time period',
            required=False,
            choices=['alltime', 'month', 'week'],
        ),
    ):
        """Show top 10 leaderboard for a given stat and period."""
        await interaction.response.defer()

        stat = stat or 'xp'
        period = period or 'alltime'

        # XP leaderboard (existing behaviour)
        if stat == 'xp':
            data = await self._get_leaderboard_data()
            if not data:
                embed = await info_embed(
                    title='Leaderboard',
                    description='No activity recorded yet. Start chatting to earn XP!',
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
                uid = int(row['discord_id'])
                member = self.bot.get_user(uid)
                name = member.display_name if member else row.get('username') or f'User {uid}'
                level = row.get('level') or calculate_level(row.get('points', 0))
                lines.append(f'**{medal}** {name} — Level {level} | {row["points"]:,} XP')

            user_rank = await self._get_user_rank(interaction.user.id)
            user_row = await db.fetch_one(
                'SELECT points, level FROM users WHERE discord_id = $1',
                str(interaction.user.id),
            )
            if user_row:
                user_level = user_row['level'] or calculate_level(user_row['points'] or 0)
                rank_text = f'#{user_rank}' if user_rank else 'Unranked'
                lines.append(f'\n**Your Rank**: {rank_text} — Level {user_level} | {user_row["points"] or 0:,} XP')

            description = '\n'.join(lines)

            embed = await success_embed(
                title='Community Leaderboard — XP',
                description=description,
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            if data:
                top_uid = int(data[0]['discord_id'])
                top_member = self.bot.get_user(top_uid)
                if top_member:
                    embed.set_thumbnail(
                        url=top_member.avatar.url if top_member.avatar else top_member.default_avatar.url
                    )
            embed.timestamp = datetime.now(UTC)
            await interaction.followup.send(embed=embed)
            return

        # Stat-based leaderboard
        stat_map = {
            'messages': 'total_messages',
            'voice': 'total_voice_minutes',
            'streaming': 'total_streaming_minutes',
            'gaming': 'total_gaming_minutes',
            'listening': 'total_listening_minutes',
        }
        column = stat_map[stat]
        period_label = {'alltime': 'All Time', 'month': 'Past Month', 'week': 'Past Week'}
        rows = await self._get_stat_leaderboard(column, period if period != 'alltime' else None)

        if not rows:
            embed = await info_embed(
                title=f'Leaderboard — {stat.title()}',
                description='No data recorded yet for this category.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await interaction.followup.send(embed=embed)
            return

        medals = ['\U0001f947', '\U0001f948', '\U0001f949']
        lines = []
        for i, row in enumerate(rows):
            medal = medals[i] if i < 3 else f'#{i + 1}'
            uid = int(row['discord_id'])
            member = self.bot.get_user(uid)
            name = member.display_name if member else f'User {uid}'
            val = row.get(column) or row.get('stat_val') or 0
            lines.append(f'**{medal}** {name}: {val:,}')

        description = '\n'.join(lines)

        embed = await success_embed(
            title=f'Community Leaderboard — {stat.title()} ({period_label[period]})',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        if rows:
            top_uid = int(rows[0]['discord_id'])
            top_member = self.bot.get_user(top_uid)
            if top_member:
                embed.set_thumbnail(url=top_member.avatar.url if top_member.avatar else top_member.default_avatar.url)
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)

    @nextcord.slash_command(name='setupleaderboard', description='Set the leaderboard channel (admin only)')
    @safe_slash_command()
    @admin_only()
    async def setupleaderboard_command(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel for the leaderboard'),
    ):
        """Designate a channel for the auto-updating leaderboard."""
        global LEADERBOARD_CHANNEL_ID  # noqa: PLW0603

        LEADERBOARD_CHANNEL_ID = channel.id

        # Send initial leaderboard embed
        embed = await self._build_leaderboard_embed()
        if embed:
            msg = await channel.send(embed=embed)
            self._leaderboard_message = msg

        embed = await success_embed(
            title='Leaderboard Configured',
            description=f'Leaderboard will auto-update in {channel.mention} every {LEADERBOARD_UPDATE_INTERVAL // 60} minutes.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='activity', description='View your activity stats')
    @safe_slash_command()
    async def activity_command(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = nextcord.SlashOption(
            description='User to check (defaults to you)', required=False
        ),
    ):
        """Show detailed activity statistics."""
        target = user or interaction.user
        await self._ensure_user(target.id)

        try:
            row = await db.fetch_one(
                """
                SELECT points, level, total_messages, total_voice_minutes, total_commands, last_active
                FROM users WHERE discord_id = $1
                """,
                str(target.id),
            )
        except Exception:
            embed = await error_embed(
                title='Error',
                description='Could not fetch activity data.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if not row:
            embed = await info_embed(
                title='No Activity',
                description='No activity recorded for this user yet.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        points = row['points'] or 0
        level = row['level'] or calculate_level(points)
        messages = row['total_messages'] or 0
        voice_min = row['total_voice_minutes'] or 0
        commands_count = row['total_commands'] or 0
        last_active = row.get('last_active')

        last_active_text = 'Never'
        if last_active:
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=UTC)
            delta = datetime.now(UTC) - last_active
            if delta < timedelta(minutes=1):
                last_active_text = 'Just now'
            elif delta < timedelta(hours=1):
                last_active_text = f'{int(delta.total_seconds() // 60)}m ago'
            elif delta < timedelta(days=1):
                last_active_text = f'{int(delta.total_seconds() // 3600)}h ago'
            else:
                last_active_text = f'{delta.days}d ago'

        activity_role = 'None'
        for role_key, threshold in reversed(_ACTIVITY_ROLE_THRESHOLDS):
            if points >= threshold:
                activity_role = _ACTIVITY_ROLE_NAMES[role_key]
                break

        next_level_pts = points_to_next_level(points)
        progress = _progress_bar(points)

        embed = await success_embed(
            title='Activity Stats',
            description=f'**{target.display_name}**',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        embed.add_field(name='Level', value=str(level), inline=True)
        embed.add_field(name='XP', value=f'{points:,}', inline=True)
        embed.add_field(name='Next Level', value=f'{next_level_pts:,} XP', inline=True)
        embed.add_field(name='Progress', value=f'{progress}', inline=False)
        embed.add_field(name='Messages', value=f'{messages:,}', inline=True)
        embed.add_field(name='Voice Time', value=f'{voice_min:,} min', inline=True)
        embed.add_field(name='Commands Used', value=f'{commands_count:,}', inline=True)
        embed.add_field(name='Activity Role', value=activity_role, inline=True)
        embed.add_field(name='Last Active', value=last_active_text, inline=True)

        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(RPGManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.rpg')
    return True
