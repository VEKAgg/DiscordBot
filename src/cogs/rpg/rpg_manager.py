"""
RPG Manager Cog — XP tracking, activity roles, level progression, and leaderboard.

Tracks user activity (messages, commands, voice time), awards XP with role-based
multipliers, manages dynamic activity roles, and maintains a leaderboard.
"""

import logging
import math
import time
from datetime import UTC, date, datetime, timedelta, timezone
from datetime import time as dt_time

import aiohttp
import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    ACTIVITY_ROLE_INACTIVITY_DAYS,
    ACTIVITY_ROLES,
    CODING_APPS,
    INACTIVITY_CHECK_HOUR,
    INACTIVITY_CHECK_MINUTE,
    INACTIVITY_MAX_DMS_PER_RUN,
    INACTIVITY_MONTH_DAYS,
    INACTIVITY_WEEK_DAYS,
    IST_UTC_OFFSET,
    LEADERBOARD_TOP_N,
    LEADERBOARD_UPDATE_INTERVAL,
    LIVE_ROLE_ID,
    MAIN_GUILD_ID,
    MESSAGE_XP_COOLDOWN,
    RPG_POINTS,
    XP_MULTIPLIERS,
)
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.services import activity_service
from src.services.activity_service import Award
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import alert_embed, info_embed, success_embed
from src.utils.http import get_session
from src.utils.outbound import SendStatus, outbound
from src.utils.roles import punitive_role_problem
from src.utils.safety import manage_guild_only, safe_send, safe_slash_command
from src.utils.ttlcache import TTLDict

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

# Leaderboard category column mapping
_LEADERBOARD_CATEGORIES = activity_service.LEADERBOARD_CATEGORIES
_DAILY_COLUMNS = activity_service.DAILY_COLUMNS
_PRESENCE_COLUMNS = activity_service.PRESENCE_COLUMNS
_SEASON_CATEGORIES = {
    'xp': 'xp_earned',
    'chat': 'messages',
    'voice': 'voice_minutes',
    'gaming': 'gaming_minutes',
    'streaming': 'streaming_minutes',
    'coding': 'coding_minutes',
}
_PERIOD_LABELS = {'week': 'past 7 days', 'month': 'past 30 days', 'season': 'this season'}

XP_SESSION_CAP_MINUTES = 60  # XP stops after this many continuous minutes of one kind (totals don't)
PRESENCE_XP_PER_MINUTE = 1


_period_start = activity_service.period_start


def _notified_since(notices: dict, user_id: int, level: str, last_active: date) -> bool:
    """Already reported at this level since the member was last active in the server.

    A notice is only ever sent days after the last activity, so activity on the notice day itself means
    the member came back after it: that notice no longer counts (strict comparison)."""
    when = notices.get((user_id, level))
    return when is not None and when > last_active


PREV_LABEL = '\u25c0 Previous'
NEXT_LABEL = '\u25b6 Next'


class PaginationView(nextcord.ui.View):
    """Interactive leaderboard pagination with Previous/Next buttons."""

    def __init__(self, pages: list[str], title: str, author_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.title = title
        self.author_id = author_id
        self.current_page = 0
        self.message: nextcord.Message | None = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, nextcord.ui.Button):
                if child.label == PREV_LABEL:
                    child.disabled = self.current_page == 0
                elif child.label == NEXT_LABEL:
                    child.disabled = self.current_page >= len(self.pages) - 1

    @nextcord.ui.button(label=PREV_LABEL, style=nextcord.ButtonStyle.secondary)
    async def prev_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('This is not your leaderboard.', ephemeral=True)
            return
        self.current_page = max(0, self.current_page - 1)
        self._update_buttons()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @nextcord.ui.button(label=NEXT_LABEL, style=nextcord.ButtonStyle.secondary)
    async def next_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('This is not your leaderboard.', ephemeral=True)
            return
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        self._update_buttons()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_embed(self) -> nextcord.Embed:
        embed = nextcord.Embed(
            title=self.title,
            description=self.pages[self.current_page],
            color=nextcord.Color.gold(),
        )
        embed.set_author(name='VEKA Bot', url='https://veka.gg')
        embed.set_footer(text=f'Page {self.current_page + 1}/{len(self.pages)}')
        embed.timestamp = datetime.now(UTC)
        return embed

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, nextcord.ui.Button | nextcord.ui.Select):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


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


def _progress_bar(points: int, width: int = 12) -> str:
    """Build a visual progress bar with percentage to the next level."""
    current_level = calculate_level(points)
    level_start = current_level**2 * 100
    next_level = (current_level + 1) ** 2 * 100
    if next_level == level_start:
        filled = width
        pct = 100.0
    else:
        progress = (points - level_start) / (next_level - level_start)
        filled = int(progress * width)
        pct = progress * 100
    bar = '\u2588' * filled + '\u2591' * (width - filled)
    return f'{bar} {pct:.1f}%'


def _sparkline(values: list[int], width: int = 7) -> str:
    """Render a Unicode mini bar graph from a list of daily values."""
    blocks = [' ', '\u2582', '\u2583', '\u2584', '\u2585', '\u2586', '\u2587', '\u2588']
    if not values or max(values) == 0:
        return '[' + ' ' * width + ']'
    max_val = max(values)
    # Pad or truncate to width
    padded = values[:width] + [0] * max(0, width - len(values))
    bars = ''
    for v in padded:
        idx = int((v / max_val) * (len(blocks) - 1)) if max_val > 0 else 0
        bars += blocks[idx]
    return f'[{bars}]'


def _streak_multiplier(streak: int) -> float:
    """Return XP multiplier based on current streak length."""
    if streak >= 30:
        return 2.0
    if streak >= 7:
        return 1.5
    if streak >= 3:
        return 1.25
    return 1.0


# ============================================================
# Cog
# ============================================================


class RPGManager(commands.Cog):
    """XP tracking, activity roles, and leaderboard.

    Tracking model (see AGENTS.md "Activity tracking"):
    - Messages and commands are awarded as they happen (message XP has a per-user cooldown).
    - Voice and presence minutes are *sampled*: ``activity_tick`` runs every minute and credits each
      eligible member from the live gateway state. Nothing lives only in memory, so a restart or deploy
      loses at most a minute and members already in voice/playing at startup are counted.
    - Totals record real minutes; only XP is capped (60 consecutive minutes per kind).
    - Presence-derived tracking (games, coding apps, streaming) only in servers that enabled it
      (``guild_settings.presence_tracking_enabled``), skipping members who ran ``/privacy optout``.
      Listening/Spotify is never tracked.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._message_cooldowns: TTLDict[int, bool] = TTLDict(ttl=MESSAGE_XP_COOLDOWN, maxsize=50_000)
        self._leaderboard_messages: dict[int, nextcord.Message | nextcord.PartialMessage] = {}  # guild → message
        # Members who ever changed their tracking choice: discord ID -> (allowed, changed_at). Everyone
        # else is allowed with consent generation None. changed_at is the generation a batch carries.
        self._consent: dict[int, tuple[bool, datetime | None]] = {}
        self._opt_in_loaded = False
        # (user_id, kind) -> consecutive minutes credited; rebuilt each tick, so it only holds active users.
        self._consecutive: dict[tuple[int, str], int] = {}
        self._last_tick: float | None = None
        self._tick_carry = 0.0

    def _loops(self):
        return (
            self.update_leaderboard,
            self.evaluate_activity_roles,
            self.check_inactivity,
            self.activity_tick,
            self.monthly_season_archive,
        )

    async def cog_ready(self):
        """Start background tasks (called from on_ready via run_cog_ready_hooks; nextcord has no cog_load)."""
        await self.load_opt_ins()
        await self.ensure_previous_season_archived()
        for loop in self._loops():
            if not loop.is_running():
                loop.start()

    def cog_unload(self):
        """Stop background tasks (called synchronously by nextcord)."""
        for loop in self._loops():
            loop.cancel()

    # ============================================================
    # Presence consent (member opt-out)
    # ============================================================

    async def load_opt_ins(self) -> None:
        rows = await db.fetch(
            """SELECT discord_id, presence_opt_in, presence_opt_in_changed_at FROM users
               WHERE presence_opt_in_changed_at IS NOT NULL OR NOT presence_opt_in"""
        )
        self._consent = {
            int(r['discord_id']): (bool(r['presence_opt_in']), r['presence_opt_in_changed_at'])
            for r in rows
            if str(r['discord_id']).isdigit()
        }
        self._opt_in_loaded = True

    async def reload_opt_in(self, user_id: int) -> None:
        """Re-read one member's choice (the dashboard API or another process changed it)."""
        row = await db.fetch_one(
            'SELECT presence_opt_in, presence_opt_in_changed_at FROM users WHERE discord_id = $1', str(user_id)
        )
        if row is None:
            self._consent.pop(user_id, None)
        else:
            self.set_opt_in(user_id, bool(row['presence_opt_in']), row['presence_opt_in_changed_at'])

    def set_opt_in(self, user_id: int, enabled: bool, changed_at: datetime | None = None) -> None:
        """Record a member's choice (``enabled`` = tracking allowed) after the database was updated."""
        self._consent[user_id] = (enabled, changed_at)
        if not enabled:
            for key in [k for k in self._consecutive if k[0] == user_id and k[1] != 'voice']:
                self._consecutive.pop(key, None)

    def is_opted_in(self, user_id: int) -> bool:
        """Tracking allowed for this member (default yes; no after /privacy optout or delete)."""
        return self._consent.get(user_id, (True, None))[0]

    # ============================================================
    # Awards
    # ============================================================

    @staticmethod
    def _role_multiplier(member: nextcord.Member | None) -> float:
        multiplier = 1.0
        for role in getattr(member, 'roles', None) or []:
            key = role.name.lower().replace(' ', '_')
            if key in XP_MULTIPLIERS:
                multiplier = max(multiplier, XP_MULTIPLIERS[key])
        return multiplier

    async def _award_event(self, metric: str, member: nextcord.Member | nextcord.User, guild: nextcord.Guild, xp: int):
        """Award one message/command event."""
        from src.services.guild_modules_service import guild_modules_service

        if not await guild_modules_service.enabled(guild.id, 'activity'):
            return
        try:
            m = member if isinstance(member, nextcord.Member) else guild.get_member(member.id)
            await activity_service.award(
                metric,
                [
                    Award(
                        user_id=member.id,
                        guild_id=guild.id,
                        quantity=1,
                        xp_base=xp,
                        role_multiplier=self._role_multiplier(m),
                        touch_streak=True,
                    )
                ],
            )
        except Exception as exc:
            logger.warning('Failed to award %s to user %s: %s', metric, member.id, type(exc).__name__)

    async def _get_user_rank(self, user_id: int, guild_id: int | None = None) -> int | None:
        """XP rank (1-indexed): in ``guild_id`` from that server's activity, else across all servers."""
        try:
            if guild_id is None:
                return await db.fetchval(
                    """
                    SELECT COUNT(*) + 1 FROM users
                    WHERE points > (SELECT COALESCE(points, 0) FROM users WHERE discord_id = $1)
                    """,
                    str(user_id),
                )
            return await db.fetchval(
                """
                WITH totals AS (
                    SELECT user_id, SUM(xp_earned) AS xp FROM user_activity_daily
                    WHERE guild_id = $1 GROUP BY user_id
                )
                SELECT COUNT(*) + 1 FROM totals
                WHERE xp > COALESCE((SELECT xp FROM totals WHERE user_id = $2), 0)
                """,
                guild_id,
                user_id,
            )
        except Exception:
            return None

    async def _guild_xp(self, user_id: int, guild_id: int) -> int:
        value = await db.fetchval(
            'SELECT COALESCE(SUM(xp_earned), 0) FROM user_activity_daily WHERE guild_id = $1 AND user_id = $2',
            guild_id,
            user_id,
        )
        return int(value or 0)

    async def _get_stat_leaderboard(
        self, column: str, period: str | None = None, limit: int = 10, guild_id: int | None = None
    ) -> list[dict]:
        """Top users for a stat (see activity_service.leaderboard). Rows: discord_id, value."""
        try:
            return await activity_service.leaderboard(column, period, guild_id=guild_id, limit=limit)
        except Exception:
            logger.debug('Stat leaderboard query failed for %s/%s', column, period, exc_info=True)
            return []

    # ============================================================
    # Build leaderboard embed
    # ============================================================

    async def _build_leaderboard_embed(self, guild: nextcord.Guild | None = None) -> nextcord.Embed | None:
        """A server's auto-updating leaderboard: its all-time XP plus this month's activity there."""
        if guild is None:
            return None
        xp_data = await self._get_stat_leaderboard('points', None, limit=LEADERBOARD_TOP_N, guild_id=guild.id)
        if not xp_data:
            return None

        embed = nextcord.Embed(title=f'\U0001f3c6 {guild.name} Leaderboard', color=nextcord.Color.gold())
        embed.set_author(name='VEKA Bot', url='https://veka.gg')
        embed.timestamp = datetime.now(UTC)

        medals = ['\U0001f947', '\U0001f948', '\U0001f949']
        lines = []
        for i, row in enumerate(xp_data):
            uid = int(row['discord_id'])
            member = guild.get_member(uid)
            name = member.display_name if member else f'User {uid}'
            xp = int(row.get('value') or 0)
            lines.append(
                f'{medals[i]} **{name}** \u2014 **{xp:,}** XP' if i < 3 else f'`#{i + 1}` {name} \u2014 {xp:,} XP'
            )
        embed.add_field(name='\u2b50 XP (all time, this server)', value='\n'.join(lines), inline=False)

        stat_configs = [
            ('total_messages', '\U0001f4ac Messages'),
            ('total_voice_minutes', '\U0001f50a Voice minutes'),
            ('total_streaming_minutes', '\U0001f4fa Streaming minutes'),
            ('total_gaming_minutes', '\U0001f3ae Gaming minutes'),
            ('total_coding_minutes', '\U0001f4bb Coding minutes'),
        ]
        for column, title in stat_configs:
            rows = await self._get_stat_leaderboard(column, 'month', guild_id=guild.id)
            if not rows:
                continue
            stat_lines = []
            for i, row in enumerate(rows):
                uid = int(row['discord_id'])
                member = guild.get_member(uid)
                name = member.display_name if member else f'User {uid}'
                val = int(row.get('value') or 0)
                stat_lines.append(f'{medals[i]} **{name}**: **{val:,}**' if i < 3 else f'`#{i + 1}` {name}: {val:,}')
            embed.add_field(name=f'{title} (this month)', value='\n'.join(stat_lines), inline=False)
        embed.set_footer(text='Games, coding and streaming count only if this server enabled activity tracking')
        return embed

    # ============================================================
    # Event listeners for XP
    # ============================================================

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Award XP for messages (with cooldown); also counts toward the daily streak."""
        if message.author.bot or not message.guild:
            return
        if message.author.id in self._message_cooldowns:
            return
        self._message_cooldowns.set(message.author.id, True)
        await self._award_event('message', message.author, message.guild, RPG_POINTS['message'])

    @commands.Cog.listener()
    async def on_application_command_completion(self, interaction: nextcord.Interaction):
        """Slash commands (nextcord dispatches ``application_command_completion``; there is no
        ``application_command`` event, so the old listener never fired)."""
        if not interaction.guild or interaction.user is None or interaction.user.bot:
            return
        await self._award_event('command', interaction.user, interaction.guild, RPG_POINTS['command'])

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        """Prefix commands."""
        if not ctx.guild or ctx.author.bot:
            return
        await self._award_event('command', ctx.author, ctx.guild, RPG_POINTS['command'])

    @commands.Cog.listener()
    async def on_presence_update(self, before: nextcord.Member, after: nextcord.Member):
        """Live role while streaming. Nothing is stored (stream links are not copied into profiles;
        members add links themselves)."""
        if after.bot or not LIVE_ROLE_ID:
            return
        was_streaming = self._is_streaming(before)
        is_streaming = self._is_streaming(after)
        if was_streaming == is_streaming:
            return
        live_role = after.guild.get_role(LIVE_ROLE_ID)
        if not live_role:
            return
        if is_streaming and (
            not self.is_opted_in(after.id)
            or not (await guild_settings_service.get_settings(after.guild.id)).presence_tracking_enabled
        ):
            return  # server tracking off or member opted out: don't react to their streaming
        if (problem := punitive_role_problem(live_role, after.guild)) is not None:
            logger.warning('Live role in %s not managed: %s', after.guild.id, problem)
            return
        try:
            if is_streaming and live_role not in after.roles:
                await after.add_roles(live_role, reason='Started streaming')
            elif not is_streaming and live_role in after.roles:
                await after.remove_roles(live_role, reason='Stopped streaming')
        except Exception as exc:
            logger.warning('Failed to update live role for %s: %s', after.id, type(exc).__name__)

    @staticmethod
    def _is_streaming(member: nextcord.Member) -> bool:
        return any(a.type == nextcord.ActivityType.streaming for a in member.activities)

    @staticmethod
    def _get_stream_url(member: nextcord.Member) -> str | None:
        for activity in member.activities:
            if activity.type == nextcord.ActivityType.streaming:
                return getattr(activity, 'url', None)
        return None

    @staticmethod
    def _is_coding_activity(activity_name: str) -> bool:
        name_lower = activity_name.lower()
        return any(coding_app in name_lower for coding_app in CODING_APPS)

    @classmethod
    def presence_snapshot(cls, member: nextcord.Member) -> dict[str, set[str]]:
        """What a member is doing right now: {'gaming': games, 'coding': apps, 'streaming': games}.

        A "Playing" activity that matches a coding app counts as coding, not gaming. Listening
        (Spotify) is deliberately ignored.
        """
        games: set[str] = set()
        coding: set[str] = set()
        streaming = False
        for activity in member.activities:
            name = getattr(activity, 'name', None)
            if activity.type == nextcord.ActivityType.streaming:
                streaming = True
            elif activity.type == nextcord.ActivityType.playing and name:
                (coding if cls._is_coding_activity(name) else games).add(name)
            elif activity.type == nextcord.ActivityType.custom and name and cls._is_coding_activity(name):
                coding.add(name)
        snapshot: dict[str, set[str]] = {}
        if games:
            snapshot['gaming'] = games
        if coding:
            snapshot['coding'] = coding
        if streaming:
            snapshot['streaming'] = games or {'(stream)'}
        return snapshot

    # ============================================================
    # Activity tick — voice and presence sampling
    # ============================================================

    @staticmethod
    def voice_eligibility(member: nextcord.Member) -> tuple[bool, bool]:
        """(counts_minutes, earns_xp) for a member in voice.

        Rules: the AFK channel and deafened members (self or server) count nothing; a member alone
        (no other non-deafened human in the channel) counts minutes but earns no XP.
        """
        voice = member.voice
        channel = voice.channel if voice else None
        if channel is None:
            return False, False
        afk = member.guild.afk_channel
        if afk is not None and channel.id == afk.id:
            return False, False
        if voice.self_deaf or voice.deaf:
            return False, False
        # Company = another human who can hear (deafened members don't count as company).
        others = sum(
            1
            for m in channel.members
            if not m.bot and m.id != member.id and not (m.voice and (m.voice.self_deaf or m.voice.deaf))
        )
        return True, others > 0

    def _take_minutes(self) -> int:
        """Whole minutes elapsed since the previous tick (fractions carried over)."""
        now = time.monotonic()
        if self._last_tick is None:
            self._last_tick = now
            return 0  # nothing observed yet; the first minute is credited one tick later
        elapsed = now - self._last_tick + self._tick_carry
        self._last_tick = now
        minutes = int(elapsed // 60)
        self._tick_carry = elapsed - minutes * 60
        return min(minutes, 5)  # a stalled loop must not credit a long gap in one go

    def _xp_minutes(self, key: tuple[int, str], minutes: int, seen: dict[tuple[int, str], int]) -> int:
        """XP-eligible minutes for this tick, capping each continuous session at XP_SESSION_CAP minutes."""
        before = self._consecutive.get(key, 0)
        seen[key] = before + minutes
        return max(0, min(minutes, XP_SESSION_CAP_MINUTES - before))

    def collect_tick(
        self, minutes: int, tracking_guilds: set[int] | None = None
    ) -> tuple[dict[str, list[Award]], list[activity_service.Detail]]:
        """Build this tick's awards from the gateway cache (pure; no I/O)."""
        awards: dict[str, list[Award]] = {'voice': [], 'gaming': [], 'coding': [], 'streaming': []}
        details: list[activity_service.Detail] = []
        seen: dict[tuple[int, str], int] = {}

        # Voice: a user can only be in one voice channel at a time.
        for guild in self.bot.guilds:
            for channel in list(guild.voice_channels) + list(getattr(guild, 'stage_channels', [])):
                for member in channel.members:
                    if member.bot:
                        continue
                    counts, earns_xp = self.voice_eligibility(member)
                    if not counts:
                        continue
                    xp_minutes = self._xp_minutes((member.id, 'voice'), minutes, seen) if earns_xp else 0
                    awards['voice'].append(
                        Award(
                            user_id=member.id,
                            guild_id=guild.id,
                            quantity=minutes,
                            xp_base=xp_minutes * RPG_POINTS['voice_per_minute'],
                            role_multiplier=self._role_multiplier(member),
                            touch_streak=True,
                        )
                    )

        # Presence: only in servers that turned tracking on, skipping members who opted out; each member is
        # credited once per tick (main guild first) so a member of several servers isn't counted twice.
        guilds = sorted(
            (g for g in self.bot.guilds if g.id in (tracking_guilds or set())), key=lambda g: g.id != MAIN_GUILD_ID
        )
        credited: set[int] = set()
        for guild in guilds:
            for member in guild.members:
                user_id = member.id
                if member.bot or user_id in credited or not member.activities:
                    continue
                allowed, consent_at = self._consent.get(user_id, (True, None))
                if not allowed:
                    continue
                snapshot = self.presence_snapshot(member)
                if not snapshot:
                    continue
                credited.add(user_id)
                self._collect_presence(member, snapshot, consent_at, minutes, seen, awards, details)

        # Sessions not seen this tick ended: their XP cap resets.
        self._consecutive = seen
        return awards, details

    def _collect_presence(self, member, snapshot, consent_at, minutes, seen, awards, details) -> None:
        user_id = member.id
        for kind, names in snapshot.items():
            xp_minutes = self._xp_minutes((user_id, kind), minutes, seen)
            awards[kind].append(
                Award(
                    user_id=user_id,
                    guild_id=member.guild.id,
                    quantity=minutes,
                    xp_base=xp_minutes * PRESENCE_XP_PER_MINUTE,
                    role_multiplier=self._role_multiplier(member),
                    consent_at=consent_at,
                )
            )
            detail_type = {'gaming': 'game', 'coding': 'coding', 'streaming': 'streaming_game'}[kind]
            for name in names:
                if name != '(stream)':
                    details.append((user_id, detail_type, name, minutes, consent_at, member.guild.id))

    @tasks.loop(minutes=1)
    async def activity_tick(self):
        """Credit voice minutes, and presence minutes in servers that enabled tracking, from the live state."""
        if not runtime_state.db_available:
            self._last_tick = None  # don't credit the outage window later
            return
        minutes = self._take_minutes()
        if minutes <= 0:
            return
        from src.services.guild_modules_service import guild_modules_service

        tracking_guilds = set()
        enabled_guilds = set()
        for guild in self.bot.guilds:
            try:
                if not await guild_modules_service.enabled(guild.id, 'activity'):
                    continue
                enabled_guilds.add(guild.id)
                if (await guild_settings_service.get_settings(guild.id)).presence_tracking_enabled:
                    tracking_guilds.add(guild.id)
            except Exception:
                pass  # unreadable settings → treated as off
        awards, details = self.collect_tick(minutes, tracking_guilds)
        awards = {metric: [a for a in rows if a.guild_id in enabled_guilds] for metric, rows in awards.items()}
        details = [d for d in details if d[5] in enabled_guilds]
        try:
            # One transaction: totals, rollups and named details stay consistent, and presence rows are
            # written only where the server enabled tracking and the member hasn't opted out (locked row).
            await activity_service.award_tick(awards, details)
        except Exception:
            logger.warning('Activity tick: award failed', exc_info=True)

    @activity_tick.before_loop
    async def before_activity_tick(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # Background tasks
    # ============================================================

    @tasks.loop(seconds=LEADERBOARD_UPDATE_INTERVAL)
    async def update_leaderboard(self):
        """Edit each server's auto-updating leaderboard message (posted once if missing)."""
        if not runtime_state.db_available:
            return
        for guild in list(self.bot.guilds):
            try:
                await self._update_guild_leaderboard(guild)
            except Exception as exc:
                logger.warning('Failed to update leaderboard in %s: %s', guild.id, type(exc).__name__)

    async def _update_guild_leaderboard(self, guild: nextcord.Guild) -> None:
        from src.services.guild_modules_service import guild_modules_service

        if not await guild_modules_service.enabled(guild.id, 'leaderboards'):
            return
        settings = await guild_settings_service.get_settings(guild.id)
        channel_id = settings.leaderboard_channel_id
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, nextcord.TextChannel):
            return
        embed = await self._build_leaderboard_embed(guild=guild)
        if not embed:
            return
        # Only reuse a message in the *current* channel: after the channel changes (slash or dashboard) the
        # old message is left alone and a new one is posted. A stored ID from another channel 404s here,
        # which makes upsert_status post a fresh message.
        existing = self._leaderboard_messages.get(guild.id)
        if existing is not None and existing.channel.id != channel.id:
            existing = None
        if existing is None and settings.leaderboard_message_id:
            existing = channel.get_partial_message(settings.leaderboard_message_id)
        outcome = await outbound.upsert_status(
            f'leaderboard:{guild.id}:{channel.id}', channel, kind='leaderboard', embed=embed, message=existing
        )
        if outcome.message is not None:
            if outcome.status == SendStatus.SENT:
                await guild_settings_service.update_settings(guild.id, leaderboard_message_id=outcome.message.id)
            self._leaderboard_messages[guild.id] = outcome.message

    @update_leaderboard.before_loop
    async def before_update_leaderboard(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def evaluate_activity_roles(self):
        """In every server that has the activity roles, give each member the highest one their XP *in that
        server* earns; remove them after ACTIVITY_ROLE_INACTIVITY_DAYS without activity there. Roles are
        re-checked for safety before every assignment."""
        if not runtime_state.db_available:
            return
        for guild in list(self.bot.guilds):
            try:
                await self._evaluate_guild_activity_roles(guild)
            except Exception:
                logger.error('Activity role evaluation failed in %s', guild.id, exc_info=True)

    async def _evaluate_guild_activity_roles(self, guild: nextcord.Guild) -> None:
        from src.services.guild_modules_service import guild_modules_service

        if not await guild_modules_service.enabled(guild.id, 'activity_roles'):
            return
        roles = {
            key: role
            for key, name in _ACTIVITY_ROLE_NAMES.items()
            if (role := nextcord.utils.get(guild.roles, name=name)) is not None
        }
        if not roles:
            return
        if any(punitive_role_problem(role, guild) is not None for role in roles.values()):
            logger.warning('Activity roles in %s skipped: unsafe (privileged or above the bot)', guild.id)
        cutoff = datetime.now(UTC).date() - timedelta(days=ACTIVITY_ROLE_INACTIVITY_DAYS)
        rows = await db.fetch(
            """SELECT user_id, SUM(xp_earned) AS xp, MAX(activity_date) AS last_day
               FROM user_activity_daily WHERE guild_id = $1 GROUP BY user_id""",
            guild.id,
        )
        stats = {r['user_id']: (int(r['xp'] or 0), r['last_day']) for r in rows}
        all_roles = set(roles.values())
        candidates = {m.id for r in all_roles for m in r.members} | set(stats)
        for user_id in candidates:
            member = guild.get_member(user_id)
            if member is None or member.bot:
                continue
            xp, last_day = stats.get(user_id, (0, None))
            # Safety is re-checked live for every role at every change (roles can gain permissions while we
            # await); an unsafe role is neither given nor taken away.
            target = None
            if last_day is not None and last_day >= cutoff:
                for key, threshold in reversed(_ACTIVITY_ROLE_THRESHOLDS):
                    if xp >= threshold and key in roles and punitive_role_problem(roles[key], guild) is None:
                        target = roles[key]
                        break
            for role in all_roles & set(member.roles):
                if role != target and punitive_role_problem(role, guild) is None:
                    try:
                        await member.remove_roles(role, reason='Activity role update')
                    except Exception as exc:
                        logger.debug('Failed to remove role %s from %s: %s', role.id, member.id, type(exc).__name__)
            if target is not None and target not in member.roles and punitive_role_problem(target, guild) is None:
                try:
                    await member.add_roles(target, reason='Activity role update')
                except Exception as exc:
                    logger.debug('Failed to add role %s to %s: %s', target.id, member.id, type(exc).__name__)

    @evaluate_activity_roles.before_loop
    async def before_evaluate_activity_roles(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------
    # Inactivity monitoring — daily at INACTIVITY_CHECK_HOUR (IST), every server
    # ------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def check_inactivity(self):
        """Run the inactivity pass once per day at the configured IST time."""
        now = datetime.now(timezone(timedelta(hours=IST_UTC_OFFSET)))
        if now.hour != INACTIVITY_CHECK_HOUR or now.minute != INACTIVITY_CHECK_MINUTE:
            return
        if not runtime_state.db_available:
            return
        try:
            await self._run_inactivity_check()
        except Exception as exc:
            logger.error('Inactivity check failed: %s', exc, exc_info=True)

    async def _run_inactivity_check(self) -> None:
        """One pass over every server with inactivity alerts on and a log channel. DMs are capped across
        all servers per run."""
        budget = {'dm_attempts': 0}
        for guild in list(self.bot.guilds):
            try:
                await self._guild_inactivity(guild, budget)
            except Exception:
                logger.error('Inactivity check failed in %s', guild.id, exc_info=True)

    async def _guild_inactivity(self, guild: nextcord.Guild, budget: dict) -> None:
        from src.services.guild_modules_service import guild_modules_service

        if not await guild_modules_service.enabled(guild.id, 'activity'):
            return
        """Inactive = no recorded activity in *this* server for INACTIVITY_WEEK_DAYS / _MONTH_DAYS (members
        never active count from when they joined). Each member is reported once per level until they are
        active again; one digest per day in the log channel."""
        settings = await guild_settings_service.get_settings(guild.id)
        if not settings.inactivity_alerts_enabled:
            return
        logs_channel = await guild_settings_service.resolve_channel(guild, 'log_channel_id')
        if not isinstance(logs_channel, nextcord.TextChannel):
            return
        today = datetime.now(UTC).date()
        last_rows = await db.fetch(
            'SELECT user_id, MAX(activity_date) AS last_day FROM user_activity_daily WHERE guild_id = $1 GROUP BY user_id',
            guild.id,
        )
        last_active = {r['user_id']: r['last_day'] for r in last_rows}
        notices = {
            (r['user_id'], r['level']): r['notified_at'].date()
            for r in await db.fetch(
                'SELECT user_id, level, notified_at FROM inactivity_notices WHERE guild_id = $1', guild.id
            )
        }
        week: list[tuple[int, str]] = []
        month: list[tuple[int, str]] = []
        dm_delivered: list[int] = []
        dms_allowed = settings.inactivity_dm_enabled
        for member in guild.members:
            if member.bot:
                continue
            last = last_active.get(member.id) or (member.joined_at.date() if member.joined_at else None)
            if last is None:
                continue
            days = (today - last).days
            if days >= INACTIVITY_MONTH_DAYS and not _notified_since(notices, member.id, 'month', last):
                dm_note = ''
                if dms_allowed and budget['dm_attempts'] < INACTIVITY_MAX_DMS_PER_RUN:
                    budget['dm_attempts'] += 1
                    dm_embed = await info_embed(
                        '👋 We miss you!',
                        (
                            f"Hey there! We noticed you haven't been around **{guild.name}** in a while — "
                            f'about **{days} days** to be exact.\n\n'
                            "Everything okay? We'd love to see you back in the community. "
                            "If there's anything going on or you need help with anything, "
                            'feel free to reach out to our mods!'
                        ),
                    )
                    outcome = await outbound.dm(member, kind='inactivity_dm', embed=dm_embed)
                    if outcome.ok:
                        dm_delivered.append(member.id)
                        dm_note = ' (DM sent)'
                    elif outcome.status in (SendStatus.BREAKER_OPEN, SendStatus.DROPPED_BUDGET):
                        dms_allowed = False
                month.append((member.id, f'{member.mention} — {days} days{dm_note}'))
            elif INACTIVITY_WEEK_DAYS <= days < INACTIVITY_MONTH_DAYS and not _notified_since(
                notices, member.id, 'week', last
            ):
                week.append((member.id, f'{member.mention} — {days} days'))

        if not week and not month:
            return
        parts = []
        if month:
            parts.append(f'**Inactive 1 month+ ({len(month)})**\n' + '\n'.join(line for _, line in month[:25]))
        if week:
            parts.append(f'**Inactive 1 week+ ({len(week)})**\n' + '\n'.join(line for _, line in week[:25]))
        hidden = max(0, len(month) - 25) + max(0, len(week) - 25)
        description = '\n\n'.join(parts) + (f'\n\n…and {hidden} more' if hidden else '')
        embed = await alert_embed('⏰ Daily inactivity digest', description[:4000])
        outcome = await outbound.send(
            logs_channel,
            kind='inactivity_digest',
            guild_id=guild.id,
            embed=embed,
            allowed_mentions=nextcord.AllowedMentions.none(),
        )
        # Mark only what was delivered (a dropped digest is retried tomorrow); never DM anyone twice.
        marks = (
            [(uid, 'week') for uid, _ in week] + [(uid, 'month') for uid, _ in month]
            if outcome.ok
            else [(uid, 'month') for uid in dm_delivered]
        )
        if marks:
            await db.execute(
                """INSERT INTO inactivity_notices (guild_id, user_id, level, notified_at)
                   SELECT $1, u, l, NOW() FROM unnest($2::bigint[], $3::text[]) AS x(u, l)
                   ON CONFLICT (guild_id, user_id, level) DO UPDATE SET notified_at = NOW()""",
                guild.id,
                [m[0] for m in marks],
                [m[1] for m in marks],
            )

    @check_inactivity.before_loop
    async def before_check_inactivity(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=dt_time(hour=0, minute=5, tzinfo=UTC))
    async def monthly_season_archive(self):
        """On the 1st (UTC), snapshot last month's per-server standings and announce the main guild's."""
        if not runtime_state.db_available:
            return
        try:
            await self.ensure_previous_season_archived()
        except Exception:
            logger.error('Failed to run monthly season archive', exc_info=True)

    async def ensure_previous_season_archived(self) -> None:
        """Archive last month if it isn't complete yet; in the first 3 days of a month, announce it in every
        server that has a leaderboard channel and hasn't had its announcement yet. Runs daily and on startup,
        so a restart or DB outage on the 1st doesn't lose the month."""
        now = datetime.now(UTC)
        last_month = (now.replace(day=1) - timedelta(days=1)).date()
        season = last_month.strftime('%Y-%m')
        if not await db.fetchval('SELECT 1 FROM season_archives WHERE season_month = $1', season):
            await self.archive_season(last_month)
        if now.day > 3:
            return
        done = {
            r['guild_id']
            for r in await db.fetch('SELECT guild_id FROM season_announcements WHERE season_month = $1', season)
        }
        for guild in list(self.bot.guilds):
            if guild.id in done:
                continue
            try:
                if await self._announce_season(guild, season):
                    await db.execute(
                        'INSERT INTO season_announcements (guild_id, season_month) VALUES ($1, $2) ON CONFLICT DO NOTHING',
                        guild.id,
                        season,
                    )
            except Exception:
                logger.warning('Season announcement failed in %s', guild.id, exc_info=True)

    async def archive_season(self, day_in_month: date) -> None:
        """Snapshot one month's top 25 per category for every guild, all categories and the completion
        marker in one transaction (a partial archive is rolled back and retried)."""
        month_start = day_in_month.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        season = month_start.strftime('%Y-%m')
        pool = db.pool
        if pool is None:
            raise RuntimeError('database unavailable')
        async with pool.acquire() as conn, conn.transaction():
            # Same lock order as ActivityService and /privacy delete (users rows, ordered by discord_id): a
            # deletion either finishes first (its rows are gone when we read) or waits for this archive and
            # then deletes the snapshots too. Each INSERT below reads a fresh snapshot after the locks.
            await conn.execute(
                """SELECT 1 FROM users WHERE discord_id IN (
                       SELECT DISTINCT user_id::text FROM user_activity_daily
                       WHERE activity_date >= $1 AND activity_date < $2
                   ) ORDER BY discord_id FOR UPDATE""",
                month_start,
                next_month,
            )
            for category, column in _SEASON_CATEGORIES.items():
                presence = column in ('gaming_minutes', 'streaming_minutes', 'coding_minutes')
                await conn.execute(
                    f"""
                    INSERT INTO leaderboard_snapshots (guild_id, season_month, category, user_id, rank, score)
                    SELECT guild_id, $1, $2, user_id, rnk, score FROM (
                        SELECT d.guild_id, d.user_id, SUM(d.{column})::bigint AS score,
                               ROW_NUMBER() OVER (
                                   PARTITION BY d.guild_id ORDER BY SUM(d.{column}) DESC, d.user_id
                               ) AS rnk
                        FROM user_activity_daily d
                        {
                        '''JOIN users u ON u.discord_id = d.user_id::text AND u.presence_opt_in
                        JOIN guild_settings gs ON gs.guild_id = d.guild_id AND gs.presence_tracking_enabled'''
                        if presence
                        else ''
                    }
                        WHERE d.activity_date >= $3 AND d.activity_date < $4
                        GROUP BY d.guild_id, d.user_id
                        HAVING SUM(d.{column}) > 0
                    ) ranked
                    WHERE rnk <= 25
                    ON CONFLICT (guild_id, season_month, category, user_id) DO NOTHING
                    """,
                    season,
                    category,
                    month_start,
                    next_month,
                )
            await conn.execute('INSERT INTO season_archives (season_month) VALUES ($1) ON CONFLICT DO NOTHING', season)

    async def _announce_season(self, guild: nextcord.Guild, season: str) -> bool:
        from src.services.guild_modules_service import guild_modules_service

        if not await guild_modules_service.enabled(guild.id, 'leaderboards'):
            return False
        """Post a server's champions. Returns True when there is nothing more to do (posted, or nothing to
        announce/no channel); False to retry on the next run."""
        channel = await guild_settings_service.resolve_channel(guild, 'leaderboard_channel_id')
        if not isinstance(channel, nextcord.TextChannel):
            return True
        top3 = await db.fetch(
            """SELECT user_id, score FROM leaderboard_snapshots
               WHERE guild_id = $1 AND season_month = $2 AND category = 'xp' AND rank <= 3 ORDER BY rank""",
            guild.id,
            season,
        )
        if not top3:
            return True
        medals = ['\U0001f947', '\U0001f948', '\U0001f949']
        podium = []
        for i, row in enumerate(top3):
            member = guild.get_member(row['user_id'])
            name = member.display_name if member else f'User {row["user_id"]}'
            podium.append(f'{medals[i]} **{name}** \u2014 **{row["score"]:,}** XP this season')
        embed = await success_embed(
            title=f'\U0001f3c6 Season {season} Champions!',
            description=(
                "A new month has begun! Here are last season's champions in this server:\n\n"
                + '\n'.join(podium)
                + '\n\nCongratulations to all participants! The new season starts now.'
            ),
            contributor_source=__name__,
        )
        outcome = await outbound.send(
            channel, kind='season_announcement', embed=embed, essential=True, dedupe_key=f'season:{guild.id}:{season}'
        )
        return outcome.ok

    @monthly_season_archive.before_loop
    async def before_monthly_season_archive(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # Commands
    # ============================================================

    async def _user_row(self, user_id: int, columns: str) -> dict | None:
        row = await db.fetch_one(f'SELECT {columns} FROM users WHERE discord_id = $1', str(user_id))
        return dict(row) if row else None

    @nextcord.slash_command(name='level', description='Check your level, XP, and rank')
    @safe_slash_command(requires_db=True)
    async def level_command(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = nextcord.SlashOption(
            description='User to check (defaults to you)', required=False
        ),
    ):
        """Show level, XP and global rank for yourself or another user."""
        target = user or interaction.user
        row = await self._user_row(target.id, 'points, level') or {}
        points = row.get('points') or 0
        level = calculate_level(points)
        rank = await self._get_user_rank(target.id) if points else None

        rank_icon = '\U0001f3c5'
        if rank and rank <= 3:
            rank_icon = ['\U0001f947', '\U0001f948', '\U0001f949'][rank - 1]
        elif rank and rank <= 10:
            rank_icon = '⭐'

        description = (
            f'{rank_icon} **{target.display_name}**\n\n'
            f'**Level**: {level}\n'
            f'**XP**: {points:,}\n'
            f'**Rank** (all servers): {f"#{rank}" if rank else "Unranked"}\n\n'
            f'{_progress_bar(points)}\n'
            f'`{points_to_next_level(points):,} XP to next level`'
        )
        embed = await success_embed(
            title='Level Status',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await safe_send(interaction, embed=embed)

    @nextcord.slash_command(name='rank', description='View your rank card')
    @safe_slash_command(requires_db=True)
    async def rank_command(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = nextcord.SlashOption(
            description='User to check (defaults to you)', required=False
        ),
    ):
        """Generate and send a visual rank card."""
        await interaction.response.defer()
        target = user or interaction.user
        row = await self._user_row(target.id, 'points, current_streak') or {}
        points = row.get('points') or 0
        rank = await self._get_user_rank(target.id) if points else None

        avatar_bytes = None
        try:
            async with get_session().get(
                str(target.display_avatar.url), timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()
        except Exception:
            logger.debug('Failed to download avatar for %s', target.id, exc_info=True)

        from src.utils.card_generator import generate_rank_card

        buffer = await generate_rank_card(
            username=target.display_name,
            avatar_bytes=avatar_bytes,
            level=calculate_level(points),
            current_xp=points,
            xp_needed=points + points_to_next_level(points),
            rank=rank or 0,
            streak=row.get('current_streak') or 0,
        )
        await interaction.followup.send(file=nextcord.File(fp=buffer, filename='rank_card.png'))

    @nextcord.slash_command(name='leaderboard', description='View the community XP and activity leaderboards')
    async def leaderboard_group(self, interaction: nextcord.Interaction) -> None:
        embed = await info_embed(
            title='Leaderboard Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/leaderboard show [category] [period]` — All time (all servers) or this server '
                'for the past week, past month or this season\n'
                "• `/leaderboard season` — This server's current and previous season"
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @leaderboard_group.subcommand(name='show', description='View a paginated leaderboard')
    @safe_slash_command(requires_db=True)
    async def leaderboard_show_command(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            description='Category to rank by',
            required=False,
            choices=['xp', 'chat', 'voice', 'streaming', 'gaming', 'coding'],
        ),
        period: str = nextcord.SlashOption(
            description='Time period',
            required=False,
            choices=['alltime', 'season', 'month', 'week'],
        ),
    ):
        """This server's activity: all time (everything recorded here) or the past week/month/season."""
        await interaction.response.defer()
        category = category or 'xp'
        period = period or 'alltime'
        column = _LEADERBOARD_CATEGORIES[category]
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send('Leaderboards are per server; use this in a server.')
            return
        rows = await self._get_stat_leaderboard(
            column, None if period == 'alltime' else period, limit=50, guild_id=guild.id
        )
        scope = 'all time, this server' if period == 'alltime' else f'{_PERIOD_LABELS[period]}, this server'
        unit = 'XP' if category == 'xp' else ('messages' if category == 'chat' else 'min')
        medals = ['\U0001f947', '\U0001f948', '\U0001f949']
        lines = []
        for i, row in enumerate(rows):
            uid = int(row['discord_id'])
            member = guild.get_member(uid) if guild else None
            name = member.display_name if member else f'User {uid}'
            val = int(row.get('value') or 0)
            lines.append(
                f'{medals[i]} **{name}**: **{val:,}** {unit}' if i < 3 else f'`#{i + 1}` {name}: {val:,} {unit}'
            )
        pages = ['\n'.join(lines[i : i + 10]) for i in range(0, len(lines), 10)] or ['No activity recorded yet.']
        if category in ('gaming', 'streaming', 'coding'):
            pages[-1] += '\n\n*Tracked only if this server enabled activity tracking; members can `/privacy optout`.*'
        if category == 'xp' and period == 'alltime':
            server_xp = await self._guild_xp(interaction.user.id, guild.id)
            rank = await self._get_user_rank(interaction.user.id, guild.id) if server_xp else None
            pages[-1] += (
                f'\n\n──────────\n'
                f'\U0001f464 **Your rank here**: {f"#{rank}" if rank else "Unranked"} | **{server_xp:,}** XP in this server'
            )
        title = f'\U0001f3c6 Leaderboard — {category.title()} ({scope})'
        view = PaginationView(pages=pages, title=title, author_id=interaction.user.id)
        # wait=True returns the message (without it followup.send returns None and the view never times out cleanly)
        view.message = await interaction.followup.send(embed=view._build_embed(), view=view, wait=True)

    @leaderboard_group.subcommand(name='season', description="View this server's current and previous season")
    @safe_slash_command(requires_db=True)
    async def leaderboard_season_command(self, interaction: nextcord.Interaction) -> None:
        """A season is a calendar month (UTC) of activity in this server."""
        await interaction.response.defer()
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send('Seasons are per server; use this in a server.')
            return
        now = datetime.now(UTC)
        current_month = now.strftime('%Y-%m')
        prev_month = (now.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        medals = ['\U0001f947', '\U0001f948', '\U0001f949']

        lines = [f'**Current season: {current_month}**\n']
        for label, column in (('XP', 'points'), ('Chat', 'total_messages'), ('Voice', 'total_voice_minutes')):
            rows = await self._get_stat_leaderboard(column, 'season', limit=3, guild_id=guild.id)
            if not rows:
                lines.append(f'**{label}:** No data yet')
                continue
            cat_lines = []
            for i, row in enumerate(rows):
                member = guild.get_member(int(row['discord_id']))
                name = member.display_name if member else f'User {row["discord_id"]}'
                cat_lines.append(f'{medals[i]} **{name}**: {int(row["value"]):,}')
            lines.append(f'**{label}:**\n' + '\n'.join(cat_lines))

        lines.append(f'\n**Previous season: {prev_month}**')
        # Presence categories hide members who have since opted out.
        snapshots = await db.fetch(
            """SELECT s.category, s.user_id, s.rank, s.score FROM leaderboard_snapshots s
               LEFT JOIN users u ON u.discord_id = s.user_id::text
               WHERE s.guild_id = $1 AND s.season_month = $2 AND s.rank <= 3
                 AND (s.category NOT IN ('gaming', 'streaming', 'coding') OR COALESCE(u.presence_opt_in, FALSE))
               ORDER BY s.category, s.rank""",
            guild.id,
            prev_month,
        )
        if snapshots:
            cats: dict[str, list] = {}
            for snap in snapshots:
                cats.setdefault(snap['category'], []).append(snap)
            for cat, entries in cats.items():
                prev_lines = []
                for entry in entries:
                    member = guild.get_member(entry['user_id'])
                    name = member.display_name if member else f'User {entry["user_id"]}'
                    prev_lines.append(f'{medals[entry["rank"] - 1]} **{name}**: {entry["score"]:,}')
                lines.append(f'**{cat.title()}:**\n' + '\n'.join(prev_lines))
        else:
            lines.append('No archived data for the previous season.')

        embed = await success_embed(
            title='Season Standings',
            description='\n'.join(lines)[:4000],
            contributor_source=__name__,
            user=interaction.user,
            guild=guild,
        )
        await interaction.followup.send(embed=embed)

    @nextcord.slash_command(
        name='setupleaderboard',
        description="Set this server's auto-updating leaderboard channel (Manage Server)",
        contexts=[nextcord.InteractionContextType.guild],
        default_member_permissions=nextcord.Permissions(manage_guild=True),
    )
    @manage_guild_only()
    @safe_slash_command(requires_db=True)
    async def setupleaderboard_command(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(description='Channel for the leaderboard'),
    ):
        """Designate the channel for the auto-updating leaderboard (stored in guild settings)."""
        await guild_settings_service.update_settings(
            interaction.guild.id, leaderboard_channel_id=channel.id, leaderboard_message_id=None
        )
        self._leaderboard_messages.pop(interaction.guild.id, None)
        outbound.forget_status(f'leaderboard:{interaction.guild.id}:{channel.id}')
        if self.update_leaderboard.is_running():
            self.update_leaderboard.restart()
        embed = await success_embed(
            title='Leaderboard Configured',
            description=f'Leaderboard will auto-update in {channel.mention} every {LEADERBOARD_UPDATE_INTERVAL // 60} minutes.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='activity', description='View detailed activity stats or summary')
    async def activity_group(self, interaction: nextcord.Interaction) -> None:
        embed = await info_embed(
            title='Activity Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/activity stats [user]` — All-time totals (all servers)\n'
                '• `/activity summary [user]` — Last 7 days in this server'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @activity_group.subcommand(name='stats', description='View detailed activity stats')
    @safe_slash_command(requires_db=True)
    async def activity_stats_command(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = nextcord.SlashOption(
            description='User to check (defaults to you)', required=False
        ),
    ):
        """All-time activity totals across all servers."""
        target = user or interaction.user
        row = await self._user_row(
            target.id,
            """points, total_messages, total_voice_minutes, total_streaming_minutes, total_gaming_minutes,
               total_coding_minutes, total_commands, last_active, current_streak, longest_streak, presence_opt_in""",
        )
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
        current_streak = row.get('current_streak') or 0
        last_active = row.get('last_active')
        last_active_text = 'Never'
        if last_active:
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=UTC)
            last_active_text = f'<t:{int(last_active.timestamp())}:R>'

        activity_role = 'None'
        for role_key, threshold in reversed(_ACTIVITY_ROLE_THRESHOLDS):
            if points >= threshold:
                activity_role = _ACTIVITY_ROLE_NAMES[role_key]
                break

        description = (
            f'{_progress_bar(points)}\n'
            f'`{points_to_next_level(points):,} XP to next level`\n\n'
            f'\U0001f464 **Level** {calculate_level(points)} • **XP** {points:,} • **Rank** {activity_role}\n'
            f'\U0001f525 **Streak**: {current_streak}d (Best: {row.get("longest_streak") or 0}d) | '
            f'Bonus: {_streak_multiplier(current_streak)}x XP\n'
            '*All servers, all time.*'
        )
        embed = await success_embed(
            title=f'Activity Stats — {target.display_name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name='\U0001f4ac Messages', value=f'{row["total_messages"] or 0:,}', inline=True)
        embed.add_field(name='\U0001f50a Voice', value=f'{row["total_voice_minutes"] or 0:,} min', inline=True)
        embed.add_field(name='\U0001f4f1 Commands', value=f'{row["total_commands"] or 0:,}', inline=True)
        if row.get('presence_opt_in'):
            embed.add_field(name='\U0001f3ae Gaming', value=f'{row["total_gaming_minutes"] or 0:,} min', inline=True)
            embed.add_field(name='\U0001f4bb Coding', value=f'{row["total_coding_minutes"] or 0:,} min', inline=True)
            embed.add_field(
                name='\U0001f4fa Streaming', value=f'{row["total_streaming_minutes"] or 0:,} min', inline=True
            )
        else:
            embed.add_field(
                name='\U0001f3ae Games / coding / streaming',
                value='Not tracked (you opted out — `/privacy optin` to allow it again)',
                inline=False,
            )
        embed.add_field(name='\U0001f552 Last Active', value=last_active_text, inline=True)
        await safe_send(interaction, embed=embed)

    @activity_group.subcommand(name='summary', description='7-day activity summary in this server')
    @safe_slash_command(requires_db=True)
    async def activity_summary_command(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = nextcord.SlashOption(
            description='User to check (defaults to you)', required=False
        ),
    ):
        """Last 7 UTC days (today included) in this server, one bar per day (empty days shown)."""
        target = user or interaction.user
        today = datetime.now(UTC).date()
        start = today - timedelta(days=6)
        rows = await db.fetch(
            """
            SELECT activity_date, messages, voice_minutes, gaming_minutes, streaming_minutes, coding_minutes
            FROM user_activity_daily
            WHERE user_id = $1 AND guild_id = $2 AND activity_date BETWEEN $3 AND $4
            """,
            target.id,
            interaction.guild.id if interaction.guild else 0,
            start,
            today,
        )
        by_day = {r['activity_date']: r for r in rows}
        days = [start + timedelta(days=i) for i in range(7)]

        def series(col: str) -> list[int]:
            return [int(by_day[d][col] or 0) if d in by_day else 0 for d in days]

        def fmt_hours(val: int) -> str:
            h, m = divmod(val, 60)
            return f'{h}h {m}m' if h else f'{m}m'

        streak_row = await self._user_row(target.id, 'current_streak, longest_streak, presence_opt_in') or {}
        current_streak = streak_row.get('current_streak') or 0
        messages, voice = series('messages'), series('voice_minutes')
        lines = [
            f'\U0001f4ac Messages: {_sparkline(messages)} **{sum(messages)}**',
            f'\U0001f50a Voice: {_sparkline(voice)} **{fmt_hours(sum(voice))}**',
        ]
        if streak_row.get('presence_opt_in'):
            for label, col in (
                ('\U0001f4bb Coding', 'coding_minutes'),
                ('\U0001f3ae Gaming', 'gaming_minutes'),
                ('\U0001f4fa Streaming', 'streaming_minutes'),
            ):
                values = series(col)
                lines.append(f'{label}: {_sparkline(values)} **{fmt_hours(sum(values))}**')
        lines += [
            '',
            f'\U0001f525 **Streak**: {current_streak}d (Best: {streak_row.get("longest_streak") or 0}d) | '
            f'Bonus: {_streak_multiplier(current_streak)}x XP',
            f'*{start:%d %b} – {today:%d %b} (UTC), this server.*',
        ]
        embed = await success_embed(
            title=f'Activity Summary — {target.display_name}',
            description='\n'.join(lines),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await safe_send(interaction, embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(RPGManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.rpg')
    return True
