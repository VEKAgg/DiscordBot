"""Activity tracking accuracy (Phase 3): voice rules, sampling, XP caps, opt-in, command events."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import nextcord
import pytest

from src.cogs.rpg.rpg_manager import XP_SESSION_CAP_MINUTES, RPGManager
from src.utils.ttlcache import TTLDict

GUILD_ID = 10


def _activity(kind, name=None, url=None):
    return SimpleNamespace(type=kind, name=name, url=url)


def _member(uid, *, channel=None, self_deaf=False, deaf=False, activities=(), roles=()):
    m = MagicMock()
    m.id = uid
    m.bot = False
    m.roles = list(roles)
    m.activities = list(activities)
    m.voice = SimpleNamespace(channel=channel, self_deaf=self_deaf, deaf=deaf) if channel else None
    return m


def _guild(voice_channels=(), afk=None, members=()):
    g = MagicMock()
    g.id = GUILD_ID
    g.voice_channels = list(voice_channels)
    g.stage_channels = []
    g.afk_channel = afk
    by_id = {m.id: m for m in members}
    g.members = list(members)
    g.get_member = lambda uid: by_id.get(uid)
    for m in members:
        m.guild = g
    return g


def _channel(cid, members):
    ch = SimpleNamespace(id=cid, members=members)
    return ch


def _cog(guilds):
    bot = MagicMock()
    bot.guilds = guilds
    return RPGManager(bot)


# ---------------------------------------------------------------- voice rules


def test_voice_rules_afk_deaf_and_alone():
    a, b, c, d = _member(1), _member(2), _member(3), _member(4)
    talk = _channel(100, [a, b, c])
    afk = _channel(200, [d])
    for m in (a, b):
        m.voice = SimpleNamespace(channel=talk, self_deaf=False, deaf=False)
    c.voice = SimpleNamespace(channel=talk, self_deaf=True, deaf=False)
    d.voice = SimpleNamespace(channel=afk, self_deaf=False, deaf=False)
    guild = _guild([talk, afk], afk=afk, members=[a, b, c, d])
    _ = guild

    assert RPGManager.voice_eligibility(a) == (True, True)  # with company: minutes + XP
    assert RPGManager.voice_eligibility(c) == (False, False)  # deafened: nothing
    assert RPGManager.voice_eligibility(d) == (False, False)  # AFK channel: nothing

    alone = _member(5)
    solo = _channel(300, [alone])
    alone.voice = SimpleNamespace(channel=solo, self_deaf=False, deaf=False)
    _guild([solo], members=[alone])
    assert RPGManager.voice_eligibility(alone) == (True, False)  # alone: minutes, no XP


def test_deafened_member_is_not_company():
    hearing, deafened = _member(1), _member(2)
    ch = _channel(100, [hearing, deafened])
    hearing.voice = SimpleNamespace(channel=ch, self_deaf=False, deaf=False)
    deafened.voice = SimpleNamespace(channel=ch, self_deaf=True, deaf=False)
    _guild([ch], members=[hearing, deafened])
    assert RPGManager.voice_eligibility(hearing) == (True, False)


def test_tick_picks_up_members_already_in_voice_without_join_events():
    """Restart safety: sampling reads gateway state, so members in voice at startup are counted."""
    a, b = _member(1), _member(2)
    ch = _channel(100, [a, b])
    for m in (a, b):
        m.voice = SimpleNamespace(channel=ch, self_deaf=False, deaf=False)
    cog = _cog([_guild([ch], members=[a, b])])

    awards, _ = cog.collect_tick(1)

    assert sorted(x.user_id for x in awards['voice']) == [1, 2]
    assert all(x.quantity == 1 and x.xp_base == 1 for x in awards['voice'])


def test_long_voice_session_records_real_minutes_but_caps_xp():
    a, b = _member(1), _member(2)
    ch = _channel(100, [a, b])
    for m in (a, b):
        m.voice = SimpleNamespace(channel=ch, self_deaf=False, deaf=False)
    cog = _cog([_guild([ch], members=[a, b])])

    minutes = xp = 0
    for _ in range(180):  # a 3-hour call, one tick per minute
        awards, _ = cog.collect_tick(1)
        award = next(x for x in awards['voice'] if x.user_id == 1)
        minutes += award.quantity
        xp += award.xp_base
    assert minutes == 180
    assert xp == XP_SESSION_CAP_MINUTES


def test_xp_cap_resets_after_leaving():
    a, b = _member(1), _member(2)
    ch = _channel(100, [a, b])
    for m in (a, b):
        m.voice = SimpleNamespace(channel=ch, self_deaf=False, deaf=False)
    guild = _guild([ch], members=[a, b])
    cog = _cog([guild])
    for _ in range(70):
        cog.collect_tick(1)
    ch.members = []  # everyone left
    cog.collect_tick(1)
    ch.members = [a, b]
    awards, _ = cog.collect_tick(1)
    assert next(x for x in awards['voice'] if x.user_id == 1).xp_base == 1


# ---------------------------------------------------------------- presence


def _presence_member(uid):
    return _member(
        uid,
        activities=[
            _activity(nextcord.ActivityType.playing, 'Valorant'),
            _activity(nextcord.ActivityType.playing, 'Visual Studio Code'),
            _activity(nextcord.ActivityType.listening, 'Spotify'),
        ],
    )


def test_presence_needs_server_opt_in_and_respects_member_opt_out():
    opted, other = _presence_member(1), _presence_member(2)
    cog = _cog([_guild(members=[opted, other])])
    cog._consent = {2: (False, None)}  # member 2 opted out; member 1 never chose (allowed)

    off_awards, off_details = cog.collect_tick(2)  # server hasn't enabled tracking
    assert not off_awards['gaming'] and not off_details

    awards, details = cog.collect_tick(2, tracking_guilds={GUILD_ID})

    assert [x.user_id for x in awards['gaming']] == [1]
    assert [x.user_id for x in awards['coding']] == [1]
    assert awards['gaming'][0].quantity == 2  # counted once, not twice
    assert {d[1] for d in details} == {'game', 'coding'}  # no listening/Spotify
    assert ('Valorant' in {d[2] for d in details}) and all(d[0] == 1 for d in details)
    assert all(d[5] == GUILD_ID for d in details)  # credited to the enabled server


def test_coding_app_is_not_counted_as_gaming():
    snap = RPGManager.presence_snapshot(_presence_member(1))
    assert snap['gaming'] == {'Valorant'}
    assert snap['coding'] == {'Visual Studio Code'}
    assert 'listening' not in snap


def test_streaming_is_tracked():
    m = _member(
        1,
        activities=[
            _activity(nextcord.ActivityType.streaming, 'Live', url='https://twitch.tv/x'),
            _activity(nextcord.ActivityType.playing, 'Valorant'),
        ],
    )
    snap = RPGManager.presence_snapshot(m)
    assert snap['streaming'] == {'Valorant'} and snap['gaming'] == {'Valorant'}


def test_opt_out_clears_presence_sessions():
    cog = _cog([])
    assert cog.is_opted_in(1)  # default allowed
    cog._consecutive = {(1, 'gaming'): 30, (1, 'voice'): 10}
    cog.set_opt_in(1, False)
    assert not cog.is_opted_in(1)
    assert (1, 'gaming') not in cog._consecutive and (1, 'voice') in cog._consecutive


# ---------------------------------------------------------------- messages / commands


async def test_message_cooldown_counts_two_of_six_messages():
    """Acceptance: 5 messages within 10 s, then 1 after 15 s → total_messages +2."""
    cog = _cog([])
    clock = SimpleNamespace(t=0.0)
    cog._message_cooldowns = TTLDict(ttl=10, maxsize=100, clock=lambda: clock.t)
    award = AsyncMock()
    guild = SimpleNamespace(id=GUILD_ID, get_member=lambda _uid: None)
    author = SimpleNamespace(id=1, bot=False)
    with patch.object(RPGManager, '_award_event', award):
        for t in (0, 2, 4, 6, 8):
            clock.t = t
            await cog.on_message(SimpleNamespace(author=author, guild=guild))
        clock.t = 23
        await cog.on_message(SimpleNamespace(author=author, guild=guild))
    assert award.await_count == 2


def test_command_xp_listens_to_events_nextcord_actually_dispatches():
    listeners = {name for name, _ in _cog([]).get_listeners()}
    assert 'on_application_command_completion' in listeners
    assert 'on_command_completion' in listeners
    assert 'on_application_command' not in listeners  # never dispatched by nextcord


async def test_slash_command_awards_command_metric():
    cog = _cog([])
    award = AsyncMock()
    interaction = SimpleNamespace(guild=SimpleNamespace(id=GUILD_ID), user=SimpleNamespace(id=1, bot=False))
    with patch.object(RPGManager, '_award_event', award):
        await cog.on_application_command_completion(interaction)
    assert award.await_args.args[0] == 'command'


@pytest.mark.parametrize('elapsed,expected', [(59, 0), (60, 1), (150, 2), (3600, 5)])
def test_tick_minutes_carry_fractions_and_cap_gaps(elapsed, expected):
    cog = _cog([])
    now = [1000.0]
    fake_time = SimpleNamespace(monotonic=lambda: now[0])
    # Patch the globals the method was defined with: test_cog_loading may have reloaded the module.
    with patch.dict(RPGManager._take_minutes.__globals__, {'time': fake_time}):
        assert cog._take_minutes() == 0  # first tick: nothing observed yet
        now[0] += elapsed
        assert cog._take_minutes() == expected


async def test_activity_roles_use_this_servers_xp_and_skip_unsafe_roles():
    from datetime import UTC, datetime

    import nextcord as nc

    from src.cogs.rpg.rpg_manager import _ACTIVITY_ROLE_NAMES, _ACTIVITY_ROLE_THRESHOLDS

    low_key, low_threshold = _ACTIVITY_ROLE_THRESHOLDS[0]
    top_key, _ = _ACTIVITY_ROLE_THRESHOLDS[-1]

    class Role:
        def __init__(self, rid, name, perms=0, pos=1):
            self.id, self.name, self.position = rid, name, pos
            self.permissions = nc.Permissions(perms)
            self.managed = False
            self.members: list = []

        def is_default(self):
            return False

        def __ge__(self, other):
            return self.position >= other.position

    safe = Role(1, _ACTIVITY_ROLE_NAMES[low_key])
    unsafe = Role(2, _ACTIVITY_ROLE_NAMES[top_key], perms=nc.Permissions(administrator=True).value)
    member = MagicMock()
    member.id, member.bot, member.roles = 5, False, []
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    guild = MagicMock()
    guild.id = GUILD_ID
    guild.roles = [safe, unsafe]
    guild.me = SimpleNamespace(top_role=Role(9, 'bot', pos=10))
    guild.get_member = lambda uid: member if uid == 5 else None
    rows = [{'user_id': 5, 'xp': 10**9, 'last_day': datetime.now(UTC).date()}]  # enough XP for any role
    cog = _cog([guild])
    with patch.dict(
        RPGManager._evaluate_guild_activity_roles.__globals__,
        {'db': SimpleNamespace(fetch=AsyncMock(return_value=rows))},
    ):
        await cog._evaluate_guild_activity_roles(guild)
    # Highest *safe* role is used; the admin-capable one is never handed out.
    member.add_roles.assert_awaited_once()
    assert member.add_roles.await_args.args[0] is safe
    assert low_threshold >= 0
