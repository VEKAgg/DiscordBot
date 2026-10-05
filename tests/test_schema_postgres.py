"""Schema integration tests against a real PostgreSQL (audit C-03 / H-05 / H-11).

Skipped unless ``VEKA_TEST_DATABASE_URL`` points at an EMPTY, disposable database, e.g.
``postgresql://postgres@127.0.0.1:5432/veka_test``. The database is wiped (schema ``public``
dropped and recreated) at the start of the module. CI runs this against a service container.
"""

from __future__ import annotations

import ast
import os
import pathlib

import pytest
import pytest_asyncio

DSN = os.getenv('VEKA_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DSN, reason='VEKA_TEST_DATABASE_URL not set')

_SQL_METHODS = {'fetch', 'fetch_one', 'fetchrow', 'fetchval', 'execute', 'execute_many', 'fetch_many'}
_SQL_KEYWORDS = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH')


def _static_sql_statements() -> list[tuple[str, int, str]]:
    """Every string-literal SQL statement passed to a db.* call under src/."""
    items = []
    for path in sorted(pathlib.Path('src').rglob('*.py')):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in _SQL_METHODS or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if any(k in arg.value.upper() for k in _SQL_KEYWORDS):
                    items.append((str(path), node.lineno, arg.value))
    return items


@pytest_asyncio.fixture(scope='module', loop_scope='module')
async def migrated_db():
    import asyncpg

    from src.database.database import Database

    conn = await asyncpg.connect(DSN)
    await conn.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')
    await conn.close()

    database = Database()
    database.pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    await database.run_migrations()
    yield database
    await database.close()


@pytest.mark.asyncio(loop_scope='module')
async def test_fresh_database_gets_full_schema(migrated_db):
    tables = await migrated_db.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    names = {r['table_name'] for r in tables}
    for required in ('users', 'warnings', 'guild_settings', 'honeypots', 'massunban_jobs', 'feed_subscriptions'):
        assert required in names


@pytest.mark.asyncio(loop_scope='module')
async def test_migrations_are_idempotent(migrated_db):
    before = await migrated_db.fetchval('SELECT COUNT(*) FROM schema_migrations')
    await migrated_db.run_migrations()
    after = await migrated_db.fetchval('SELECT COUNT(*) FROM schema_migrations')
    assert before == after


@pytest.mark.asyncio(loop_scope='module')
async def test_every_static_sql_statement_prepares(migrated_db):
    failures = []
    async with migrated_db.pool.acquire() as conn:
        for path, line, sql in _static_sql_statements():
            try:
                await conn.prepare(sql)
            except Exception as exc:
                failures.append(f'{path}:{line}: {type(exc).__name__}: {str(exc).splitlines()[0]}')
    assert not failures, 'SQL that does not match the migrated schema:\n' + '\n'.join(failures)


@pytest.mark.asyncio(loop_scope='module')
async def test_warnings_accept_discord_snowflakes(migrated_db):
    """H-05: warnings.user_id / moderator_id must hold 64-bit Discord IDs."""
    guild_id, user_id, mod_id = 1088553066334273537, 941009204045557842, 1222548162741538938
    await migrated_db.execute(
        'INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES ($1, $2, $3, $4)',
        guild_id,
        user_id,
        mod_id,
        'test',
    )
    count = await migrated_db.fetchval(
        'SELECT COUNT(*) FROM warnings WHERE guild_id = $1 AND user_id = $2 AND active = TRUE', guild_id, user_id
    )
    assert count == 1


@pytest.mark.asyncio(loop_scope='module')
async def test_honeypot_log_action_allowed(migrated_db):
    await migrated_db.execute(
        "INSERT INTO honeypots (guild_id, channel_id, action_type, created_by) VALUES ($1, $2, 'log', $3)",
        1,
        2,
        3,
    )
    await migrated_db.execute('UPDATE honeypots SET updated_by = $1 WHERE guild_id = 1', 941009204045557842)


@pytest.mark.asyncio(loop_scope='module')
async def test_feed_dedupe_is_per_subscription(migrated_db, monkeypatch):
    """H-12: two guilds subscribed to the same URL must each receive every entry once."""
    from src.services import rss_service as rss_module

    monkeypatch.setattr(rss_module, 'db', migrated_db)
    url = 'https://example.com/shared.xml'
    sub_a = await migrated_db.fetchval(
        "INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name) VALUES (11, 1, $1, 'a') RETURNING id",
        url,
    )
    sub_b = await migrated_db.fetchval(
        "INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name) VALUES (22, 2, $1, 'b') RETURNING id",
        url,
    )
    entries = [{'entry_id': 'guid-1', 'title': 't', 'link': 'l', 'description': 'd', 'author': 'a'}]
    service = rss_module.RSSService()

    assert len(await service.process_and_dedupe(url, entries, subscription_id=sub_a)) == 1
    assert len(await service.process_and_dedupe(url, entries, subscription_id=sub_a)) == 0
    # Previewing for delivery must not consume dedupe state (including repeated previews).
    assert len(await service.process_and_dedupe(url, entries, subscription_id=sub_b, mark_seen=False)) == 1
    assert len(await service.process_and_dedupe(url, entries, subscription_id=sub_b, mark_seen=False)) == 1
    assert len(await service.process_and_dedupe(url, entries, subscription_id=sub_b)) == 1


@pytest.mark.asyncio(loop_scope='module')
async def test_concurrent_mentor_completion_awards_xp_once(migrated_db):
    import asyncio

    mentor = await migrated_db.fetchval("INSERT INTO users (discord_id) VALUES ('90001') RETURNING id")
    mentee = await migrated_db.fetchval("INSERT INTO users (discord_id) VALUES ('90002') RETURNING id")
    match_id = await migrated_db.fetchval(
        """INSERT INTO mentorship_matches (guild_id, mentor_id, mentee_id, category)
           VALUES (1, $1, $2, 'test') RETURNING id""",
        mentor,
        mentee,
    )
    sql = next(
        sql
        for path, _, sql in _static_sql_statements()
        if path == 'src/cogs/mentorship.py' and 'WITH completed AS' in sql
    )
    results = await asyncio.gather(
        migrated_db.fetch_one(sql, match_id, mentor, 'successful', 50),
        migrated_db.fetch_one(sql, match_id, mentee, 'successful', 50),
    )
    assert sum(row is not None for row in results) == 1
    points = await migrated_db.fetch('SELECT points FROM users WHERE id IN ($1, $2)', mentor, mentee)
    assert [row['points'] for row in points] == [50, 50]
