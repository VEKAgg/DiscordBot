from pathlib import Path
from typing import List


MIGRATIONS_TABLE = 'schema_migrations'


def get_migrations_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / 'migrations'


def list_migration_files() -> List[Path]:
    return sorted(
        p for p in get_migrations_dir().iterdir()
        if p.is_file() and p.suffix == '.sql'
    )


def sort_migration_files(files: List[Path]) -> List[Path]:
    return sorted(files, key=lambda p: p.name)
