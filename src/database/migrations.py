import re
from pathlib import Path

MIGRATIONS_TABLE = 'schema_migrations'

# Full prefix = 3 digits plus an optional letter suffix (``005`` and ``005b`` are distinct).
_PREFIX_PATTERN = re.compile(r'^(\d{3}[a-z]*)_')

# Migrations that were renamed after being applied somewhere. The runner keys on filename,
# so without this map a renamed file would be applied a second time.
LEGACY_MIGRATION_NAMES: dict[str, str] = {
    # Renamed in 93e2a72 to avoid colliding with 005_community_additions.sql.
    '005b_guild_and_rss_schema.sql': '005_guild_and_rss_schema.sql',
}


def get_migrations_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / 'migrations'


def list_migration_files() -> list[Path]:
    return sorted(p for p in get_migrations_dir().iterdir() if p.is_file() and p.suffix == '.sql')


def sort_migration_files(files: list[Path]) -> list[Path]:
    return sorted(files, key=lambda p: p.name)


def check_duplicate_prefixes(files: list[Path]) -> None:
    """Raise RuntimeError if two migration files share the same full prefix (e.g. two ``007_`` files)."""
    seen: dict[str, list[str]] = {}
    for f in files:
        match = _PREFIX_PATTERN.match(f.name)
        if match:
            seen.setdefault(match.group(1), []).append(f.name)
    duplicates = {k: v for k, v in seen.items() if len(v) > 1}
    if duplicates:
        detail = '; '.join(f'prefix {k}: {v}' for k, v in duplicates.items())
        raise RuntimeError(f'Duplicate migration prefix detected: {detail}')
