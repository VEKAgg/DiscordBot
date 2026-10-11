"""A mass unban of 500 users must send a small, bounded number of messages (the bot was quarantined once)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import nextcord
import pytest

from src.cogs.admin.massunban import DM_CAP_PER_JOB, MassUnban
from src.utils.outbound import OutboundConfig, OutboundMessenger

N_USERS = 500


class FakeDB:
    """Just enough of the massunban tables to run a job end to end."""

    def __init__(self, notify_users: bool) -> None:
        self.job: dict[str, Any] = {
            'id': 1,
            'guild_id': 10,
            'requested_by': 99,
            'reason': None,
            'status': 'running',
            'notify_users': notify_users,
            'total_matched': N_USERS,
            'total_attempted': 0,
            'total_succeeded': 0,
            'total_failed': 0,
            'total_skipped': 0,
            'dm_sent': 0,
            'dm_failed': 0,
            'rate_limit_hits': 0,
            'started_at': datetime.now(UTC),
            'completed_at': None,
            'progress_channel_id': None,
            'progress_message_id': None,
        }
        self.items = [
            {'id': i, 'target_user_id': str(1000 + i), 'target_username': f'u{i}', 'status': 'pending'}
            for i in range(N_USERS)
        ]

    async def fetch_one(self, _sql, *_args):
        return dict(self.job)

    async def fetch(self, sql, *_args):
        if "status = 'pending'" in sql:
            return [dict(i) for i in self.items if i['status'] == 'pending']
        return []

    async def fetchval(self, sql, *_args):
        if 'dm_sent' in sql:
            return self.job['dm_sent']
        if sql.startswith('SELECT status'):
            return self.job['status']
        if "SET status = 'completed'" in sql:
            if self.job['status'] != 'running':
                return None
            self.job['status'] = 'completed'
            return self.job['id']
        return None

    async def execute(self, sql, *args):
        if sql.lstrip().startswith('UPDATE massunban_job_items'):
            item = next(i for i in self.items if i['id'] == args[5])
            item['status'] = args[0]
        elif 'total_attempted = total_attempted + 1' in sql:
            self.job['total_attempted'] += 1
            col = sql.split('SET')[1].split('=')[0].strip()
            self.job[col] += 1
            self.job['dm_sent'] += args[2]
            self.job['dm_failed'] += args[3]
        elif 'SET status = $1' in sql:
            self.job['status'] = args[0]
        return 'UPDATE 1'


class Counter:
    def __init__(self) -> None:
        self.channel_posts = 0
        self.edits = 0
        self.dms = 0


def _setup(notify_users: bool, users_share_guild: bool):
    counter = Counter()
    db = FakeDB(notify_users)

    def make_message(**_):
        counter.channel_posts += 1
        msg = MagicMock(id=555)

        async def edit(**_):
            counter.edits += 1
            return msg

        msg.edit = edit
        return msg

    log_channel = MagicMock(spec=nextcord.TextChannel)
    log_channel.id = 77
    log_channel.guild = SimpleNamespace(id=10)
    log_channel.mention = '#log'
    log_channel.send = AsyncMock(side_effect=make_message)

    guild = MagicMock()
    guild.id = 10
    guild.name = 'VEKA'
    guild.unban = AsyncMock()
    guild.get_member = MagicMock(return_value=SimpleNamespace(id=99))  # the runner

    other_guild = MagicMock()
    other_guild.id = 20
    other_guild.get_member = MagicMock(return_value=object() if users_share_guild else None)

    def make_user(uid):
        user = MagicMock(spec=nextcord.User)
        user.id = uid

        async def send(**_):
            counter.dms += 1
            return MagicMock()

        user.send = send
        return user

    bot = MagicMock()
    bot.guilds = [guild, other_guild]
    bot.get_guild = MagicMock(return_value=guild)
    bot.get_user = MagicMock(side_effect=make_user)

    # Runner DM goes through the same messenger; count it too.
    async def runner_send(**_):
        counter.dms += 1
        return MagicMock()

    guild.get_member.return_value = SimpleNamespace(id=99, send=runner_send)

    clock_t = [0.0]

    def clock():
        return clock_t[0]

    async def fake_sleep(seconds):
        clock_t[0] += seconds

    messenger = OutboundMessenger(OutboundConfig(), clock=clock, sleep=fake_sleep)
    messenger.bind(bot)
    return counter, db, log_channel, bot, messenger, fake_sleep, clock


@pytest.mark.parametrize(
    ('notify_users', 'share'),
    [(False, True), (True, False), (True, True)],
)
async def test_500_user_mass_unban_sends_bounded_messages(notify_users, share, _reset_runtime_state):
    _reset_runtime_state.db_available = True
    counter, db, log_channel, bot, messenger, fake_sleep, clock = _setup(notify_users, share)
    cog = MassUnban(bot)
    cog._active_jobs[1] = False

    g = MassUnban._run_job.__globals__
    with (
        patch.dict(
            g,
            {
                'db': db,
                'outbound': messenger,
                # Module-local stand-ins only: patching the real time/asyncio would freeze the event loop.
                'asyncio': SimpleNamespace(
                    sleep=fake_sleep, Lock=asyncio.Lock, current_task=asyncio.current_task, Task=asyncio.Task
                ),
                'time': SimpleNamespace(monotonic=clock),
            },
        ),
        patch.object(cog, '_log_channel', AsyncMock(return_value=log_channel)),
    ):
        await cog._run_job(1, resumed=False)

    assert db.job['status'] == 'completed'
    assert db.job['total_succeeded'] == N_USERS
    # One progress message, edited — never a post per user or per event.
    assert counter.channel_posts == 1
    if notify_users and share:
        assert 0 < db.job['dm_sent'] <= DM_CAP_PER_JOB
    else:
        assert db.job['dm_sent'] == 0
    # Apology DMs (≤ cap) + one final summary DM to the runner.
    assert counter.dms <= (DM_CAP_PER_JOB if notify_users and share else 0) + 1
    # Progress edits are throttled (20 s apart) — far fewer than the number of users.
    assert counter.edits < N_USERS / 5


async def test_worker_stops_when_job_is_cancelled_in_the_database(_reset_runtime_state):
    """A dashboard cancel whose NOTIFY never arrived still stops the worker at the next item."""
    _reset_runtime_state.db_available = True
    counter, db, log_channel, bot, messenger, fake_sleep, clock = _setup(False, True)
    cog = MassUnban(bot)
    cog._active_jobs[1] = False
    unbanned = []
    guild = bot.get_guild.return_value

    async def unban(obj, reason=None):  # noqa: ARG001
        unbanned.append(obj.id)
        if len(unbanned) == 3:
            db.job['status'] = 'cancelled'  # cancelled elsewhere; no in-memory flag set

    guild.unban = unban
    g = MassUnban._run_job.__globals__
    with (
        patch.dict(
            g,
            {
                'db': db,
                'outbound': messenger,
                'asyncio': SimpleNamespace(
                    sleep=fake_sleep, Lock=asyncio.Lock, current_task=asyncio.current_task, Task=asyncio.Task
                ),
                'time': SimpleNamespace(monotonic=clock),
            },
        ),
        patch.object(cog, '_log_channel', AsyncMock(return_value=log_channel)),
    ):
        await cog._run_job(1, resumed=False)
    assert len(unbanned) == 3
    assert db.job['status'] == 'cancelled'  # not overwritten with completed
