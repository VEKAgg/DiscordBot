"""Tests for src/utils/safety.py — safe wrappers, degraded mode, admin checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import nextcord
from nextcord.ext import commands

from src.core.runtime_state import runtime_state
from src.utils.safety import (
    DatabaseUnavailableError,
    ExternalRequestError,
    ValidationError,
    _is_admin_user,
    format_context,
    map_exception_to_message,
    safe_command,
    safe_send,
    safe_slash_command,
)

# ============================================================
# map_exception_to_message
# ============================================================


class TestMapExceptionToMessage:
    def test_database_unavailable(self):
        msg = map_exception_to_message(DatabaseUnavailableError('down'))
        assert 'database' in msg.lower()

    def test_validation_error(self):
        msg = map_exception_to_message(ValidationError('bad input'))
        assert 'Invalid input' in msg

    def test_external_request_error(self):
        msg = map_exception_to_message(ExternalRequestError('timeout'))
        assert 'external service' in msg.lower()

    def test_command_not_found(self):
        msg = map_exception_to_message(commands.CommandNotFound('test'))
        assert 'not found' in msg.lower()

    def test_missing_permissions(self):
        msg = map_exception_to_message(commands.MissingPermissions(missing_permissions=['admin']))
        assert 'permission' in msg.lower()

    def test_command_on_cooldown(self):
        from nextcord.ext.commands import Cooldown

        cooldown = Cooldown(65.0, 1.0)
        err = commands.CommandOnCooldown(cooldown, 65.0, commands.BucketType.default)
        msg = map_exception_to_message(err)
        assert '1m 5s' in msg

    def test_generic_exception(self):
        msg = map_exception_to_message(RuntimeError('something'))
        assert 'unexpected error' in msg.lower()


# ============================================================
# format_context
# ============================================================


class TestFormatContext:
    def test_with_context(self, mock_context):
        result = format_context(mock_context)
        assert 'command=' in result
        assert 'user_id=' in result

    def test_with_interaction(self, mock_interaction):
        result = format_context(mock_interaction)
        assert 'command=' in result
        assert 'user_id=' in result

    def test_with_string(self):
        result = format_context('fallback')
        assert result == 'fallback'


# ============================================================
# _is_admin_user
# ============================================================


class TestIsAdminUser:
    def test_none_user(self):
        assert _is_admin_user(None) is False

    def test_owner_id(self, mock_user):
        mock_user.id = 941009204045557842  # OWNER_DISCORD_ID
        # OWNER_IDS is loaded from .env; OWNER_DISCORD_ID may not be in it.
        # Instead, test with a known admin from ADMIN_IDS or patch it.
        with patch('src.utils.safety.ADMIN_IDS', [941009204045557842]):
            assert _is_admin_user(mock_user) is True

    def test_admin_permission(self, admin_member):
        assert _is_admin_user(admin_member) is True

    def test_regular_user(self, mock_member):
        assert _is_admin_user(mock_member) is False


# ============================================================
# safe_send
# ============================================================


class TestSafeSend:
    async def test_context_send(self, mock_context):
        await safe_send(mock_context, content='hello')
        mock_context.send.assert_awaited_once_with(content='hello', embed=None)

    async def test_interaction_not_done(self, mock_interaction):
        mock_interaction.response.is_done.return_value = False
        await safe_send(mock_interaction, content='hello')
        mock_interaction.response.send_message.assert_awaited_once()

    async def test_interaction_done_followup(self, mock_interaction):
        mock_interaction.response.is_done.return_value = True
        await safe_send(mock_interaction, content='hello')
        mock_interaction.followup.send.assert_awaited_once()


# ============================================================
# safe_command — degraded mode
# ============================================================


class TestSafeCommand:
    async def test_db_unavailable_aborts(self, mock_context):
        runtime_state.db_available = False

        @safe_command(requires_db=True)
        async def my_cmd(self, ctx):  # noqa: ARG001
            raise AssertionError('Should not execute')

        # Create a mock cog instance
        cog = MagicMock()
        await my_cmd(cog, mock_context)
        mock_context.send.assert_awaited()

    async def test_db_available_executes(self, mock_context):
        runtime_state.db_available = True
        called = False

        @safe_command(requires_db=True)
        async def my_cmd(self, ctx):  # noqa: ARG001
            nonlocal called
            called = True

        cog = MagicMock()
        await my_cmd(cog, mock_context)
        assert called

    async def test_exception_sends_error_embed(self, mock_context):
        runtime_state.db_available = True

        @safe_command(requires_db=False)
        async def my_cmd(self, ctx):  # noqa: ARG001
            raise RuntimeError('boom')

        cog = MagicMock()
        await my_cmd(cog, mock_context)
        mock_context.send.assert_awaited()
        # The embed should be an error embed
        call_kwargs = mock_context.send.call_args
        embed = call_kwargs.kwargs.get('embed') or call_kwargs[1].get('embed')
        assert embed.color == nextcord.Color.red()


# ============================================================
# safe_slash_command — degraded mode
# ============================================================


class TestSafeSlashCommand:
    async def test_db_unavailable_aborts(self, mock_interaction):
        runtime_state.db_available = False

        @safe_slash_command(requires_db=True)
        async def my_cmd(self, interaction):  # noqa: ARG001
            raise AssertionError('Should not execute')

        cog = MagicMock()
        await my_cmd(cog, mock_interaction)
        mock_interaction.response.send_message.assert_awaited()

    async def test_db_available_executes(self, mock_interaction):
        runtime_state.db_available = True
        called = False

        @safe_slash_command(requires_db=True)
        async def my_cmd(self, interaction):  # noqa: ARG001
            nonlocal called
            called = True

        cog = MagicMock()
        await my_cmd(cog, mock_interaction)
        assert called
