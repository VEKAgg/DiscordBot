"""D11: all enrollment paths fail closed on unsafe role collisions, at assignment time."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest

from src.cogs import mentorship as module
from src.services.networking_service import NetworkingService


def _role(name='Mentor'):
    role = MagicMock(spec=nextcord.Role)
    role.name = name
    role.managed = False
    role.is_default.return_value = False
    role.permissions = nextcord.Permissions.none()
    role.__ge__.return_value = False
    return role


@pytest.mark.parametrize(
    'problem',
    [
        'administrator',
        'manage_guild',
        'manage_roles',
        'manage_channels',
        'ban_members',
        'kick_members',
        'moderate_members',
        'managed',
        'default',
        'hierarchy',
        'missing_bot',
    ],
)
async def test_live_enrollment_check_refuses_unsafe_roles(problem, mock_bot, mock_guild, mock_user):
    role = _role()
    mock_guild.roles = [role]
    mock_guild.me = SimpleNamespace(top_role=object())
    mock_user.add_roles = AsyncMock()
    if problem == 'managed':
        role.managed = True
    elif problem == 'default':
        role.is_default.return_value = True
    elif problem == 'hierarchy':
        role.__ge__.return_value = True
    elif problem == 'missing_bot':
        mock_guild.me = None
    else:
        setattr(role.permissions, problem, True)
    assigned, message = await module.Mentorship(mock_bot)._assign_registration_role(mock_guild, mock_user, 'Mentor')
    assert not assigned and 'skipped' in message.lower()
    mock_user.add_roles.assert_not_awaited()


async def test_new_role_created_with_zero_permissions_and_checked_before_assignment(mock_bot, mock_guild, mock_user):
    role = _role()
    mock_guild.roles = []
    mock_guild.me = SimpleNamespace(top_role=object())
    mock_guild.create_role = AsyncMock(return_value=role)
    mock_user.add_roles = AsyncMock()
    assigned, _ = await module.Mentorship(mock_bot)._assign_registration_role(mock_guild, mock_user, 'Mentor')
    assert assigned
    assert mock_guild.create_role.call_args.kwargs['permissions'].value == 0
    mock_user.add_roles.assert_awaited_once_with(role, reason='Mentorship registration')


async def test_previously_safe_role_is_refused_after_permissions_change(mock_bot, mock_guild, mock_user):
    role = _role()
    mock_guild.roles = [role]
    mock_guild.me = SimpleNamespace(top_role=object())
    mock_user.add_roles = AsyncMock()
    cog = module.Mentorship(mock_bot)
    assert (await cog._assign_registration_role(mock_guild, mock_user, 'Mentor'))[0]
    mock_user.add_roles.reset_mock()
    role.permissions.administrator = True
    assert not (await cog._assign_registration_role(mock_guild, mock_user, 'Mentor'))[0]
    mock_user.add_roles.assert_not_awaited()


@pytest.mark.parametrize('path', ['slash', 'prefix', 'apply'])
async def test_enrollment_paths_use_guard_and_report_skipped_role(
    path, monkeypatch, mock_bot, mock_interaction, mock_context
):
    role = _role()
    role.permissions.administrator = True
    guild = mock_interaction.guild
    guild.roles = [role]
    guild.me = SimpleNamespace(top_role=object())
    mock_context.guild = guild
    mock_context.author = mock_interaction.user
    mock_interaction.user.add_roles = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(module, 'safe_send', send)
    cog = module.Mentorship(mock_bot)
    monkeypatch.setattr(cog, '_defer', AsyncMock())
    registration = AsyncMock(return_value={'available': True})
    monkeypatch.setattr(cog.mentorship_service, 'register_mentor', registration)
    write_profile = AsyncMock()
    monkeypatch.setattr(NetworkingService, 'upsert_profile', write_profile)
    if path == 'slash':
        callback = cast(Any, cog.mentor_register_slash.callback).__wrapped__
        await callback(cog, mock_interaction, 'mentor')
    elif path == 'prefix':
        callback = cast(Any, cog.mentor_register_prefix.callback).__wrapped__
        await callback(cog, mock_context, 'mentor')
    else:
        callback = cast(Any, cog.mentor_apply.callback).__wrapped__
        await callback(cog, mock_interaction, 'Python', 'Bio')
    registration.assert_awaited_once()  # role denial never suppresses canonical opt-in
    write_profile.assert_not_awaited()  # D13 enrollment cannot overwrite networking metadata
    mock_interaction.user.add_roles.assert_not_awaited()
    embed = send.call_args.kwargs['embed']
    assert 'skipped' in (embed.title + embed.description).lower()
