"""Tests for cog loading — all EXTENSIONS load, unload, and have setup functions."""

from __future__ import annotations

import pytest

from src.core.app import EXTENSIONS, build_bot


@pytest.fixture
def bot():
    """Headless bot for extension loading tests."""
    return build_bot()


class TestExtensionList:
    def test_extensions_is_list(self):
        assert isinstance(EXTENSIONS, list)

    def test_extensions_not_empty(self):
        assert len(EXTENSIONS) > 0

    def test_extensions_count(self):
        assert len(EXTENSIONS) == 22

    def test_all_are_strings(self):
        for ext in EXTENSIONS:
            assert isinstance(ext, str), f'Extension {ext!r} is not a string'

    def test_all_dotted_paths(self):
        for ext in EXTENSIONS:
            parts = ext.split('.')
            assert len(parts) >= 3, f'{ext} does not look like a dotted module path'

    def test_no_duplicates(self):
        assert len(EXTENSIONS) == len(set(EXTENSIONS)), 'Duplicate entries in EXTENSIONS'


class TestCogLoading:
    @pytest.mark.parametrize('extension', EXTENSIONS)
    def test_extension_loads_without_error(self, bot, extension):
        """Each extension should load without raising an exception."""
        try:
            bot.load_extension(extension)
        except Exception as exc:
            pytest.fail(f'Failed to load {extension}: {exc}')
        finally:
            try:
                bot.unload_extension(extension)
            except Exception:
                pass

    @pytest.mark.parametrize('extension', EXTENSIONS)
    def test_extension_unloads_cleanly(self, bot, extension):
        """Each loaded extension should unload without error."""
        try:
            bot.load_extension(extension)
            bot.unload_extension(extension)
        except Exception as exc:
            pytest.fail(f'Failed to unload {extension}: {exc}')
