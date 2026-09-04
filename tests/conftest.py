"""Shared test fixtures for VEKA Bot test suite."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest
from nextcord.ext import commands

from src.core.runtime_state import RuntimeState, runtime_state


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    """Reset runtime_state before each test to avoid cross-test contamination."""
    original = RuntimeState()
    runtime_state.db_available = original.db_available
    runtime_state.loaded_cogs = original.loaded_cogs.copy()
    runtime_state.failed_cogs = original.failed_cogs.copy()
    runtime_state.degraded_features = original.degraded_features.copy()
    runtime_state.startup_check_results = original.startup_check_results.copy()
    runtime_state.last_db_error = original.last_db_error
    runtime_state.last_recovery_time = original.last_recovery_time
    runtime_state.alert_state_cache = original.alert_state_cache.copy()
    yield runtime_state


@pytest.fixture
def mock_db():
    """Async mock simulating the Database singleton."""
    db = AsyncMock()
    db.pool = MagicMock()
    db.fetch = AsyncMock(return_value=[])
    db.fetch_one = AsyncMock(return_value=None)
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value='INSERT 0 1')
    db.execute_many = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.ping = AsyncMock(return_value=True)
    db.reconnect = AsyncMock()
    db.run_migrations = AsyncMock()
    return db


@pytest.fixture
def mock_bot():
    """Headless Bot instance with runtime_state attached."""
    intents = nextcord.Intents.default()
    bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
    bot.runtime_state = runtime_state  # type: ignore[attr-defined]
    bot.notifier = None  # type: ignore[attr-defined]
    return bot


@pytest.fixture
def mock_guild():
    """Mocked nextcord.Guild."""
    guild = MagicMock(spec=nextcord.Guild)
    guild.id = 1088553066334273537
    guild.name = 'VEKA Test Server'
    guild.owner_id = 941009204045557842
    guild.get_channel = MagicMock(return_value=MagicMock(spec=nextcord.TextChannel))
    return guild


@pytest.fixture
def mock_user():
    """Mocked nextcord.Member with standard attributes."""
    user = MagicMock(spec=nextcord.Member)
    user.id = 123456789
    user.name = 'TestUser'
    user.discriminator = '0001'
    user.display_name = 'TestUser'
    user.bot = False
    user.guild_permissions = MagicMock(spec=nextcord.Permissions)
    user.guild_permissions.administrator = False
    user.roles = []
    user.joined_at = datetime.now(UTC)
    user.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    user.avatar = None
    return user


@pytest.fixture
def mock_interaction(mock_user, mock_guild):
    """Mocked nextcord.Interaction with response and followup."""
    interaction = AsyncMock(spec=nextcord.Interaction)
    interaction.user = mock_user
    interaction.guild = mock_guild
    interaction.channel = MagicMock(spec=nextcord.TextChannel)
    interaction.channel.id = 999
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.data = {}
    interaction.application_command = MagicMock()
    interaction.application_command.name = 'test_command'
    return interaction


@pytest.fixture
def mock_context(mock_user, mock_guild):
    """Mocked commands.Context."""
    ctx = AsyncMock(spec=commands.Context)
    ctx.author = mock_user
    ctx.guild = mock_guild
    ctx.channel = MagicMock(spec=nextcord.TextChannel)
    ctx.channel.id = 888
    ctx.command = MagicMock()
    ctx.command.name = 'test_command'
    ctx.send = AsyncMock()
    ctx.reply = AsyncMock()
    return ctx


@pytest.fixture
def mock_member():
    """A regular USER-role member (no special ID, no admin perms)."""
    member = MagicMock(spec=nextcord.Member)
    member.id = 999999999
    member.name = 'RegularUser'
    member.discriminator = '0042'
    member.display_name = 'RegularUser'
    member.bot = False
    member.guild_permissions = MagicMock(spec=nextcord.Permissions)
    member.guild_permissions.administrator = False
    member.roles = []
    member.joined_at = datetime(2024, 1, 1, tzinfo=UTC)
    member.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    member.avatar = None
    return member


@pytest.fixture
def admin_member():
    """A member with administrator permissions."""
    member = MagicMock(spec=nextcord.Member)
    member.id = 111111111
    member.name = 'AdminUser'
    member.discriminator = '0001'
    member.display_name = 'AdminUser'
    member.bot = False
    member.guild_permissions = MagicMock(spec=nextcord.Permissions)
    member.guild_permissions.administrator = True
    member.roles = []
    member.joined_at = datetime(2024, 1, 1, tzinfo=UTC)
    member.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    member.avatar = None
    return member
