"""Explicit operator boundaries and non-root runtime configuration."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import yaml

from src.core import app
from src.utils import logger as log_module
from src.utils import safety


@pytest.mark.parametrize('guild_id', [1088553066334273537, 42])
def test_guild_administrator_and_owner_cannot_become_bot_operator(monkeypatch, mock_interaction, guild_id):
    monkeypatch.setattr(safety, 'BOT_OPERATOR_IDS', [])
    mock_interaction.guild.id = guild_id
    mock_interaction.guild.owner_id = mock_interaction.user.id
    mock_interaction.user.guild_permissions.administrator = True
    assert not safety._bot_operator_predicate(mock_interaction)
    module = importlib.import_module('src.utils.security.rbac')
    monkeypatch.setattr(module, 'BOT_OPERATOR_IDS', [])
    assert module.rbac.get_user_role(mock_interaction) == module.Role.ADMIN


def test_explicit_operator_is_platform_operator_without_any_special_guild(monkeypatch, mock_interaction):
    monkeypatch.setattr(safety, 'BOT_OPERATOR_IDS', [mock_interaction.user.id])
    mock_interaction.guild = None
    assert safety._bot_operator_predicate(mock_interaction)
    module = importlib.import_module('src.utils.security.rbac')
    monkeypatch.setattr(module, 'BOT_OPERATOR_IDS', [mock_interaction.user.id])
    assert module.rbac.get_user_role(mock_interaction) == module.Role.FOUNDER


def test_empty_operator_allowlist_has_one_clear_startup_warning(monkeypatch, caplog):
    monkeypatch.setattr(app, 'BOT_OPERATOR_IDS', [])
    app.log_operator_configuration()
    warnings = [record.message for record in caplog.records if 'BOT_OPERATOR_IDS' in record.message]
    assert len(warnings) == 1
    assert 'empty' in warnings[0] and 'disabled' in warnings[0] and 'deployment' in warnings[0]


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
