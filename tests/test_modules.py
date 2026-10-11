"""Module registry, fail-closed cache, command gates, metadata and permission diagnostics."""

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import nextcord
import pytest

from src.api.app import create_app
from src.api.routes.settings import _serialize
from src.core.module_checks import command_module, module_check
from src.services.guild_modules_service import GuildModulesService
from src.services.module_diagnostics import diagnostics
from src.services.module_registry import INVITE_PERMISSIONS, MODULES, REGISTRY, serialize
from src.utils.safety import AppPermissionDenied, DatabaseUnavailableError, PermissionDenied


def test_registry_has_no_duplicate_settings_or_disabled_cogs():
    assert len(REGISTRY) == len(MODULES)
    assert not {'radio', 'quiz', 'inactivity', 'bump_reminder'} & REGISTRY.keys()
    assert all(REGISTRY[x].locked for x in ('core', 'settings', 'privacy'))
    assert all(dep in REGISTRY for m in MODULES for dep in m.requires)
    assert INVITE_PERMISSIONS & 8 == 0
    result = serialize(1, None)
    assert result['version'] == '0'
    assert all(m['enabled'] for m in result['modules'])


async def test_cache_disabled_and_dependency_enforcement(monkeypatch):
    read = AsyncMock(return_value={'disabled': ['activity', 'feeds']})
    monkeypatch.setattr('src.services.guild_modules_service.db', SimpleNamespace(fetch_one=read))
    service = GuildModulesService()
    assert not await service.enabled(1, 'feeds')
    assert not await service.enabled(1, 'leveling')
    assert not await service.enabled(1, 'activity_roles')
    assert await service.enabled(1, 'privacy')
    assert await service.enabled(1, 'leveling', dependencies=False)
    read.assert_awaited_once()
    read.return_value = None
    service.invalidate_cache(1)
    assert await service.enabled(1, 'feeds')
    assert read.await_count == 2


async def test_outage_keeps_last_known_and_unknown_fails_closed(monkeypatch):
    read = AsyncMock(return_value={'disabled': ['feeds']})
    monkeypatch.setattr('src.services.guild_modules_service.db', SimpleNamespace(fetch_one=read))
    service = GuildModulesService()
    assert not await service.enabled(1, 'feeds')
    service.invalidate_cache()
    read.side_effect = DatabaseUnavailableError('offline')
    assert not await service.enabled(1, 'feeds')
    assert await service.enabled(1, 'welcome')
    assert await service.enabled(2, 'welcome') is None
    assert await service.enabled(2, 'privacy')


async def test_disabled_commands_raise_user_facing_denial(monkeypatch):
    from src.services.guild_modules_service import guild_modules_service

    monkeypatch.setattr(guild_modules_service, 'enabled', AsyncMock(return_value=False))
    command = SimpleNamespace(name='feed', parent=None)
    assert command_module(command) == 'feeds'
    prefix = SimpleNamespace(guild=SimpleNamespace(id=1), command=command)
    with pytest.raises(PermissionDenied, match='turned off'):
        await module_check(prefix)
    slash = SimpleNamespace(guild=SimpleNamespace(id=1), application_command=command)
    with pytest.raises(AppPermissionDenied, match='turned off'):
        await module_check(slash)
    assert await module_check(SimpleNamespace(guild=None, command=command))
    monkeypatch.setattr(guild_modules_service, 'enabled', AsyncMock(return_value=None))
    with pytest.raises(DatabaseUnavailableError, match='temporarily unavailable'):
        await module_check(slash)


def test_diagnostics_enabled_only_and_channel_overwrites():
    snap = {'bot_permissions': '0', 'channels': [{'id': '99', 'bot_permissions': '1024'}]}
    result = diagnostics(snap, {'welcome_channel_id': 99}, {'massunban'})
    assert not any(d['module'] == 'massunban' for d in result)
    assert any(d['module'] == 'moderation' and 'BAN_MEMBERS' in d['missing'] for d in result)
    welcome = next(d for d in result if d['module'] == 'welcome')
    assert welcome['channel_id'] == '99'
    assert welcome['missing'] == ['SEND_MESSAGES', 'EMBED_LINKS']
    assert diagnostics({'bot_permissions': '8', 'channels': []}, {}, set()) == []


def test_settings_schema_and_zero_cooldown():
    result = _serialize({'honeypot_cooldown_seconds': 0, 'updated_at': datetime.now(UTC)})
    assert result['honeypot_cooldown_seconds'] == 0
    assert next(c for c in result['schema']['channels'] if c['key'] == 'marketplace')['types'] == [
        'text',
        'news',
        'forum',
    ]
    assert next(n for n in result['schema']['numbers'] if n['key'] == 'honeypot_cooldown_seconds')['min'] == 0
    assert all('module' in t for t in result['schema']['toggles'])
    assert 'radio' not in result['channels']
    assert isinstance(result['version'], str)


def test_every_dashboard_audit_action_is_visible():
    from src.api.routes.moderation import AUDIT_ACTIONS

    actions = set()
    root = Path(__file__).parents[1] / 'src/api/routes'
    for path in root.glob('*.py'):
        if path.name != 'moderation.py':
            actions.update(re.findall(r"['\"](dashboard_[a-z_]+)['\"]", path.read_text()))
    assert actions <= set(AUDIT_ACTIONS)


def test_real_nextcord_subcommands_are_classified():
    from src.core.app import EXTENSIONS, build_bot, load_extensions

    bot = build_bot()
    load_extensions(bot, EXTENSIONS)
    commands = {
        c.name: c for c in bot.get_all_application_commands() if isinstance(c, nextcord.SlashApplicationCommand)
    }
    assert command_module(commands['leaderboard'].children['show']) == 'leaderboards'
    assert command_module(commands['admin'].children['broadcast']) == 'notifications'
    assert command_module(commands['admin'].children['panic']) == 'moderation'
    assert command_module(commands['admin'].children['reloadcog']) is None
    assert command_module(commands['privacy'].children['delete']) == 'privacy'
    assert all(INVITE_PERMISSIONS & (1 << p) for p in (1, 2, 13, 28, 40))


async def test_disabled_automation_stops_before_work(monkeypatch, mock_bot, mock_guild, mock_user):
    from src.cogs.admin.honeypot import Honeypot
    from src.cogs.admin.welcome import Welcome
    from src.cogs.marketplace.marketplace import Marketplace
    from src.services.guild_modules_service import guild_modules_service

    enabled = AsyncMock(return_value=False)
    monkeypatch.setattr(guild_modules_service, 'enabled', enabled)
    mock_user.guild = mock_guild
    await Welcome(mock_bot).on_member_join(mock_user)
    message = MagicMock(spec=nextcord.Message)
    message.author, message.webhook_id, message.guild = mock_user, None, mock_guild
    await Honeypot(mock_bot).on_message(message)
    thread = MagicMock(spec=nextcord.Thread)
    thread.guild = mock_guild
    await Marketplace(mock_bot)._ingest_forum_thread(thread)
    assert [c.args[1] for c in enabled.await_args_list] == ['welcome', 'honeypot', 'marketplace']


async def test_module_pause_does_not_overwrite_terminal_progress(
    monkeypatch, mock_bot, mock_guild, _reset_runtime_state
):
    from src.cogs.admin.massunban import MassUnban
    from src.services.guild_modules_service import guild_modules_service
    from tests.test_massunban import JOB, _item

    _reset_runtime_state.db_available = True
    monkeypatch.setattr(guild_modules_service, 'enabled', AsyncMock(return_value=False))
    mock_bot.get_guild = MagicMock(return_value=mock_guild)
    cog = MassUnban(mock_bot)
    cog._active_jobs[1] = False
    database = SimpleNamespace(
        fetch_one=AsyncMock(return_value=JOB),
        fetch=AsyncMock(return_value=[_item(1)]),
        fetchval=AsyncMock(return_value='running'),
        execute=AsyncMock(return_value='UPDATE 0'),
    )
    progress = AsyncMock()
    process = AsyncMock()
    with (
        patch.dict(MassUnban._run_job.__globals__, {'db': database}),
        patch.object(cog, '_update_progress', progress),
        patch.object(cog, '_process_unban_item', process),
    ):
        await cog._run_job(1, resumed=False)
    process.assert_not_awaited()
    assert not any('Paused' in c.kwargs.get('note', '') for c in progress.await_args_list)
    assert 1 not in cog._active_jobs


async def test_public_meta_needs_no_auth():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url='http://test') as client:
        response = await client.get('/v1/meta')
    assert response.status_code == 200
    assert response.json() == {'invite_permissions': str(INVITE_PERMISSIONS)}
