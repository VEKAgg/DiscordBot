"""Tests for migrations/ — filename conventions, prefix uniqueness, sequential ordering."""

from __future__ import annotations

import re

import pytest

from src.database.migrations import get_migrations_dir, list_migration_files

MIGRATIONS_DIR = get_migrations_dir()
# Standard NNN_name.sql pattern (e.g. 001_initial_schema.sql)
FILENAME_PATTERN = re.compile(r'^(\d{3})_([a-z0-9_]+)\.sql$')
# Pattern allowing a letter suffix for variant migrations (e.g. 005b_guild_and_rss_schema.sql)
FILENAME_PATTERN_WITH_SUFFIX = re.compile(r'^(\d{3}[a-z]*)_([a-z0-9_]+)\.sql$')


def _numeric_prefix(filename: str) -> int:
    """Extract the numeric prefix from a migration filename, stripping any letter suffix."""
    base = filename.split('_')[0]
    return int(re.sub(r'[a-z]', '', base))


@pytest.fixture
def migration_files():
    """List of migration file Path objects, sorted by name."""
    return list_migration_files()


class TestMigrationFilenames:
    def test_all_filenames_match_pattern(self, migration_files):
        for f in migration_files:
            match = FILENAME_PATTERN_WITH_SUFFIX.match(f.name)
            assert match, f'Filename {f.name!r} does not match expected pattern NNN[_suffix]_name.sql'

    def test_all_use_three_digit_numeric_prefix(self, migration_files):
        for f in migration_files:
            base = f.name.split('_')[0]
            numeric_part = re.sub(r'[a-z]', '', base)
            assert len(numeric_part) == 3, f'{f.name}: numeric prefix {numeric_part!r} is not 3 digits'
            assert numeric_part.isdigit(), f'{f.name}: numeric prefix {numeric_part!r} is not numeric'


class TestMigrationUniqueness:
    def test_no_duplicate_full_prefixes(self, migration_files):
        """No two files share the exact same full prefix (including letter suffixes)."""
        prefixes: dict[str, list[str]] = {}
        for f in migration_files:
            base = f.name.split('_')[0]
            prefixes.setdefault(base, []).append(f.name)

        duplicates = {k: v for k, v in prefixes.items() if len(v) > 1}
        assert not duplicates, f'Duplicate full migration prefixes found: {duplicates}'


class TestMigrationOrdering:
    def test_starts_at_001(self, migration_files):
        assert len(migration_files) > 0, 'No migration files found'
        first_prefix = _numeric_prefix(migration_files[0].name)
        assert first_prefix == 1, f'First migration should start at 001, got {first_prefix}'

    def test_no_gaps_in_numeric_prefixes(self, migration_files):
        """All numeric prefixes present from 1 to max should exist (no gaps except known exceptions)."""
        prefixes = sorted({_numeric_prefix(f.name) for f in migration_files})
        max_prefix = prefixes[-1]
        all_expected = set(range(1, max_prefix + 1))
        missing = all_expected - set(prefixes)
        # Known gap: no 002_ migration exists in this project
        known_missing = {2}
        unexpected_missing = missing - known_missing
        assert not unexpected_missing, f'Unexpected gaps in migration numbering: {unexpected_missing}'

    def test_strictly_ascending_by_full_prefix(self, migration_files):
        """Files are sorted by their full prefix string (005 < 005b < 006)."""
        full_prefixes = [f.name.split('_')[0] for f in migration_files]
        assert full_prefixes == sorted(full_prefixes), f'Files not in sorted order: {full_prefixes}'


class TestMigrationFilesExist:
    def test_migrations_directory_exists(self):
        assert MIGRATIONS_DIR.exists(), f'Migrations directory not found: {MIGRATIONS_DIR}'

    def test_migrations_directory_is_not_empty(self, migration_files):
        assert len(migration_files) > 0, 'Migrations directory is empty'

    def test_minimum_expected_count(self, migration_files):
        assert len(migration_files) >= 20, f'Expected at least 20 migrations, found {len(migration_files)}'

    def test_initial_schema_present(self, migration_files):
        names = {f.name for f in migration_files}
        assert '001_initial_schema.sql' in names, '001_initial_schema.sql not found'
