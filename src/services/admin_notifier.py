from datetime import UTC, datetime, timedelta

import nextcord

from src.config.config import ADMIN_ALERT_CHANNEL_ID
from src.core.runtime_state import runtime_state
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import alert_embed
from src.utils.logger import get_logger
from src.utils.outbound import outbound

logger = get_logger('VEKA.admin_notifier')

_CHANNEL_CACHE_TTL = timedelta(minutes=5)


class AdminNotifier:
    def __init__(self, bot: nextcord.Client):
        self.bot = bot
        self._channel: nextcord.abc.Messageable | None = None
        self._channel_fetched_at: datetime | None = None

    async def _get_channel(self, guild_id: int | None = None):
        # Guild-specific alerts stay inside that guild: never fall back to another server's channel.
        if guild_id is not None:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return None
            try:
                settings = await guild_settings_service.get_settings(guild_id)
            except Exception:
                return None
            channel_id = settings.alert_channel_id or settings.log_channel_id
            return guild.get_channel(channel_id) if channel_id else None

        # Fallback to global admin alert channel
        if not ADMIN_ALERT_CHANNEL_ID:
            return None

        now = datetime.now(UTC)
        if self._channel is not None and self._channel_fetched_at is not None:
            if now - self._channel_fetched_at < _CHANNEL_CACHE_TTL:
                return self._channel
            self._channel = None

        channel = self.bot.get_channel(ADMIN_ALERT_CHANNEL_ID)  # type: ignore[arg-type]
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(ADMIN_ALERT_CHANNEL_ID)  # type: ignore[arg-type]
            except Exception as e:
                logger.warning('Failed to fetch admin alert channel: %s', e)
                self._channel = None
                self._channel_fetched_at = now
                return None

        self._channel = channel  # type: ignore[assignment]
        self._channel_fetched_at = now
        return self._channel

    def _should_alert(self, dedupe_key: str | None, cooldown_minutes: int) -> bool:
        if not dedupe_key:
            return True

        now = datetime.now(UTC)
        cache = runtime_state.alert_state_cache
        last_alert_time = cache.get(dedupe_key)

        if last_alert_time and (now - last_alert_time) < timedelta(minutes=cooldown_minutes):
            return False

        cache[dedupe_key] = now
        return True

    def clear_cooldown(self, dedupe_key: str):
        """Clear a cooldown, useful for when a system recovers."""
        runtime_state.alert_state_cache.pop(dedupe_key, None)

    async def send_alert(
        self,
        title: str,
        description: str,
        severity: str = 'INFO',
        dedupe_key: str = None,
        cooldown_minutes: int = 60,
        guild_id: int | None = None,
    ):
        channel = await self._get_channel(guild_id)
        if not channel:
            logger.info('Admin alert skipped (no channel): [%s] %s - %s', severity, title, description)
            return

        if not self._should_alert(dedupe_key, cooldown_minutes):
            return

        embed = await alert_embed(title=title, description=description, severity=severity, contributor_source=__name__)
        # Essential: alerts bypass the circuit breaker (they report it) but still respect budgets and dedupe.
        outcome = await outbound.send(channel, kind='admin_alert', embed=embed, essential=True)
        if outcome.ok:
            logger.info('Sent admin alert: [%s] %s', severity, title)
        else:
            # Undelivered: don't let the cooldown suppress the next attempt.
            if dedupe_key:
                self.clear_cooldown(dedupe_key)
            logger.error('Failed to send admin alert (%s): %s', outcome.status.value, title)

    async def send_startup_summary(self):
        if not await self._get_channel():
            return

        checks_text = ''
        for check in runtime_state.startup_check_results:
            icon = '✅' if check['status'] == 'PASS' else '⚠️' if check['status'] == 'WARN' else '❌'
            checks_text += f'{icon} **{check["name"]}**: {check["message"]}\n'

        if not checks_text:
            checks_text = 'No startup checks ran.'

        description = (
            f'**Environment**: `{runtime_state.branch}` @ `{runtime_state.commit}`\n'
            f'**Version**: `{runtime_state.version}`\n'
            f'**DB Status**: {"Connected 🟢" if runtime_state.db_available else "Offline 🔴"}\n\n'
            f'**Loaded Cogs**: {len(runtime_state.loaded_cogs)}\n'
            f'**Failed Cogs**: {len(runtime_state.failed_cogs)}\n'
            f'**Degraded Features**: {len(runtime_state.degraded_features)}\n\n'
            f'**Startup Checks**:\n{checks_text}'
        )

        severity = 'WARN' if runtime_state.failed_cogs or not runtime_state.db_available else 'INFO'

        await self.send_alert(
            title='Bot Deployment / Startup Summary',
            description=description,
            severity=severity,
            dedupe_key='startup_summary',
        )
