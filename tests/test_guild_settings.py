"""Tests for src/services/guild_settings_service.py — cache, defaults, invalidation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.guild_settings_service import (
    GuildSettings,
    GuildSettingsService,
)


@pytest.fixture
def service():
    """Fresh GuildSettingsService with empty cache."""
    return GuildSettingsService()


class TestGuildSettingsDataclass:
    def test_defaults(self):
        settings = GuildSettings(guild_id=1)
        assert settings.log_channel_id is None
        assert settings.warn_mute_threshold == 3
        assert settings.warn_ban_threshold == 5
        assert settings.honeypot_cooldown_seconds == 60
        assert settings.welcome_message_template == 'Welcome {user} to {server}!'
        assert settings.welcome_card_enabled is True
        assert settings.honeypot_channel_ids == []

    def test_get_resolved_returns_set_value(self):
        settings = GuildSettings(guild_id=1, log_channel_id=123)
        assert settings.get_resolved('log_channel_id') == 123

    @patch('src.services.guild_settings_service._load_defaults', return_value={'log_channel_id': 999})
    def test_get_resolved_falls_back_to_config(self, _mock_defaults):
        settings = GuildSettings(guild_id=1, log_channel_id=None)
        assert settings.get_resolved('log_channel_id') == 999

    def test_get_resolved_unknown_field(self):
        settings = GuildSettings(guild_id=1)
        assert settings.get_resolved('nonexistent_field') is None


class TestGuildSettingsServiceCache:
    async def test_cache_hit_skips_db(self, service):
        """Second call returns cached value without hitting DB."""
        service._cache[42] = GuildSettings(guild_id=42, log_channel_id=111)
        result = await service.get_settings(42)
        assert result.log_channel_id == 111
        assert result.guild_id == 42

    async def test_cache_miss_queries_db(self, service):
        """Cache miss queries DB and caches the result."""
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda _self, key: {
            'guild_id': 55,
            'log_channel_id': 222,
            'staff_channel_id': None,
            'alert_channel_id': None,
            'public_commands_channel_id': None,
            'welcome_channel_id': None,
            'radio_channel_id': None,
            'leaderboard_channel_id': None,
            'muted_role_id': None,
            'honeypot_channel_ids': [],
            'warn_mute_threshold': 3,
            'warn_ban_threshold': 5,
            'honeypot_cooldown_seconds': 60,
            'welcome_message_template': 'Welcome {user} to {server}!',
            'welcome_card_enabled': True,
            'created_at': None,
            'updated_at': None,
        }.get(key)

        with patch('src.services.guild_settings_service.db') as mock_db:
            mock_db.fetch_one = AsyncMock(return_value=mock_row)
            result = await service.get_settings(55)

        assert result.log_channel_id == 222
        assert 55 in service._cache

    async def test_no_row_inserts_defaults(self, service):
        """When DB returns None, inserts default row and caches."""
        with patch('src.services.guild_settings_service.db') as mock_db:
            mock_db.fetch_one = AsyncMock(return_value=None)
            mock_db.execute = AsyncMock()
            result = await service.get_settings(77)

        assert result.guild_id == 77
        assert result.log_channel_id is None
        mock_db.execute.assert_awaited_once()

    async def test_invalidate_single_guild(self, service):
        service._cache[1] = GuildSettings(guild_id=1)
        service._cache[2] = GuildSettings(guild_id=2)
        service.invalidate_cache(guild_id=1)
        assert 1 not in service._cache
        assert 2 in service._cache

    async def test_invalidate_all(self, service):
        service._cache[1] = GuildSettings(guild_id=1)
        service._cache[2] = GuildSettings(guild_id=2)
        service.invalidate_cache()
        assert len(service._cache) == 0

    async def test_update_settings_invalidates_and_refetches(self, service):
        service._cache[10] = GuildSettings(guild_id=10, log_channel_id=100)

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda _self, key: {
            'guild_id': 10,
            'log_channel_id': 200,
            'staff_channel_id': None,
            'alert_channel_id': None,
            'public_commands_channel_id': None,
            'welcome_channel_id': None,
            'radio_channel_id': None,
            'leaderboard_channel_id': None,
            'muted_role_id': None,
            'honeypot_channel_ids': [],
            'warn_mute_threshold': 3,
            'warn_ban_threshold': 5,
            'honeypot_cooldown_seconds': 60,
            'welcome_message_template': 'Welcome {user} to {server}!',
            'welcome_card_enabled': True,
            'created_at': None,
            'updated_at': None,
        }.get(key)

        with patch('src.services.guild_settings_service.db') as mock_db:
            mock_db.execute = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value=mock_row)
            result = await service.update_settings(10, log_channel_id=200)

        assert result.log_channel_id == 200
        assert service._cache[10].log_channel_id == 200
