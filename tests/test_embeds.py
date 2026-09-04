"""Tests for src/utils/embeds.py — brand colors, author, footer attribution."""

from __future__ import annotations

import nextcord
import pytest

from src.utils.embeds import (
    ORANGE,
    VEKA_AUTHOR_NAME,
    VEKA_AUTHOR_URL,
    alert_embed,
    error_embed,
    get_contributor,
    info_embed,
    success_embed,
    veka_embed,
)


@pytest.fixture(autouse=True)
def _clear_contributor_cache():
    """Clear the LRU cache on get_contributor between tests."""
    get_contributor.cache_clear()
    yield
    get_contributor.cache_clear()


class TestVekaEmbed:
    async def test_default_color_is_orange(self):
        embed = await veka_embed(title='Test')
        assert embed.color == ORANGE

    async def test_author_is_set(self):
        embed = await veka_embed(title='Test')
        assert embed.author.name == VEKA_AUTHOR_NAME
        assert embed.author.url == VEKA_AUTHOR_URL

    async def test_timestamp_present_by_default(self):
        embed = await veka_embed(title='Test')
        assert embed.timestamp is not None

    async def test_timestamp_disabled(self):
        embed = await veka_embed(title='Test', timestamp=False)
        assert embed.timestamp is None

    async def test_title_and_description(self):
        embed = await veka_embed(title='My Title', description='My Desc')
        assert embed.title == 'My Title'
        assert embed.description == 'My Desc'

    async def test_empty_title_when_none(self):
        embed = await veka_embed()
        assert embed.title == ''
        assert embed.description == ''


class TestSuccessEmbed:
    async def test_inherits_orange_color(self):
        embed = await success_embed(title='Done')
        assert embed.color == ORANGE
        assert embed.title == 'Done'


class TestErrorEmbed:
    async def test_color_is_red(self):
        embed = await error_embed(title='Fail', description='Something broke')
        assert embed.color == nextcord.Color.red()

    async def test_default_title(self):
        embed = await error_embed(description='Oops')
        assert embed.title == 'Error'


class TestInfoEmbed:
    async def test_default_title(self):
        embed = await info_embed(description='FYI')
        assert embed.title == 'Info'


class TestAlertEmbed:
    async def test_info_severity_blue(self):
        embed = await alert_embed(title='Hey', description='msg', severity='INFO')
        assert embed.color == nextcord.Color.blue()
        assert '[INFO] Hey' in (embed.title or '')

    async def test_warn_severity_gold(self):
        embed = await alert_embed(title='Careful', description='msg', severity='WARN')
        assert embed.color == nextcord.Color.gold()

    async def test_error_severity_red(self):
        embed = await alert_embed(title='Bad', description='msg', severity='ERROR')
        assert embed.color == nextcord.Color.red()

    async def test_critical_severity_dark_red(self):
        embed = await alert_embed(title='Critical', description='msg', severity='CRITICAL')
        assert embed.color == nextcord.Color.dark_red()

    async def test_unknown_severity_defaults_to_orange(self):
        embed = await alert_embed(title='Huh', description='msg', severity='UNKNOWN')
        assert embed.color == ORANGE


class TestContributorResolution:
    def test_static_map_hit(self):
        contrib = get_contributor('src.cogs.admin.basic')
        assert contrib['name'] == 'shifu'
        assert contrib['discord_id'] == '941009204045557842'

    def test_static_map_miss_falls_back_to_default(self):
        contrib = get_contributor('some.unknown.module')
        assert contrib['name'] == 'shifu'

    def test_none_source_returns_default(self):
        contrib = get_contributor(None)
        assert contrib['name'] == 'shifu'

    def test_empty_string_source_returns_default(self):
        contrib = get_contributor('')
        assert contrib['name'] == 'shifu'
