"""Explicit operator boundaries and non-root runtime configuration."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from src.services.operators import OperatorRegistry, operators
from src.utils import logger as log_module
from src.utils import safety


def _set_operators(monkeypatch, ids):
    """Point the shared registry at an explicit operator set for one test."""
    monkeypatch.setattr(operators, '_operators', frozenset(ids))


@pytest.mark.parametrize('guild_id', [1088553066334273537, 42])
def test_guild_administrator_and_owner_cannot_become_bot_operator(monkeypatch, mock_interaction, guild_id):
    _set_operators(monkeypatch, [])
    mock_interaction.guild.id = guild_id
    mock_interaction.guild.owner_id = mock_interaction.user.id
    mock_interaction.user.guild_permissions.administrator = True
    assert not safety._bot_operator_predicate(mock_interaction)
    module = importlib.import_module('src.utils.security.rbac')
    assert module.rbac.get_user_role(mock_interaction) == module.Role.ADMIN


async def test_explicit_operator_is_platform_operator_without_any_special_guild(monkeypatch, mock_interaction):
    _set_operators(monkeypatch, [mock_interaction.user.id])
    mock_interaction.guild = None
    assert safety._bot_operator_predicate(mock_interaction)
    module = importlib.import_module('src.utils.security.rbac')
    assert await module.rbac.get_user_role_async(mock_interaction) == module.Role.OPERATOR


async def test_empty_operator_set_warns_once_and_stays_disabled(caplog):
    """First failed refresh with an empty set ⇒ operators disabled, exactly one warning."""
    registry = OperatorRegistry()
    failing = SimpleNamespace(http=SimpleNamespace(application_info=AsyncMock(side_effect=RuntimeError('down'))))
    registry.bind(failing)  # type: ignore[arg-type]
    assert await registry.refresh() is False
    assert await registry.refresh() is False
    warnings = [r.message for r in caplog.records if r.levelname == 'WARNING' and 'disabled' in r.message]
    assert len(warnings) == 1
    assert 'Developer Portal' in warnings[0]
    assert registry.ids == frozenset() and not registry.is_operator(1)


@pytest.mark.parametrize('compose_name', ['docker-compose.yml', 'docker-compose.dev.yml'])
def test_runtime_uses_environment_injection_not_secret_or_writable_log_binds(compose_name):
    compose = yaml.safe_load(Path(compose_name).read_text())
    for name in ('discord-bot', 'api'):
        service = compose['services'][name]
        assert service['env_file'] == ['.env']
        assert service['read_only'] is True
        assert service['cap_drop'] == ['ALL']
        assert service['security_opt'] == ['no-new-privileges:true']
        assert '/tmp:size=32m,noexec,nosuid,nodev' in service['tmpfs']
        assert not any('/app/.env' in volume or '/app/logs' in volume for volume in service.get('volumes', []))
    assert 'USER 10001:10001' in Path('Dockerfile').read_text()


def test_stdout_logging_creates_no_directory_or_file(monkeypatch):
    monkeypatch.setenv('VEKA_LOG_TO_FILE', '0')
    root = MagicMock()
    root.handlers = []
    monkeypatch.setattr(log_module.logging, 'getLogger', lambda *_args: root)
    mkdir = MagicMock()
    file_handler = MagicMock()
    monkeypatch.setattr(log_module.os, 'makedirs', mkdir)
    monkeypatch.setattr(log_module, 'RotatingFileHandler', file_handler)
    log_module.setup_logging('INFO')
    mkdir.assert_not_called()
    file_handler.assert_not_called()
    assert root.addHandler.call_count == 1


async def test_info_rejects_member_from_another_guild(monkeypatch, mock_bot, mock_interaction):
    from unittest.mock import AsyncMock

    info = importlib.import_module('src.cogs.external.info')

    # Extension unload/reload can leave a stale package attribute; patch the actual module.
    sender = AsyncMock()
    monkeypatch.setattr(info, 'safe_send', sender)
    callback = cast(Any, info.ExternalInfo.memberinfo.callback).__wrapped__
    await callback(info.ExternalInfo(mock_bot), mock_interaction, SimpleNamespace(guild=SimpleNamespace(id=99)))
    assert sender.call_args.kwargs['ephemeral'] is True
    assert sender.call_args.kwargs['content'] == 'Member not found in this server.'
