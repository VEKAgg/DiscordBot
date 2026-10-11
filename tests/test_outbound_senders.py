"""Bot-initiated senders stay bounded: honeypot digest, welcome raid mode, squad cooldown, inactivity digest,
and the nightly retention job."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import nextcord

from src.cogs.admin.honeypot import Honeypot
from src.cogs.admin.maintenance import RETENTION_RULES, run_retention
from src.cogs.admin.notifications import Notifications
from src.cogs.admin.welcome import RAID_JOIN_THRESHOLD, Welcome
from src.cogs.rpg.rpg_manager import RPGManager
from src.services.guild_settings_service import GuildSettings
from src.utils.outbound import SendOutcome, SendStatus


def _text_channel(cid=7, guild_id=10):
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.id = cid
    channel.mention = f'<#{cid}>'
    channel.guild = SimpleNamespace(id=guild_id)
    return channel


def _recording_outbound():
    sent: list[dict] = []

    async def send(dest, **kwargs):
        sent.append({'dest': dest, **kwargs})
        return SendOutcome(SendStatus.SENT, message=MagicMock())

    async def dm(user, **kwargs):
        sent.append({'dm': user, **kwargs})
        return SendOutcome(SendStatus.SENT, message=MagicMock())

    return SimpleNamespace(send=send, dm=dm), sent


# ---------------------------------------------------------------- honeypot


async def test_honeypot_raid_sends_one_alert_and_one_digest():
    channel = _text_channel()
    guild = MagicMock()
    guild.id = 10
    guild.get_channel = MagicMock(return_value=channel)
    cog = Honeypot(MagicMock())
    out, sent = _recording_outbound()
    flushes: list = []

    def capture_spawn(coro, *, name):  # noqa: ARG001
        flushes.append(coro)
        return MagicMock()

    g = Honeypot._send_alert.__globals__
    db = SimpleNamespace(fetch_one=AsyncMock(return_value={'logging_channel_id': 7, 'notification_role_id': 55}))
    with patch.dict(g, {'outbound': out, 'spawn': capture_spawn, 'db': db}):
        for i in range(30):
            message = MagicMock()
            message.guild = guild
            message.author = SimpleNamespace(id=100 + i, mention=f'<@{100 + i}>')
            message.channel = channel
            message.content = 'free nitro'
            await cog._send_alert(message, {'id': 1}, 'ban', 'success')
        assert len(sent) == 1  # first alert only, with the role ping
        assert sent[0]['content'] == '<@&55>'
        assert len(flushes) == 1

        with patch.object(g['asyncio'], 'sleep', AsyncMock()):
            await flushes[0]

    assert len(sent) == 2
    digest = sent[1]['embed']
    assert '29 more trigger' in digest.title
    assert sent[1]['allowed_mentions'].roles is False  # no second ping
    assert db.fetch_one.await_count == 1  # logging config cached


# ---------------------------------------------------------------- welcome


async def test_welcome_raid_batches_joins_without_cards():
    channel = _text_channel()
    guild = MagicMock()
    guild.id = 10
    guild.name = 'VEKA'
    guild.member_count = 100
    guild.icon = None
    guild.get_channel = MagicMock(return_value=channel)
    settings = GuildSettings(guild_id=10, welcome_channel_id=7, welcome_card_enabled=True)
    cog = Welcome(MagicMock())
    cog._download_asset = AsyncMock(return_value=None)  # type: ignore[method-assign]
    out, sent = _recording_outbound()
    flushes: list = []

    def capture_spawn(coro, *, name):  # noqa: ARG001
        flushes.append(coro)

    g = Welcome.on_member_join.__globals__
    card = AsyncMock(return_value=__import__('io').BytesIO(b'png'))
    with (
        patch.dict(g, {'outbound': out, 'spawn': capture_spawn}),
        patch.object(g['guild_settings_service'], 'get_settings', AsyncMock(return_value=settings)),
        patch('src.utils.card_generator.generate_welcome_card', card),
    ):
        for i in range(40):
            member = MagicMock()
            member.bot = False
            member.guild = guild
            member.mention = f'<@{i}>'
            member.display_name = f'u{i}'
            await cog.on_member_join(member)
        with patch.object(g['asyncio'], 'sleep', AsyncMock()):
            for flush in flushes:
                await flush

    individual = [s for s in sent if s['kind'] == 'welcome']
    batches = [s for s in sent if s['kind'] == 'welcome_batch']
    assert len(individual) == RAID_JOIN_THRESHOLD  # normal welcomes until the raid threshold
    assert card.await_count == RAID_JOIN_THRESHOLD
    assert len(batches) == 1
    # 35 batched joins: 30 mentions shown, the rest summarised.
    assert batches[0]['embed'].description.endswith('and 5 others!')


# ---------------------------------------------------------------- squad ping


def test_squad_ping_cooldown_is_per_guild():
    cog = Notifications(MagicMock())
    assert cog._claim_squad_ping(1) is True
    assert cog._claim_squad_ping(1) is False
    assert cog._claim_squad_ping(2) is True


# ---------------------------------------------------------------- inactivity


class _InactivityDB:
    """Per-server inactivity: last activity per member, existing notices, and recorded marks."""

    def __init__(self, last_days: dict[int, int], notices=()):
        from datetime import timedelta

        today = datetime.now(UTC).date()
        self.last = [{'user_id': uid, 'last_day': today - timedelta(days=d)} for uid, d in last_days.items()]
        self.notices = list(notices)
        self.marks: list[tuple] = []

    async def fetch(self, sql, *_args):
        return self.notices if 'inactivity_notices' in sql else self.last

    async def execute(self, sql, *args):
        if 'inactivity_notices' in sql:
            self.marks.extend(zip(args[1], args[2], strict=True))
        return 'INSERT 0 1'


async def _run_inactivity(dm_enabled: bool, *, send_ok: bool = True, alerts: bool = True):
    logs = _text_channel()
    members = [SimpleNamespace(id=i, bot=False, mention=f'<@{i}>', joined_at=None) for i in range(1, 121)]
    guild = MagicMock()
    guild.id = 10
    guild.name = 'VEKA'
    guild.members = members
    bot = MagicMock()
    bot.guilds = [guild]
    cog = RPGManager(bot)
    sent: list[dict] = []

    async def send(dest, **kwargs):
        sent.append({'dest': dest, **kwargs})
        return SendOutcome(SendStatus.SENT if send_ok else SendStatus.DROPPED_BUDGET, message=MagicMock())

    async def dm(user, **kwargs):
        sent.append({'dm': user, **kwargs})
        return SendOutcome(SendStatus.SENT, message=MagicMock())

    # 1–60 inactive 8 days (week), 61–120 inactive 40 days (month).
    database = _InactivityDB({i: (8 if i <= 60 else 40) for i in range(1, 121)})
    g = RPGManager._run_inactivity_check.__globals__
    settings = GuildSettings(guild_id=10, inactivity_dm_enabled=dm_enabled, inactivity_alerts_enabled=alerts)
    with (
        patch.dict(g, {'outbound': SimpleNamespace(send=send, dm=dm), 'db': database}),
        patch.object(g['guild_settings_service'], 'resolve_channel', AsyncMock(return_value=logs)),
        patch.object(g['guild_settings_service'], 'get_settings', AsyncMock(return_value=settings)),
    ):
        await cog._run_inactivity_check()
    return sent, database


async def test_inactivity_sends_one_digest_and_no_dms_by_default():
    sent, database = await _run_inactivity(dm_enabled=False)
    assert len(sent) == 1 and sent[0]['kind'] == 'inactivity_digest'
    assert sum(1 for _, level in database.marks if level == 'month') == 60
    assert sum(1 for _, level in database.marks if level == 'week') == 60


async def test_inactivity_dms_are_opt_in_and_capped():
    from src.config.config import INACTIVITY_MAX_DMS_PER_RUN

    sent, _ = await _run_inactivity(dm_enabled=True)
    dms = [s for s in sent if 'dm' in s]
    digests = [s for s in sent if s.get('kind') == 'inactivity_digest']
    assert len(dms) == INACTIVITY_MAX_DMS_PER_RUN
    assert len(digests) == 1


async def test_inactivity_not_marked_when_digest_is_dropped():
    """A dropped digest must be retried tomorrow, not silently consumed."""
    _sent, database = await _run_inactivity(dm_enabled=False, send_ok=False)
    assert database.marks == []


async def test_inactivity_alerts_can_be_turned_off_per_server():
    sent, database = await _run_inactivity(dm_enabled=True, alerts=False)
    assert sent == [] and database.marks == []


# ---------------------------------------------------------------- retention


async def test_retention_runs_every_rule_even_if_one_fails():
    calls = []

    async def execute(sql, _days):
        calls.append(sql)
        if 'honeypot_events' in sql:
            raise RuntimeError('boom')
        return 'DELETE 3'

    with patch.dict(run_retention.__globals__, {'db': SimpleNamespace(execute=execute)}):
        results = await run_retention()

    assert len(calls) == len(RETENTION_RULES)
    assert results['honeypot_events'].startswith('error')
    assert results['user_activity_log'] == 'DELETE 3'
    # Aggregates and the audit trail are never purged.
    assert not any(t in sql for sql in calls for t in ('user_activity_daily', 'audit_logs', 'feed_seen_items'))


async def test_failed_admin_alert_does_not_consume_cooldown():
    from src.services.admin_notifier import AdminNotifier

    notifier = AdminNotifier(MagicMock())
    notifier._get_channel = AsyncMock(return_value=_text_channel())  # type: ignore[method-assign]
    outcomes = [SendOutcome(SendStatus.DROPPED_BUDGET), SendOutcome(SendStatus.SENT)]
    send = AsyncMock(side_effect=outcomes)
    with patch.dict(AdminNotifier.send_alert.__globals__, {'outbound': SimpleNamespace(send=send)}):
        await notifier.send_alert('DB down', 'x', dedupe_key='db_unavailable')
        await notifier.send_alert('DB down', 'x', dedupe_key='db_unavailable')
    assert send.await_count == 2


async def test_guild_alert_never_falls_back_to_another_guild():
    from src.services.admin_notifier import AdminNotifier

    bot = MagicMock()
    bot.get_guild = MagicMock(return_value=None)  # bot not in that guild
    notifier = AdminNotifier(bot)
    assert await notifier._get_channel(guild_id=123) is None
    bot.get_channel.assert_not_called()
