"""Regression tests for slash-command authorization (audit C-01).

nextcord ignores ``commands.check`` on application commands, so every privileged slash
command must be guarded through ``permission_guard`` (``admin_only``/``staff_only``/guild gates).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest
from nextcord.ext import commands

from src.core.app import EXTENSIONS, build_bot
from src.utils.safety import PermissionDenied, admin_only, staff_only

# Fully-qualified slash command names that must never run for a regular member.
PRIVILEGED_SLASH_COMMANDS = {
    'massunban run',
    'massunban preview',
    'massunban status',
    'massunban cancel',
    'massunban recent',
    'admin reloadcog',
    'admin featurestatus',
    'admin startupchecks',
    'admin detailedstatus',
    'radio station',
    'radio start',
    'radio stop',
    'radio move',
    'setupleaderboard',
    'exportchat',
    'feed add',
    'feed remove',
    'feed test',
}


def _walk(cmd, prefix=''):
    name = f'{prefix} {cmd.name}'.strip()
    children = getattr(cmd, 'children', None) or {}
    if not children:
        yield name, cmd
    for child in children.values():
        yield from _walk(child, name)


def _is_guarded(cmd) -> bool:
    return bool(cmd.checks) or bool(getattr(cmd.callback, '__veka_guards__', None))


@pytest.fixture(scope='module')
def loaded_bot():
    bot = build_bot()
    for ext in EXTENSIONS:
        bot.load_extension(ext)
    yield bot
    for ext in EXTENSIONS:
        try:
            bot.unload_extension(ext)
        except Exception:
            pass


def test_privileged_slash_commands_are_guarded(loaded_bot):
    found = {}
    for top in loaded_bot.get_all_application_commands():
        for name, leaf in _walk(top):
            found[name] = leaf

    missing = PRIVILEGED_SLASH_COMMANDS - found.keys()
    assert not missing, f'privileged commands not registered: {sorted(missing)}'

    unguarded = sorted(name for name in PRIVILEGED_SLASH_COMMANDS if not _is_guarded(found[name]))
    assert not unguarded, f'privileged slash commands without a permission guard: {unguarded}'


class _FakeCog:
    def __init__(self):
        self.ran = False


async def test_admin_only_blocks_slash_for_regular_member(mock_interaction):
    @admin_only()
    async def body(self, _interaction):
        self.ran = True

    cog = _FakeCog()
    await body(cog, mock_interaction)

    assert cog.ran is False
    mock_interaction.response.send_message.assert_awaited_once()
    assert mock_interaction.response.send_message.call_args.kwargs['ephemeral'] is True


async def test_admin_only_allows_slash_for_admin(mock_interaction, admin_member):
    mock_interaction.user = admin_member

    @admin_only()
    async def body(self, _interaction):
        self.ran = True

    cog = _FakeCog()
    await body(cog, mock_interaction)
    assert cog.ran is True


async def test_staff_only_blocks_slash_for_regular_member(mock_interaction):
    mock_interaction.guild.owner_id = 0

    @staff_only()
    async def body(self, _interaction):
        self.ran = True

    cog = _FakeCog()
    await body(cog, mock_interaction)
    assert cog.ran is False


async def test_admin_only_on_prefix_command_raises_check_failure(mock_context):
    @commands.command(name='dangerous')
    @admin_only()
    async def dangerous(self, ctx):
        pass

    assert dangerous.checks, 'prefix command should carry a commands.check'
    check: Any = dangerous.checks[0]  # nextcord types permit both sync and async predicates
    with pytest.raises(PermissionDenied):
        await check(mock_context)


async def test_guard_on_application_command_object_uses_app_checks():
    async def cb(interaction):
        pass

    cmd = nextcord.slash_command(name='x', description='x')(cb)
    before = len(cmd.modify_callbacks)
    assert admin_only()(cmd) is cmd
    assert len(cmd.modify_callbacks) == before + 1
    for modify in cmd.modify_callbacks[before:]:
        modify(cmd)
    assert cmd.checks, 'decorating an application command should append an application check'


def test_guard_preserves_signature_for_slash_options():
    import inspect

    @admin_only()
    async def body(self, interaction: nextcord.Interaction, channel: nextcord.TextChannel):
        pass

    assert list(inspect.signature(body).parameters) == ['self', 'interaction', 'channel']
    assert isinstance(body, AsyncMock) is False


async def test_radiostation_prefix_blocks_admins_of_external_guilds(loaded_bot, mock_context, admin_member):
    """`!radiostation` changes the single shared radio, so it needs the same guild gate as `/radio station`."""
    cmd = loaded_bot.get_command('radiostation')
    external_guild = MagicMock(spec=nextcord.Guild)
    external_guild.id = 42  # not MAIN_GUILD_ID
    mock_context.author = admin_member
    mock_context.guild = external_guild

    with pytest.raises(PermissionDenied):
        for check in cmd.checks:
            await check(mock_context)


async def test_connect_picker_rejects_other_members(mock_guild, mock_interaction):
    """The `!connect` picker is posted publicly; nobody but the invoker may send requests through it."""
    from src.cogs.networking.networking import ConnectionRequestView

    svc = MagicMock()
    svc.create_request = AsyncMock()
    view = ConnectionRequestView(mock_guild, requester_id='555', message='', svc=svc)

    mock_interaction.user.id = 123456789  # someone else
    assert await view.interaction_check(mock_interaction) is False
    mock_interaction.response.send_message.assert_awaited_once()
    svc.create_request.assert_not_awaited()

    mock_interaction.user.id = 555
    assert await view.interaction_check(mock_interaction) is True
