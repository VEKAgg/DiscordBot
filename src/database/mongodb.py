# MongoDB has been removed. The project uses PostgreSQL exclusively.
# This file is kept as a placeholder to avoid breaking any stale imports
# during the transition. It can be deleted once all references are confirmed gone.
raise ImportError(
    "mongodb.py has been removed. Use src.database.database (asyncpg/PostgreSQL) instead."
)
