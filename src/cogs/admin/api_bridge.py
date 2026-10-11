"""API bridge — publishes the gateway state the dashboard API can't see into PostgreSQL.

- ``bot_status`` (one row) every minute: version, latency, guild count, DB state, outbound guard state.
- ``bot_guild_snapshot`` per guild: name, icon, counts, channels, roles, the bot's permissions.
  Refreshed every 5 minutes, and within a minute after a guild/channel/role change. Removed when the
  bot leaves a guild, so the API's "bot is in this guild" check stays truthful.
"""

from __future__ import annotations

import json
import logging

import nextcord
from nextcord.ext import commands, tasks

from src.core.runtime_state import runtime_state
from src.database.database import db
from src.utils.safety import safe_background_task

logger = logging.getLogger('VEKA.api_bridge')

SNAPSHOT_EVERY_TICKS = 5  # full guild snapshot every 5 minutes

_STATUS_SQL = """
INSERT INTO bot_status (id, version, commit_sha, started_at, latency_ms, guild_count, db_ok,
                        degraded_features, outbound, updated_at)
VALUES (1, $1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, NOW())
ON CONFLICT (id) DO UPDATE SET
    version = EXCLUDED.version, commit_sha = EXCLUDED.commit_sha, started_at = EXCLUDED.started_at,
    latency_ms = EXCLUDED.latency_ms, guild_count = EXCLUDED.guild_count, db_ok = EXCLUDED.db_ok,
    degraded_features = EXCLUDED.degraded_features, outbound = EXCLUDED.outbound, updated_at = NOW()
"""

_SNAPSHOT_SQL = """
INSERT INTO bot_guild_snapshot (guild_id, name, icon_url, owner_id, member_count, online_count,
                                channels, roles, bot_permissions, bot_top_role_position, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, NOW())
ON CONFLICT (guild_id) DO UPDATE SET
    name = EXCLUDED.name, icon_url = EXCLUDED.icon_url, owner_id = EXCLUDED.owner_id,
    member_count = EXCLUDED.member_count, online_count = EXCLUDED.online_count,
    channels = EXCLUDED.channels, roles = EXCLUDED.roles, bot_permissions = EXCLUDED.bot_permissions,
    bot_top_role_position = EXCLUDED.bot_top_role_position, updated_at = NOW()
"""


def guild_snapshot(guild: nextcord.Guild) -> tuple:
    channels = [
        {
            'id': str(c.id),
            'name': c.name,
            'type': str(c.type),
            'parent_id': str(c.category_id) if getattr(c, 'category_id', None) else None,
            'position': c.position,
        }
        for c in guild.channels
    ]
    roles = [
        {
            'id': str(r.id),
            'name': r.name,
            'color': r.color.value,
            'position': r.position,
            'managed': r.managed,
            'permissions': str(r.permissions.value),
        }
        for r in guild.roles
        if not r.is_default()
    ]
    online = sum(1 for m in guild.members if not m.bot and m.status != nextcord.Status.offline)
    me = guild.me
    return (
        guild.id,
        guild.name,
        str(guild.icon.url) if guild.icon else None,
        guild.owner_id,
        guild.member_count or 0,
        online,
        json.dumps(channels),
        json.dumps(roles),
        me.guild_permissions.value if me is not None else None,
        me.top_role.position if me is not None else None,
    )


class ApiBridge(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._ticks = 0
        self._dirty: set[int] = set()

    async def cog_ready(self) -> None:
        if not self.publish.is_running():
            self.publish.start()

    def cog_unload(self) -> None:
        self.publish.cancel()

    @tasks.loop(minutes=1)
    @safe_background_task(name='api_bridge')
    async def publish(self) -> None:
        if not runtime_state.db_available:
            return
        outbound = getattr(self.bot, 'outbound', None)
        latency = self.bot.latency
        await db.execute(
            _STATUS_SQL,
            runtime_state.version,
            runtime_state.commit,
            runtime_state.startup_time,
            None if latency != latency or latency == float('inf') else int(latency * 1000),  # NaN/inf guard
            len(self.bot.guilds),
            runtime_state.db_available,
            json.dumps(list(runtime_state.degraded_features)),
            json.dumps(outbound.snapshot() if outbound is not None else {}),
        )
        full = self._ticks % SNAPSHOT_EVERY_TICKS == 0
        self._ticks += 1
        targets = self.bot.guilds if full else [g for g in self.bot.guilds if g.id in self._dirty]
        self._dirty.clear()
        for guild in targets:
            await db.execute(_SNAPSHOT_SQL, *guild_snapshot(guild))
        if full:
            current = [g.id for g in self.bot.guilds]
            await db.execute('DELETE FROM bot_guild_snapshot WHERE NOT (guild_id = ANY($1::bigint[]))', current)

    @publish.before_loop
    async def before_publish(self) -> None:
        await self.bot.wait_until_ready()

    def _mark(self, guild: nextcord.Guild | None) -> None:
        if guild is not None:
            self._dirty.add(guild.id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: nextcord.Guild) -> None:
        self._mark(guild)

    @commands.Cog.listener()
    async def on_guild_update(self, _before: nextcord.Guild, after: nextcord.Guild) -> None:
        self._mark(after)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: nextcord.Guild) -> None:
        self._dirty.discard(guild.id)
        if runtime_state.db_available:
            try:
                await db.execute('DELETE FROM bot_guild_snapshot WHERE guild_id = $1', guild.id)
            except Exception:
                logger.warning('Failed to drop snapshot for guild %s', guild.id, exc_info=True)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: nextcord.abc.GuildChannel) -> None:
        self._mark(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: nextcord.abc.GuildChannel) -> None:
        self._mark(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, _before: nextcord.abc.GuildChannel, after: nextcord.abc.GuildChannel
    ) -> None:
        self._mark(after.guild)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: nextcord.Role) -> None:
        self._mark(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: nextcord.Role) -> None:
        self._mark(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_update(self, _before: nextcord.Role, after: nextcord.Role) -> None:
        self._mark(after.guild)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(ApiBridge(bot))
    logger.info('Loaded cog: src.cogs.admin.api_bridge')
