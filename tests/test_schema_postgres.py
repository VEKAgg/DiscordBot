"""Schema integration tests against a real PostgreSQL (audit C-03 / H-05 / H-11).

Skipped unless ``VEKA_TEST_DATABASE_URL`` points at an EMPTY, disposable database, e.g.
``postgresql://postgres@127.0.0.1:5432/veka_test``. The database is wiped (schema ``public``
dropped and recreated) at the start of the module. CI runs this against a service container.
"""

from __future__ import annotations

import ast
import os
import pathlib
from typing import Any, cast

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
    # Servers used by the presence tests have activity tracking switched on (server opt-in, migration 037).
    await database.execute(
        """INSERT INTO guild_settings (guild_id, presence_tracking_enabled)
           SELECT unnest($1::bigint[]), TRUE ON CONFLICT (guild_id) DO UPDATE SET presence_tracking_enabled = TRUE""",
        [1, 2, 990000000000000001, 7701],
    )
    yield database
    await database.close()


@pytest.mark.asyncio(loop_scope='module')
async def test_fresh_database_gets_full_schema(migrated_db):
    tables = await migrated_db.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    names = {r['table_name'] for r in tables}
    for required in ('users', 'warnings', 'guild_settings', 'honeypots', 'massunban_jobs', 'feed_subscriptions'):
        assert required in names
    assert not await migrated_db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = 'users' AND column_name = 'total_listening_minutes')"
    )


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

    from src.services.mentorship_service import MentorshipService
    from src.utils.safety import ValidationError

    service = MentorshipService(database=migrated_db)
    await service.register_mentor(77, '90001', 'Python', 'Mentor')
    row = await service.create_mentorship_request(77, '90001', '90002', 'programming')
    await service.transition(77, row['id'], '90001', 'accept')
    results = await asyncio.gather(
        *(service.transition(77, row['id'], '90001', 'end') for _ in range(8)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValidationError) for result in results) == 7
    points = await migrated_db.fetch(
        "SELECT discord_id,points,experience,total_commands FROM users WHERE discord_id IN ('90001','90002') ORDER BY discord_id"
    )
    assert [user['points'] for user in points] == [50, 25]
    assert [user['experience'] for user in points] == [50, 25]
    assert all(user['total_commands'] == 0 for user in points)
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM mentorship_awards WHERE mentorship_id=$1', row['id']) == 2
    daily = await migrated_db.fetch(
        'SELECT user_id,xp_earned FROM user_activity_daily WHERE guild_id=77 AND user_id IN (90001,90002) ORDER BY user_id'
    )
    assert [user['xp_earned'] for user in daily] == [50, 25]


@pytest.mark.asyncio(loop_scope='module')
async def test_feed_outage_survives_cog_restart(migrated_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.cogs.resources.feeds import Feeds

    monkeypatch.setattr('src.cogs.resources.feeds.db', migrated_db)
    sub_id = await migrated_db.fetchval(
        "INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name) VALUES (33, 3, $1, 'outage') RETURNING id",
        'https://example.com/broken',
    )
    notifier = SimpleNamespace(send_alert=AsyncMock())
    bot = SimpleNamespace(notifier=notifier)
    for _ in range(6):
        sub = await migrated_db.fetch_one('SELECT * FROM feed_subscriptions WHERE id = $1', sub_id)
        await Feeds(bot)._record_poll_result(sub, succeeded=False)
    assert notifier.send_alert.await_count == 1
    sub = await migrated_db.fetch_one('SELECT * FROM feed_subscriptions WHERE id = $1', sub_id)
    assert sub['consecutive_failures'] == 6
    assert sub['next_retry_at'] > sub['last_polled_at']
    await Feeds(bot)._record_poll_result(sub, succeeded=True)
    assert notifier.send_alert.await_count == 2
    recovered = await migrated_db.fetch_one('SELECT * FROM feed_subscriptions WHERE id = $1', sub_id)
    assert recovered['consecutive_failures'] == 0
    assert recovered['next_retry_at'] is None
    for _ in range(3):
        sub = await migrated_db.fetch_one('SELECT * FROM feed_subscriptions WHERE id = $1', sub_id)
        await Feeds(bot)._record_poll_result(sub, succeeded=False)
    assert notifier.send_alert.await_count == 3
    # Reapplying the SQL itself (not just the runner) is safe and preserves outage state.
    await migrated_db.execute(pathlib.Path('migrations/027_feed_failure_backoff.sql').read_text())
    assert await migrated_db.fetchval('SELECT consecutive_failures FROM feed_subscriptions WHERE id = $1', sub_id) == 3


@pytest.mark.asyncio(loop_scope='module')
async def test_dynamic_feed_migration_preserves_configured_subscriptions(migrated_db):
    url = 'https://stackoverflow.com/jobs/feed'
    seeded = await migrated_db.fetchval(
        "INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name) VALUES (1088553066334273537, 0, $1, 'seed') RETURNING id",
        url,
    )
    configured = await migrated_db.fetchval(
        "INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name) VALUES (1088553066334273537, 4, $1, 'configured') RETURNING id",
        'https://remoteok.io/remote-jobs.rss',
    )
    custom = await migrated_db.fetchval(
        "INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name) VALUES (1088553066334273537, 0, $1, 'custom') RETURNING id",
        'https://example.com/custom',
    )
    sql = pathlib.Path('migrations/028_feed_management.sql').read_text()
    await migrated_db.execute(sql)
    await migrated_db.execute(sql)
    assert await migrated_db.fetch_one('SELECT id FROM feed_subscriptions WHERE id = $1', seeded) is None
    for sub_id in (configured, custom):
        assert await migrated_db.fetchval('SELECT paused FROM feed_subscriptions WHERE id = $1', sub_id) is False
    await migrated_db.execute('UPDATE feed_subscriptions SET paused = TRUE WHERE id = $1', configured)
    await migrated_db.execute(sql)
    assert await migrated_db.fetchval('SELECT paused FROM feed_subscriptions WHERE id = $1', configured) is True


@pytest.mark.asyncio(loop_scope='module')
async def test_forum_reingestion_preserves_withdrawal_and_reopens_archived(migrated_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import nextcord

    import src.cogs.marketplace.marketplace as module

    monkeypatch.setattr(module, 'db', migrated_db)
    owner_id = await migrated_db.fetchval("INSERT INTO users (discord_id) VALUES ('pg-forum-owner') RETURNING id")
    monkeypatch.setattr(module, 'get_or_create_user', AsyncMock(return_value={'id': owner_id}))
    channel = MagicMock(spec=nextcord.ForumChannel)
    channel.id = 888001
    monkeypatch.setattr(module.guild_settings_service, 'resolve_channel', AsyncMock(return_value=channel))
    monkeypatch.setattr(module.image_store, 'capture_attachments', AsyncMock())
    starter = SimpleNamespace(
        id=888002, author=SimpleNamespace(bot=False), webhook_id=None, content='Working laptop', attachments=[]
    )
    thread = SimpleNamespace(
        id=starter.id,
        parent_id=channel.id,
        guild=SimpleNamespace(id=888003),
        owner_id=888004,
        name='Laptop 123 USD',
        archived=False,
        locked=False,
        applied_tags=[],
        fetch_message=AsyncMock(return_value=starter),
    )
    thread = cast(Any, thread)
    cog = module.Marketplace(SimpleNamespace())
    await cog._ingest_forum_thread(thread)
    listing_id = f'FORUM{thread.id}'
    assert await migrated_db.fetchval('SELECT price FROM marketplace_listings WHERE id = $1', listing_id) == 123
    for status in ('withdrawn', 'removed', 'sold'):
        await migrated_db.execute('UPDATE marketplace_listings SET status = $2 WHERE id = $1', listing_id, status)
        thread.archived = True
        await cog._ingest_forum_thread(thread)
        thread.archived = False
        await cog._ingest_forum_thread(thread)
        await cog._withdraw_forum_thread(thread.id)
        assert await migrated_db.fetchval('SELECT status FROM marketplace_listings WHERE id = $1', listing_id) == status
    await migrated_db.execute("UPDATE marketplace_listings SET status = 'archived' WHERE id = $1", listing_id)
    await cog._ingest_forum_thread(thread)
    assert await migrated_db.fetchval('SELECT status FROM marketplace_listings WHERE id = $1', listing_id) == 'active'
    # Approval alone cannot leave an active unpriced item when its author removes the price.
    await migrated_db.execute(
        "UPDATE marketplace_listings SET forum_review_status = 'active' WHERE id = $1", listing_id
    )
    thread.name = 'Laptop - price in discussion'
    await cog._ingest_forum_thread(thread)
    pending = await migrated_db.fetch_one('SELECT price, status FROM marketplace_listings WHERE id = $1', listing_id)
    assert pending['price'] is None and pending['status'] == 'pending_review'
    thread.name = 'Laptop 123 USD'
    await cog._ingest_forum_thread(thread)
    assert await migrated_db.fetchval('SELECT status FROM marketplace_listings WHERE id = $1', listing_id) == 'active'
    # Staff-approved price/status survive forum title edits and archive/reopen.
    await migrated_db.execute(
        "UPDATE marketplace_listings SET price = 123.45, price_override = TRUE, forum_review_status = 'active' "
        'WHERE id = $1',
        listing_id,
    )
    thread.name = 'Laptop - price in discussion'
    await cog._ingest_forum_thread(thread)
    thread.archived = True
    await cog._ingest_forum_thread(thread)
    thread.archived = False
    await cog._ingest_forum_thread(thread)
    approved = await migrated_db.fetch_one('SELECT price, status FROM marketplace_listings WHERE id = $1', listing_id)
    assert str(approved['price']) == '123.45' and approved['status'] == 'active'


@pytest.mark.asyncio(loop_scope='module')
async def test_marketplace_image_roundtrip_and_attachment_identity(migrated_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import src.services.marketplace_images as module

    monkeypatch.setattr(module, 'db', migrated_db)
    owner_id = await migrated_db.fetchval("INSERT INTO users (discord_id) VALUES ('pg-image-owner') RETURNING id")
    await migrated_db.execute(
        'INSERT INTO marketplace_listings (id, seller_id, title, description, price, condition) '
        "VALUES ('PGIMAGE', $1, 'Image test', 'Test', 1, 'unknown')",
        owner_id,
    )
    store = module.PostgresImageStore()
    image = module.StoredImage(b'normalized-webp-test', 'a' * 64, 10, 20)
    download = AsyncMock(return_value=image)
    monkeypatch.setattr(module, 'download_image', download)
    attachment = SimpleNamespace(id=888101, content_type='image/webp', url='https://cdn.discordapp.com/test')
    assert await store.capture_attachments('PGIMAGE', [attachment], message_id=888102) == 1
    assert await store.get('PGIMAGE') == image
    attachment.url = 'https://cdn.discordapp.com/test?renewed=1'
    assert await store.capture_attachments('PGIMAGE', [attachment], message_id=888102) == 1
    download.assert_awaited_once()
    assert await store.capture_attachments('PGIMAGE', [], message_id=888102) == 0
    assert await store.get('PGIMAGE') is None


@pytest.mark.asyncio(loop_scope='module')
async def test_activity_award_records_real_quantities_atomically(migrated_db, monkeypatch):
    """Phase 3: totals record real minutes (no 60-min cap), XP is capped by the caller, the level is
    computed from the updated points, and the per-guild rollup uses the UTC date."""
    import asyncio

    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    uid, guild = 880000000000000001, 990000000000000001

    # A 180-minute voice session: 180 real minutes, XP capped at 60 by the caller.
    await svc.award('voice', [svc.Award(uid, guild, quantity=180, xp_base=60, touch_streak=True)])
    row = await migrated_db.fetch_one(
        'SELECT total_voice_minutes, points, level, current_streak FROM users WHERE discord_id = $1', str(uid)
    )
    assert row['total_voice_minutes'] == 180
    assert row['points'] == 60 and row['level'] == 0 and row['current_streak'] == 1
    daily = await migrated_db.fetch_one(
        'SELECT voice_minutes, xp_earned FROM user_activity_daily WHERE user_id = $1 AND guild_id = $2 '
        "AND activity_date = (NOW() AT TIME ZONE 'UTC')::date",
        uid,
        guild,
    )
    assert daily['voice_minutes'] == 180 and daily['xp_earned'] == 60

    # 50 concurrent message awards: every one counted, level consistent with the final points.
    await asyncio.gather(*(svc.award('message', [svc.Award(uid, guild, quantity=1, xp_base=1)]) for _ in range(50)))
    row = await migrated_db.fetch_one('SELECT total_messages, points, level FROM users WHERE discord_id = $1', str(uid))
    assert row['total_messages'] == 50 and row['points'] == 110
    assert row['level'] == int((110 / 100) ** 0.5)

    # Role multiplier, and gaming/coding/commands land in their own columns (presence needs opt-in).
    await migrated_db.execute(
        'UPDATE users SET presence_opt_in = TRUE, presence_opt_in_changed_at = NULL WHERE discord_id = $1', str(uid)
    )
    await svc.award('gaming', [svc.Award(uid, guild, quantity=2, xp_base=2, role_multiplier=1.5)])
    await svc.award('coding', [svc.Award(uid, guild, quantity=3, xp_base=3)])
    await svc.award('command', [svc.Award(uid, guild, quantity=1, xp_base=2)])
    row = await migrated_db.fetch_one(
        'SELECT total_gaming_minutes, total_coding_minutes, total_commands, points FROM users WHERE discord_id = $1',
        str(uid),
    )
    assert (row['total_gaming_minutes'], row['total_coding_minutes'], row['total_commands']) == (2, 3, 1)
    assert row['points'] == 110 + 3 + 3 + 2


@pytest.mark.asyncio(loop_scope='module')
async def test_activity_details_batch_upsert(migrated_db, monkeypatch):
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    await migrated_db.execute(
        "INSERT INTO users (discord_id, presence_opt_in) VALUES ('1', TRUE), ('2', FALSE) ON CONFLICT DO NOTHING"
    )
    await svc.add_activity_details(
        [(1, 'game', 'Valorant', 1, None, 1), (1, 'game', 'Valorant', 1, None, 1), (2, 'coding', 'VS Code', 1, None, 1)]
    )
    await svc.add_activity_details([(1, 'game', 'Valorant', 1, None, 1)])
    minutes = await migrated_db.fetchval(
        "SELECT duration_minutes FROM user_activity_details WHERE user_id = '1' AND activity_name = 'Valorant'"
    )
    assert minutes == 3
    # Not opted in: no detail rows.
    assert await migrated_db.fetchval("SELECT COUNT(*) FROM user_activity_details WHERE user_id = '2'") == 0


@pytest.mark.asyncio(loop_scope='module')
async def test_migration_032_repairs_gaming_and_coding_totals(migrated_db):
    """Re-running 032's repair statement rebuilds totals from user_activity_details."""
    sql = pathlib.Path('migrations/032_tracking_accuracy.sql').read_text()
    repair = sql[sql.index('UPDATE users u') :]
    await migrated_db.execute("INSERT INTO users (discord_id, total_gaming_minutes) VALUES ('777', 999)")
    await migrated_db.execute(
        'INSERT INTO user_activity_details (user_id, activity_type, activity_name, duration_minutes) VALUES '
        "('777', 'game', 'Valorant', 100), ('777', 'game', 'Visual Studio Code', 40), "
        "('777', 'coding', 'Visual Studio Code', 40)"
    )
    await migrated_db.execute(repair)
    row = await migrated_db.fetch_one(
        "SELECT total_gaming_minutes, total_coding_minutes FROM users WHERE discord_id = '777'"
    )
    assert (row['total_gaming_minutes'], row['total_coding_minutes']) == (100, 40)


@pytest.mark.asyncio(loop_scope='module')
async def test_week_chat_leaderboard_reads_per_guild_rollups(migrated_db, monkeypatch):
    """The old week/month chat board summed XP from user_activity_log with a mismatched activity_type,
    so it was always empty. It now sums this server's daily message counts."""
    from unittest.mock import MagicMock

    from src.cogs.rpg import rpg_manager
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    monkeypatch.setattr(rpg_manager, 'db', migrated_db)
    guild_a, guild_b = 4401, 4402
    await svc.award('message', [svc.Award(5501, guild_a, quantity=1, xp_base=1) for _ in range(1)])
    for _ in range(3):
        await svc.award('message', [svc.Award(5502, guild_a, quantity=1, xp_base=1)])
    await svc.award('message', [svc.Award(5503, guild_b, quantity=1, xp_base=1)])

    cog = rpg_manager.RPGManager(MagicMock())
    rows = await cog._get_stat_leaderboard('total_messages', 'week', guild_id=guild_a)
    assert [(r['discord_id'], r['value']) for r in rows] == [('5502', 3), ('5501', 1)]
    season = await cog._get_stat_leaderboard('points', 'season', guild_id=guild_b)
    assert [r['discord_id'] for r in season] == ['5503']


@pytest.mark.asyncio(loop_scope='module')
async def test_privacy_delete_erases_activity_and_opts_out(migrated_db, monkeypatch):
    from unittest.mock import MagicMock

    from src.cogs import privacy
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    monkeypatch.setattr(privacy, 'db', migrated_db)
    monkeypatch.setattr(privacy.audit_log, 'record', lambda **_: _noop())
    uid = 6601
    bot = MagicMock()
    bot.get_cog.return_value = None
    await privacy.set_presence_opt_in(bot, uid, True)
    await svc.award('gaming', [svc.Award(uid, 7701, quantity=5, xp_base=5)])
    await svc.add_activity_details([(uid, 'game', 'Valorant', 5, None, 7701)])
    await migrated_db.execute(
        "INSERT INTO user_active_activities (user_id, activity_type, activity_name) VALUES ($1, 'listening', 'Song')",
        str(uid),
    )

    await privacy.delete_activity_data(bot, uid)
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM user_active_activities WHERE user_id = $1', str(uid)) == 0

    row = await migrated_db.fetch_one(
        'SELECT points, total_gaming_minutes, presence_opt_in FROM users WHERE discord_id = $1', str(uid)
    )
    assert (row['points'], row['total_gaming_minutes'], row['presence_opt_in']) == (0, 0, False)
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM user_activity_daily WHERE user_id = $1', uid) == 0
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM user_activity_details WHERE user_id = $1', str(uid)) == 0


async def _noop():
    return None


@pytest.mark.asyncio(loop_scope='module')
async def test_season_archive_snapshots_month_per_guild_idempotently(migrated_db, monkeypatch):
    from datetime import date
    from unittest.mock import MagicMock

    from src.cogs.rpg import rpg_manager

    monkeypatch.setattr(rpg_manager, 'db', migrated_db)
    await migrated_db.execute(
        'INSERT INTO user_activity_daily (user_id, guild_id, activity_date, xp_earned, messages) VALUES '
        "(8801, 9901, '2026-08-10', 50, 5), (8802, 9901, '2026-08-11', 70, 7), "
        "(8801, 9902, '2026-08-12', 10, 1), (8801, 9901, '2026-07-31', 999, 99)"
    )
    cog = rpg_manager.RPGManager(MagicMock())
    await cog.archive_season(date(2026, 8, 20))
    await cog.archive_season(date(2026, 8, 20))  # second run adds nothing

    rows = await migrated_db.fetch(
        'SELECT guild_id, user_id, rank, score FROM leaderboard_snapshots '
        "WHERE season_month = '2026-08' AND category = 'xp' ORDER BY guild_id, rank"
    )
    assert [(r['guild_id'], r['user_id'], r['rank'], r['score']) for r in rows] == [
        (9901, 8802, 1, 70),
        (9901, 8801, 2, 50),  # July activity excluded
        (9902, 8801, 1, 10),
    ]


@pytest.mark.asyncio(loop_scope='module')
async def test_concurrent_warnings_each_see_their_own_count(migrated_db, monkeypatch):
    """Two simultaneous /warn calls used to count the same total and could both miss the ban threshold."""
    import asyncio

    from src.cogs.admin import moderation

    monkeypatch.setattr(moderation, 'db', migrated_db)
    counts = await asyncio.gather(*(moderation.record_warning(5150, 5151, 5152, f'r{i}') for i in range(5)))
    assert sorted(counts) == [1, 2, 3, 4, 5]


async def _set_streak(db, uid, streak, days_ago):
    await db.execute('INSERT INTO users (discord_id) VALUES ($1) ON CONFLICT DO NOTHING', str(uid))
    await db.execute(
        'UPDATE users SET points = 0, current_streak = $2, longest_streak = $2, '
        "last_streak_date = (NOW() AT TIME ZONE 'UTC')::date - $3::int WHERE discord_id = $1",
        str(uid),
        streak,
        days_ago,
    )


@pytest.mark.asyncio(loop_scope='module')
@pytest.mark.parametrize(
    ('streak', 'days_ago', 'touch', 'expected_xp', 'expected_streak'),
    [
        (30, 7, True, 100, 1),  # expired streak: reset to 1, no bonus (was 2x)
        (30, 7, False, 100, 30),  # expired, not touching: no bonus, stored streak untouched
        (2, 1, True, 125, 3),  # 2 -> 3 today: the 1.25x applies to this award
        (6, 1, True, 150, 7),  # 6 -> 7: 1.5x
        (29, 1, True, 200, 30),  # 29 -> 30: 2x
        (7, 0, True, 150, 7),  # already active today: unchanged
    ],
)
async def test_award_uses_effective_streak(
    migrated_db, monkeypatch, streak, days_ago, touch, expected_xp, expected_streak
):
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    uid = 7300 + streak * 10 + days_ago + (1000 if touch else 0)
    await _set_streak(migrated_db, uid, streak, days_ago)
    await svc.award('voice', [svc.Award(uid, 1, quantity=100, xp_base=100, touch_streak=touch)])
    row = await migrated_db.fetch_one('SELECT points, current_streak FROM users WHERE discord_id = $1', str(uid))
    assert (row['points'], row['current_streak']) == (expected_xp, expected_streak)


@pytest.mark.asyncio(loop_scope='module')
async def test_concurrent_midnight_touches_increment_streak_once(migrated_db, monkeypatch):
    import asyncio

    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    uid = 9400
    await _set_streak(migrated_db, uid, 2, 1)
    await asyncio.gather(
        *(svc.award('message', [svc.Award(uid, 1, quantity=1, xp_base=100, touch_streak=True)]) for _ in range(4))
    )
    row = await migrated_db.fetch_one('SELECT points, current_streak FROM users WHERE discord_id = $1', str(uid))
    assert row['current_streak'] == 3
    assert row['points'] == 4 * 125


@pytest.mark.asyncio(loop_scope='module')
async def test_presence_batch_after_opt_out_writes_nothing(migrated_db, monkeypatch):
    """A tick collected while opted in must not write presence data once the user opted out."""
    from unittest.mock import MagicMock

    from src.cogs import privacy
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    monkeypatch.setattr(privacy, 'db', migrated_db)
    uid = 7500
    bot = MagicMock()
    bot.get_cog.return_value = None
    await privacy.set_presence_opt_in(bot, uid, True)
    batch = {
        'gaming': [svc.Award(uid, 1, quantity=1, xp_base=1)],
        'voice': [svc.Award(uid, 1, quantity=1, xp_base=1)],
    }
    details: list[svc.Detail] = [(uid, 'game', 'Valorant', 1, None, 1)]
    await privacy.set_presence_opt_in(bot, uid, False)  # opt out between collection and write
    await svc.award_tick(batch, details)
    row = await migrated_db.fetch_one(
        'SELECT total_gaming_minutes, total_voice_minutes FROM users WHERE discord_id = $1', str(uid)
    )
    assert (row['total_gaming_minutes'], row['total_voice_minutes']) == (0, 1)  # voice isn't presence
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM user_activity_details WHERE user_id = $1', str(uid)) == 0


@pytest.mark.asyncio(loop_scope='module')
async def test_same_user_in_two_guilds_keeps_per_guild_attribution(migrated_db, monkeypatch):
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    uid = 7600
    await svc.award(
        'message',
        [
            svc.Award(uid, 101, quantity=1, xp_base=10, role_multiplier=1.0),
            svc.Award(uid, 202, quantity=2, xp_base=10, role_multiplier=2.0),
        ],
    )
    rows = await migrated_db.fetch(
        'SELECT guild_id, messages, xp_earned FROM user_activity_daily WHERE user_id = $1 ORDER BY guild_id', uid
    )
    assert [(r['guild_id'], r['messages'], r['xp_earned']) for r in rows] == [(101, 1, 10), (202, 2, 20)]
    row = await migrated_db.fetch_one('SELECT total_messages, points FROM users WHERE discord_id = $1', str(uid))
    assert (row['total_messages'], row['points']) == (3, 30)


@pytest.mark.asyncio(loop_scope='module')
async def test_season_snapshots_hide_members_who_opted_out(migrated_db, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from src.cogs.rpg import rpg_manager
    from src.core.runtime_state import runtime_state

    monkeypatch.setattr(rpg_manager, 'db', migrated_db)
    monkeypatch.setattr(runtime_state, 'db_available', True)
    await migrated_db.execute(
        "INSERT INTO users (discord_id, presence_opt_in) VALUES ('7701', FALSE), ('7702', TRUE) ON CONFLICT DO NOTHING"
    )
    await migrated_db.execute(
        'INSERT INTO leaderboard_snapshots (guild_id, season_month, category, user_id, rank, score) VALUES '
        "(77, '2000-01', 'gaming', 7701, 1, 500), (77, '2000-01', 'gaming', 7702, 2, 400), "
        "(77, '2000-01', 'xp', 7701, 1, 900)"
    )
    sent = {}
    interaction = MagicMock()
    interaction.guild = MagicMock(id=77, get_member=lambda _uid: None)
    interaction.response.defer = AsyncMock()

    async def capture(embed=None, **_):
        sent['embed'] = embed

    interaction.followup.send = capture
    cog = rpg_manager.RPGManager(MagicMock())
    with patch_month(rpg_manager, '2000-02-15'):
        await rpg_manager.RPGManager.leaderboard_season_command.callback(cog, interaction)
    previous = sent['embed'].description.split('Previous season')[1]
    assert 'User 7702' in previous and 'User 7701' in previous.split('**Xp:**')[1]
    assert 'User 7701' not in previous.split('**Xp:**')[0]


def patch_month(module, iso_day):
    """Freeze datetime.now in a module to a given UTC day."""
    from datetime import UTC, datetime
    from unittest.mock import patch

    frozen = datetime.fromisoformat(iso_day).replace(tzinfo=UTC)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003
            return frozen

    return patch.object(module, 'datetime', _Frozen)


@pytest.mark.asyncio(loop_scope='module')
async def test_missed_season_is_archived_on_recovery(migrated_db, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    from src.cogs.rpg import rpg_manager

    monkeypatch.setattr(rpg_manager, 'db', migrated_db)
    last_month = datetime.now(UTC).replace(day=1) - timedelta(days=1)
    await migrated_db.execute(
        'INSERT INTO user_activity_daily (user_id, guild_id, activity_date, xp_earned) VALUES (7801, 78, $1, 42)',
        last_month.date(),
    )
    cog = rpg_manager.RPGManager(MagicMock())
    cog._announce_season = AsyncMock()  # type: ignore[method-assign]
    await cog.ensure_previous_season_archived()
    await cog.ensure_previous_season_archived()  # second call is a no-op
    season = last_month.strftime('%Y-%m')
    score = await migrated_db.fetchval(
        "SELECT score FROM leaderboard_snapshots WHERE guild_id = 78 AND season_month = $1 AND category = 'xp'",
        season,
    )
    assert score == 42
    assert cog._announce_season.await_count <= 1


@pytest.mark.asyncio(loop_scope='module')
async def test_old_batch_cannot_write_after_opt_out_then_opt_in(migrated_db, monkeypatch):
    """Consent generation: a batch collected under consent g1 must not write after optout→optin (g2)."""
    from unittest.mock import MagicMock

    from src.cogs import privacy
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    monkeypatch.setattr(privacy, 'db', migrated_db)
    uid = 7550
    bot = MagicMock()
    bot.get_cog.return_value = None
    await privacy.set_presence_opt_in(bot, uid, True)
    g1 = await migrated_db.fetchval('SELECT presence_opt_in_changed_at FROM users WHERE discord_id = $1', str(uid))
    stale = {'gaming': [svc.Award(uid, 1, quantity=7, xp_base=7, consent_at=g1)]}
    await privacy.set_presence_opt_in(bot, uid, False)
    await privacy.set_presence_opt_in(bot, uid, True)
    await svc.award_tick(stale, [(uid, 'game', 'Valorant', 7, g1, 1)])
    assert await migrated_db.fetchval('SELECT total_gaming_minutes FROM users WHERE discord_id = $1', str(uid)) == 0
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM user_activity_details WHERE user_id = $1', str(uid)) == 0
    # A batch under the current consent does write.
    g2 = await migrated_db.fetchval('SELECT presence_opt_in_changed_at FROM users WHERE discord_id = $1', str(uid))
    await svc.award_tick({'gaming': [svc.Award(uid, 1, quantity=2, xp_base=2, consent_at=g2)]}, [])
    assert await migrated_db.fetchval('SELECT total_gaming_minutes FROM users WHERE discord_id = $1', str(uid)) == 2


@pytest.mark.asyncio(loop_scope='module')
async def test_partial_season_archive_rolls_back_and_recovers(migrated_db, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    from src.cogs.rpg import rpg_manager

    monkeypatch.setattr(rpg_manager, 'db', migrated_db)
    await migrated_db.execute('DELETE FROM season_archives')
    last_month = (datetime.now(UTC).replace(day=1) - timedelta(days=1)).date()
    season = last_month.strftime('%Y-%m')
    await migrated_db.execute('DELETE FROM leaderboard_snapshots WHERE season_month = $1', season)
    await migrated_db.execute(
        'INSERT INTO user_activity_daily (user_id, guild_id, activity_date, xp_earned, messages) '
        'VALUES (7901, 79, $1, 11, 3) ON CONFLICT DO NOTHING',
        last_month,
    )
    cog = rpg_manager.RPGManager(MagicMock())
    cog._announce_season = AsyncMock(return_value=True)  # type: ignore[method-assign]
    broken = {'xp': 'xp_earned', 'chat': 'no_such_column'}
    monkeypatch.setattr(rpg_manager, '_SEASON_CATEGORIES', broken)
    with pytest.raises(Exception):  # noqa: B017 - any SQL error
        await cog.ensure_previous_season_archived()
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM leaderboard_snapshots WHERE season_month = $1', season) == 0
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM season_archives WHERE season_month = $1', season) == 0

    monkeypatch.setattr(rpg_manager, '_SEASON_CATEGORIES', {'xp': 'xp_earned', 'chat': 'messages'})
    await cog.ensure_previous_season_archived()
    cats = await migrated_db.fetch(
        'SELECT DISTINCT category FROM leaderboard_snapshots WHERE season_month = $1 AND guild_id = 79', season
    )
    assert {r['category'] for r in cats} == {'xp', 'chat'}


@pytest.mark.asyncio(loop_scope='module')
async def test_concurrent_ticks_with_reversed_user_sets_do_not_deadlock(migrated_db, monkeypatch):
    import asyncio

    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    a, b = 8101, 8102
    for _ in range(10):
        await asyncio.gather(
            svc.award_tick({'voice': [svc.Award(b, 1, 1, 1)], 'message': [svc.Award(a, 1, 1, 1)]}, []),
            svc.award_tick({'voice': [svc.Award(a, 1, 1, 1)], 'message': [svc.Award(b, 1, 1, 1)]}, []),
        )
    totals = await migrated_db.fetch(
        "SELECT total_voice_minutes + total_messages AS n FROM users WHERE discord_id IN ('8101', '8102')"
    )
    assert [r['n'] for r in totals] == [20, 20]


@pytest.mark.asyncio(loop_scope='module')
async def test_mixed_consent_rows_only_current_generation_writes(migrated_db, monkeypatch):
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from src.cogs import privacy
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    monkeypatch.setattr(privacy, 'db', migrated_db)
    uid = 7560
    bot = MagicMock()
    bot.get_cog.return_value = None
    await privacy.set_presence_opt_in(bot, uid, True)
    current = await migrated_db.fetchval('SELECT presence_opt_in_changed_at FROM users WHERE discord_id = $1', str(uid))
    stale = datetime(2000, 1, 1, tzinfo=UTC)
    await svc.award(
        'gaming',
        [
            svc.Award(uid, 1, quantity=5, xp_base=0, consent_at=stale),
            svc.Award(uid, 2, quantity=2, xp_base=0, consent_at=current),
        ],
    )
    assert await migrated_db.fetchval('SELECT total_gaming_minutes FROM users WHERE discord_id = $1', str(uid)) == 2


@pytest.mark.asyncio(loop_scope='module')
async def test_bot_previews_dashboard_massunban_once_and_honours_cancel(migrated_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from src.cogs.admin import massunban

    monkeypatch.setattr(massunban, 'db', migrated_db)
    guild_id = 6060
    job_id = await migrated_db.fetchval(
        """INSERT INTO massunban_jobs (guild_id, requested_by, status, source, start_datetime, end_datetime,
                                       include_unaudited)
           VALUES ($1, 1, 'requested', 'dashboard', '2024-01-01', '2025-01-01', TRUE) RETURNING id""",
        guild_id,
    )

    async def bans(limit=None):  # noqa: ARG001
        for uid in (501, 502, 503):
            yield SimpleNamespace(user=SimpleNamespace(id=uid), reason=None)

    guild = MagicMock()
    guild.id = guild_id
    guild.bans = bans
    bot = MagicMock()
    bot.get_guild.return_value = guild
    bot.guilds = [guild]
    cog = massunban.MassUnban(bot)

    await cog.handle_dashboard_job(job_id)
    await cog.handle_dashboard_job(job_id)  # already claimed: no second preview

    job = await migrated_db.fetch_one('SELECT status, total_matched FROM massunban_jobs WHERE id = $1', job_id)
    assert (job['status'], job['total_matched']) == ('awaiting_confirmation', 3)
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM massunban_job_items WHERE job_id = $1', job_id) == 3

    cog._active_jobs[job_id] = False  # pretend a worker is running
    await migrated_db.execute("UPDATE massunban_jobs SET status = 'cancelled' WHERE id = $1", job_id)
    await cog.handle_dashboard_job(job_id)
    assert cog._active_jobs[job_id] is True


@pytest.mark.asyncio(loop_scope='module')
async def test_concurrent_marketplace_bump_has_one_winner(migrated_db):
    import asyncio

    from src.services.marketplace_service import bump_listing

    owner = 2718001
    user_id = await migrated_db.fetchval('INSERT INTO users (discord_id) VALUES ($1) RETURNING id', str(owner))
    await migrated_db.execute(
        # Creation starts the cooldown; seed an eligible older listing for the concurrency test.
        'INSERT INTO marketplace_listings (id, seller_id, title, description, price, condition, last_bumped_at) '
        "VALUES ('PGBUMP', $1, 'Bump test', 'Test', 1, 'good', NOW() - INTERVAL '2 days')",
        user_id,
    )
    winners = await asyncio.gather(*(bump_listing('PGBUMP', owner, database=migrated_db) for _ in range(8)))
    assert sum(winners) == 1
    assert not await bump_listing('PGBUMP', owner + 1, database=migrated_db)


@pytest.mark.asyncio(loop_scope='module')
async def test_concurrent_connections_reserve_and_accept_once(migrated_db, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from src.services import networking_service as module

    first = await migrated_db.fetchval("INSERT INTO users (discord_id) VALUES ('2718011') RETURNING id")
    second = await migrated_db.fetchval("INSERT INTO users (discord_id) VALUES ('2718012') RETURNING id")
    monkeypatch.setattr(module, 'db', migrated_db)
    svc = module.NetworkingService()
    monkeypatch.setattr(
        svc, '_resolve_user_id', AsyncMock(side_effect=lambda uid: first if uid == '2718011' else second)
    )
    results = await asyncio.gather(
        *(svc.create_request('2718011', '2718012') for _ in range(8)), return_exceptions=True
    )
    request_ids = [result for result in results if isinstance(result, int)]
    assert len(request_ids) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 7
    assert not await svc.respond_request(request_ids[0], '2718011', accept=True)
    responses = await asyncio.gather(*(svc.respond_request(request_ids[0], '2718012', accept=True) for _ in range(8)))
    assert sum(responses) == 1
    assert (
        await migrated_db.fetchval(
            'SELECT COUNT(*) FROM connections WHERE (user1_id = $1 AND user2_id = $2) OR (user1_id = $2 AND user2_id = $1)',
            first,
            second,
        )
        == 1
    )
    assert (
        await migrated_db.fetchval('SELECT status FROM connection_requests WHERE id = $1', request_ids[0]) == 'accepted'
    )


def _marketplace_access(guild_id: int = 77):
    from src.api.auth import GuildAccess, Principal
    from src.api.discord_client import MANAGE_GUILD, DiscordUser, Identity, UserGuild

    member = UserGuild(guild_id, 'PG Guild', None, False, MANAGE_GUILD)
    principal = Principal('user', Identity(DiscordUser(810000000000007778, 'manager', None, None), {guild_id: member}))
    return GuildAccess(principal, guild_id, member, {})


async def _seed_api_listing(database, listing_id: str, *, price: str | None = '10.00'):
    from decimal import Decimal

    seller = await database.fetchval(
        "INSERT INTO users (discord_id) VALUES ('810000000000007777') ON CONFLICT (discord_id) "
        'DO UPDATE SET discord_id = EXCLUDED.discord_id RETURNING id'
    )
    await database.execute(
        'INSERT INTO marketplace_listings (id, seller_id, title, description, price, condition, status, source, guild_id) '
        "VALUES ($1, $2, 'PG listing', 'Test listing', $3, 'unknown', 'pending_review', 'forum', 77)",
        listing_id,
        seller,
        Decimal(price) if price is not None else None,
    )


@pytest.mark.asyncio(loop_scope='module')
async def test_marketplace_mutation_guild_scope_and_approval_overrides(migrated_db, monkeypatch):
    from decimal import Decimal

    from src.api.errors import ApiError
    from src.api.routes import marketplace as module

    monkeypatch.setattr(module, 'db', migrated_db)
    listing_id = 'PGAPISCOPE'
    await _seed_api_listing(migrated_db, listing_id, price=None)
    with pytest.raises(ApiError) as error:
        await module.update_listing(listing_id, module.ListingPatch(price='12.34'), _marketplace_access(88))
    assert error.value.status == 404
    assert await migrated_db.fetchval('SELECT price FROM marketplace_listings WHERE id = $1', listing_id) is None
    await migrated_db.execute(
        'INSERT INTO marketplace_publications (guild_id, listing_id, channel_id, message_id) VALUES (88, $1, 88001, 88002)',
        listing_id,
    )
    result = await module.update_listing(
        listing_id, module.ListingPatch(price='12.34', status='active'), _marketplace_access(88)
    )
    assert result['price'] == '12.34' and result['status'] == 'active'
    row = await migrated_db.fetch_one(
        'SELECT price, price_override, forum_review_status FROM marketplace_listings WHERE id = $1', listing_id
    )
    assert row['price'] == Decimal('12.34') and row['price_override'] and row['forum_review_status'] == 'active'
    assert (
        await migrated_db.fetchval(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'dashboard_marketplace_changed' AND details->>'listing_id' = $1",
            listing_id,
        )
        == 1
    )


@pytest.mark.asyncio(loop_scope='module')
async def test_marketplace_audit_failure_rolls_back_listing_and_overrides(migrated_db, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from src.api.routes import marketplace as module
    from src.utils.safety import DatabaseQueryError

    listing_id = 'PGAPIAUDIT'
    await _seed_api_listing(migrated_db, listing_id)

    @asynccontextmanager
    async def transaction():
        async with migrated_db.transaction() as conn:

            async def execute(sql, *args):
                if 'INSERT INTO audit_logs' in sql:
                    return await conn.execute('SELECT 1 / 0')
                return await conn.execute(sql, *args)

            yield SimpleNamespace(fetchrow=conn.fetchrow, execute=execute)

    monkeypatch.setattr(module, 'db', SimpleNamespace(transaction=transaction))
    with pytest.raises(DatabaseQueryError):
        await module.update_listing(
            listing_id, module.ListingPatch(price='12.34', status='active'), _marketplace_access()
        )
    row = await migrated_db.fetch_one(
        'SELECT price, status, price_override, forum_review_status FROM marketplace_listings WHERE id = $1', listing_id
    )
    assert str(row['price']) == '10.00' and row['status'] == 'pending_review'
    assert not row['price_override'] and row['forum_review_status'] is None


@pytest.mark.asyncio(loop_scope='module')
async def test_marketplace_concurrent_approval_has_one_audited_winner(migrated_db, monkeypatch):
    import asyncio

    from src.api.errors import ApiError
    from src.api.routes import marketplace as module

    monkeypatch.setattr(module, 'db', migrated_db)
    listing_id = 'PGAPIAPPROVE'
    await _seed_api_listing(migrated_db, listing_id)
    results = await asyncio.gather(
        *(
            module.update_listing(listing_id, module.ListingPatch(status='active'), _marketplace_access())
            for _ in range(8)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ApiError) and result.status == 409 for result in results) == 7
    assert (
        await migrated_db.fetchval(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'dashboard_marketplace_changed' AND details->>'listing_id' = $1",
            listing_id,
        )
        == 1
    )


@pytest.mark.asyncio(loop_scope='module')
async def test_marketplace_concurrent_price_and_approval_preserve_both_changes(migrated_db, monkeypatch):
    import asyncio
    import json

    from src.api.routes import marketplace as module

    monkeypatch.setattr(module, 'db', migrated_db)
    listing_id = 'PGAPICOMBINED'
    await _seed_api_listing(migrated_db, listing_id)
    await asyncio.gather(
        module.update_listing(listing_id, module.ListingPatch(price='12.34'), _marketplace_access()),
        module.update_listing(listing_id, module.ListingPatch(status='active'), _marketplace_access()),
    )
    row = await migrated_db.fetch_one(
        'SELECT price, status, price_override, forum_review_status FROM marketplace_listings WHERE id = $1', listing_id
    )
    assert str(row['price']) == '12.34' and row['status'] == 'active'
    assert row['price_override'] and row['forum_review_status'] == 'active'
    records = await migrated_db.fetch(
        "SELECT details FROM audit_logs WHERE action = 'dashboard_marketplace_changed' AND details->>'listing_id' = $1 ORDER BY id",
        listing_id,
    )
    assert len(records) == 2
    first, second = [json.loads(record['details']) for record in records]
    assert first['after'] == second['before']


@pytest.mark.asyncio(loop_scope='module')
async def test_network_profile_array_and_timezone_roundtrip(migrated_db, monkeypatch):
    from unittest.mock import AsyncMock

    from src.services import networking_service as module

    user_id = await migrated_db.fetchval("INSERT INTO users (discord_id) VALUES ('pg-network-profile') RETURNING id")
    monkeypatch.setattr(module, 'db', migrated_db)
    svc = module.NetworkingService()
    monkeypatch.setattr(svc, '_resolve_user_id', AsyncMock(return_value=user_id))
    await svc.upsert_profile(
        'pg-network-profile', {'title': 'Engineer', 'skills': 'Python, SQL, Python', 'timezone': 'Europe/London'}
    )
    row = await svc.get_profile('pg-network-profile')
    assert row is not None
    assert row['skills'] == ['Python', 'SQL'] and row['timezone'] == 'Europe/London'
    await svc.upsert_profile('pg-network-profile', {'title': 'Edited', 'skills': ['SQL']})
    row = await svc.get_profile('pg-network-profile')
    assert row is not None
    assert row['skills'] == ['SQL'] and row['timezone'] == 'Europe/London'
    await svc.upsert_profile('pg-network-profile', {'skills': [], 'timezone': None})
    row = await svc.get_profile('pg-network-profile')
    assert row is not None
    assert row['skills'] == [] and row['timezone'] is None


async def _mentorship_pg_pair(database, seed):
    from src.services.mentorship_service import MentorshipService

    service = MentorshipService(database=database)
    guild = 7000 + seed
    mentor, mentee = str(920000 + seed * 100), str(920001 + seed * 100)
    await service.register_mentor(guild, mentor, 'Python', 'Mentor', categories=['programming'])
    row = await service.create_mentorship_request(guild, mentor, mentee, 'programming')
    return service, guild, mentor, mentee, row


@pytest.mark.asyncio(loop_scope='module')
async def test_mentorship_live_pair_duplicate_swapped_and_availability(migrated_db):
    import asyncio

    from src.utils.safety import ValidationError

    service, guild, mentor, mentee, row = await _mentorship_pg_pair(migrated_db, 1)
    await service.transition(guild, row['id'], mentee, 'end', 'cancelled')
    await service.register_mentor(guild, mentee, 'SQL', 'Peer', categories=['programming'])
    results = await asyncio.gather(
        *(
            service.create_mentorship_request(guild, a, b, 'programming')
            for a, b in [(mentor, mentee), (mentee, mentor)] * 4
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValidationError) for result in results) == 7
    winner = next(result for result in results if isinstance(result, dict))
    await service.transition(guild, winner['id'], mentor, 'end', 'cancelled')
    await service.set_availability(guild, mentor, False)
    with pytest.raises(ValidationError):
        await service.create_mentorship_request(guild, mentor, mentee, 'programming')
    assert await service.find_mentors(guild, None)  # newcomer peer remains discoverable without completion history
    await service.register_mentor(guild, mentor)  # role-only re-registration preserves saved metadata
    registration = await migrated_db.fetch_one(
        'SELECT * FROM mentor_registrations WHERE guild_id=$1 AND user_id=(SELECT id FROM users WHERE discord_id=$2)',
        guild,
        mentor,
    )
    assert registration['skills'] == ['Python'] and registration['bio'] == 'Mentor'
    assert registration['categories'] == ['programming'] and registration['available']


@pytest.mark.asyncio(loop_scope='module')
async def test_mentorship_actor_guild_and_state_qualification(migrated_db):
    from src.utils.safety import ValidationError

    service, guild, mentor, mentee, row = await _mentorship_pg_pair(migrated_db, 2)
    for other_guild, actor in [(guild + 1000, mentor), (guild, '999999999')]:
        with pytest.raises(ValidationError):
            await service.transition(other_guild, row['id'], actor, 'accept')
    with pytest.raises(ValidationError):
        await service.transition(guild, row['id'], mentee, 'accept')
    await service.transition(guild, row['id'], mentor, 'accept')
    with pytest.raises(ValidationError):
        await service.transition(guild, row['id'], mentee, 'end', 'successful')
    result = await service.transition(guild, row['id'], mentee, 'end', 'cancelled')
    assert result['awards'] == []
    with pytest.raises(ValidationError):
        await service.transition(guild, row['id'], mentor, 'end', 'successful')
    assert not await service.get_user_mentorships(mentor, guild + 1000)
    assert not await service.get_user_mentorships('999999999', guild)
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM mentorship_awards WHERE mentorship_id=$1', row['id']) == 0


@pytest.mark.asyncio(loop_scope='module')
async def test_mentorship_completion_cancel_race_has_single_audited_winner(migrated_db):
    import asyncio

    from src.utils.safety import ValidationError

    service, guild, mentor, mentee, row = await _mentorship_pg_pair(migrated_db, 3)
    await service.transition(guild, row['id'], mentor, 'accept')
    results = await asyncio.gather(
        service.transition(guild, row['id'], mentor, 'end', 'successful'),
        service.transition(guild, row['id'], mentee, 'end', 'cancelled'),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValidationError) for result in results) == 1
    winner = next(result for result in results if isinstance(result, dict))
    expected = 2 if winner['outcome'] == 'successful' else 0
    assert (
        await migrated_db.fetchval('SELECT COUNT(*) FROM mentorship_awards WHERE mentorship_id=$1', row['id'])
        == expected
    )
    # accept plus exactly one terminal audit, never a claimed reward for a cancellation
    assert (
        await migrated_db.fetchval(
            "SELECT COUNT(*) FROM audit_logs WHERE action='mentorship_changed' AND details->>'id'=$1", str(row['id'])
        )
        == 2
    )


@pytest.mark.asyncio(loop_scope='module')
@pytest.mark.parametrize('fail_at', ['award', 'audit'])
async def test_mentorship_award_and_audit_error_roll_back_every_write(migrated_db, fail_at):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from src.utils.safety import DatabaseUnavailableError

    seed = 4 if fail_at == 'award' else 5
    service, guild, mentor, mentee, row = await _mentorship_pg_pair(migrated_db, seed)
    await service.transition(guild, row['id'], mentor, 'accept')

    class FailingConnection:
        def __init__(self, conn):
            self.conn = conn
            self.awards = 0

        def __getattr__(self, name):
            return getattr(self.conn, name)

        async def execute(self, sql, *args):
            if 'INSERT INTO mentorship_awards' in sql:
                self.awards += 1
                if fail_at == 'award' and self.awards == 2:
                    return await self.conn.execute('SELECT 1 / 0')
            if fail_at == 'audit' and 'INSERT INTO audit_logs' in sql:
                return await self.conn.execute('SELECT 1 / 0')
            return await self.conn.execute(sql, *args)

    @asynccontextmanager
    async def failing_transaction():
        async with migrated_db.transaction() as conn:
            yield FailingConnection(conn)

    service.db = SimpleNamespace(fetch_one=migrated_db.fetch_one, transaction=failing_transaction)
    with pytest.raises(DatabaseUnavailableError):
        await service.transition(guild, row['id'], mentor, 'end')
    assert await migrated_db.fetchval('SELECT status FROM mentorships WHERE id=$1', row['id']) == 'active'
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM mentorship_awards WHERE mentorship_id=$1', row['id']) == 0
    users = await migrated_db.fetch(
        'SELECT points,experience FROM users WHERE discord_id=ANY($1::text[])', [mentor, mentee]
    )
    assert all(user['points'] == user['experience'] == 0 for user in users)
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM user_activity_daily WHERE guild_id=$1', guild) == 0


@pytest.mark.asyncio(loop_scope='module')
async def test_mentorship_unbound_legacy_history_and_no_retrospective_credit(migrated_db):
    from src.utils.safety import ValidationError

    service, guild, mentor, mentee, created = await _mentorship_pg_pair(migrated_db, 6)
    await service.transition(guild, created['id'], mentor, 'end', 'cancelled')
    legacy = await migrated_db.fetchval(
        "INSERT INTO mentorships (mentor_id,mentee_id,category,status) SELECT a.id,b.id,'programming','active' FROM users a,users b WHERE a.discord_id=$1 AND b.discord_id=$2 RETURNING id",
        mentor,
        mentee,
    )
    with pytest.raises(ValidationError):
        await service.transition(guild, legacy, mentor, 'end')
    history = await service.get_user_mentorships(mentor, None)
    assert any(
        item['id'] == legacy and not item['reward_eligible'] and item['created_at_utc'] is None for item in history
    )
    assert not await service.get_user_mentorships('999999999', None)
    # Simulate a future EXPLICIT staff binding; even then legacy provenance never generates retrospective XP.
    await migrated_db.execute('UPDATE mentorships SET guild_id=$2 WHERE id=$1', legacy, guild)
    result = await service.transition(guild, legacy, mentor, 'end')
    assert result['awards'] == []
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM mentorship_awards WHERE mentorship_id=$1', legacy) == 0


@pytest.mark.asyncio(loop_scope='module')
async def test_mentorship_reminders_default_off_lease_revision_and_backoff(migrated_db):
    service, guild, mentor, mentee, row = await _mentorship_pg_pair(migrated_db, 7)
    await service.transition(guild, row['id'], mentor, 'accept')
    await migrated_db.execute("UPDATE mentorships SET started_at=NOW()-INTERVAL '8 days' WHERE id=$1", row['id'])
    assert not await service.due_reminders()
    await service.set_reminders(guild, mentee, True)
    assert not await service.due_reminders()  # no initial/historical blast
    await migrated_db.execute(
        'UPDATE mentorship_notification_preferences SET next_attempt_at=NOW() WHERE guild_id=$1', guild
    )
    due = await service.due_reminders()
    candidate = next(item for item in due if item['guild_id'] == guild)
    args = (guild, candidate['user_id'], candidate['revision'])
    assert await service.claim_reminder(*args)
    assert not await service.claim_reminder(*args)
    await service.finish_reminder(*args, False)
    pref = await migrated_db.fetch_one('SELECT * FROM mentorship_notification_preferences WHERE guild_id=$1', guild)
    assert pref['last_sent_at'] is None
    await service.set_reminders(guild, mentee, False)
    assert not await service.reminder_current(*args)
    await service.finish_reminder(*args, True)
    pref = await migrated_db.fetch_one('SELECT * FROM mentorship_notification_preferences WHERE guild_id=$1', guild)
    assert not pref['enabled'] and pref['last_sent_at'] is None
    assert not await service.current_reminder_matches(*args)


@pytest.mark.asyncio(loop_scope='module')
async def test_mentorship_user_lock_order_matches_tick_with_reversed_internal_ids(migrated_db):
    import asyncio

    from src.services.mentorship_service import MentorshipService

    service = MentorshipService(database=migrated_db)
    # Create high snowflake first: internal-ID order is the reverse of the shared text-discord-ID lock order.
    await service.register_mentor(7088, '939200', 'Python', 'Mentor')
    row = await service.create_mentorship_request(7088, '939200', '939100', 'programming')
    await service.transition(7088, row['id'], '939200', 'accept')
    async with asyncio.TaskGroup() as group:
        async with migrated_db.transaction() as tick:
            await tick.fetchrow('SELECT id FROM users WHERE discord_id=$1 FOR UPDATE', '939100')
            task = group.create_task(service.transition(7088, row['id'], '939200', 'end'))
            # Wait for the other connection to block on the first row, then take the second in tick order.
            # An internal-ID-order implementation would already hold the second row and deadlock here.
            async with asyncio.timeout(5):
                while not await tick.fetchval(
                    "SELECT 1 FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND wait_event_type='Lock' AND query LIKE '%FROM users WHERE id = ANY%' LIMIT 1"
                ):
                    await asyncio.sleep(0.01)
                await tick.fetchrow('SELECT id FROM users WHERE discord_id=$1 FOR UPDATE', '939200')
                await tick.execute(
                    "UPDATE users SET points=points+1,experience=experience+1 WHERE discord_id IN ('939100','939200')"
                )
    assert isinstance(task.result(), dict)
    points = await migrated_db.fetch(
        "SELECT points FROM users WHERE discord_id IN ('939100','939200') ORDER BY discord_id"
    )
    assert [item['points'] for item in points] == [26, 51]


@pytest.mark.asyncio(loop_scope='module')
async def test_presence_is_not_written_for_servers_without_tracking(migrated_db, monkeypatch):
    """Server opt-in: a batch credited to a server that hasn't enabled tracking writes no presence data,
    while voice in the same tick still counts."""
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    uid, off_guild = 9911, 9912
    await migrated_db.execute('DELETE FROM users WHERE discord_id = $1', str(uid))
    await svc.award_tick(
        {
            'gaming': [svc.Award(uid, off_guild, quantity=3, xp_base=3)],
            'voice': [svc.Award(uid, off_guild, quantity=3, xp_base=3)],
        },
        [(uid, 'game', 'Valorant', 3, None, off_guild)],
    )
    row = await migrated_db.fetch_one(
        'SELECT total_gaming_minutes, total_voice_minutes, presence_opt_in FROM users WHERE discord_id = $1', str(uid)
    )
    assert (row['total_gaming_minutes'], row['total_voice_minutes']) == (0, 3)
    assert row['presence_opt_in'] is True  # new members default to allowed (member opt-out model)
    assert await migrated_db.fetchval('SELECT COUNT(*) FROM user_activity_details WHERE user_id = $1', str(uid)) == 0


@pytest.mark.asyncio(loop_scope='module')
async def test_all_time_board_is_per_server(migrated_db, monkeypatch):
    """A new server's all-time board shows only its own members, not the main server's veterans."""
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    await svc.award('message', [svc.Award(8201, 820, quantity=1, xp_base=500)])  # veteran elsewhere
    await svc.award('message', [svc.Award(8202, 821, quantity=1, xp_base=5)])  # member of the new server
    board = await svc.leaderboard('points', 'alltime', guild_id=821, limit=10)
    assert [r['discord_id'] for r in board] == ['8202']
    everyone = await svc.leaderboard('points', None, limit=1000)  # no guild = all servers
    assert {'8201', '8202'} <= {r['discord_id'] for r in everyone}


@pytest.mark.asyncio(loop_scope='module')
async def test_season_is_announced_once_per_server(migrated_db, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    from src.cogs.rpg import rpg_manager

    monkeypatch.setattr(rpg_manager, 'db', migrated_db)
    now = datetime.now(UTC)
    frozen = now.replace(day=2)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003
            return frozen

    monkeypatch.setattr(rpg_manager, 'datetime', _Frozen)
    season = (frozen.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    await migrated_db.execute('DELETE FROM season_announcements WHERE season_month = $1', season)
    guild_a, guild_b = MagicMock(id=831), MagicMock(id=832)
    bot = MagicMock()
    bot.guilds = [guild_a, guild_b]
    cog = rpg_manager.RPGManager(bot)
    cog.archive_season = AsyncMock()  # type: ignore[method-assign]
    cog._announce_season = AsyncMock(side_effect=[True, False, True])  # type: ignore[method-assign]

    await cog.ensure_previous_season_archived()  # A posts, B fails (retry later)
    await cog.ensure_previous_season_archived()  # only B is retried

    calls = [c.args[0].id for c in cog._announce_season.await_args_list]
    assert calls == [831, 832, 832]
    done = await migrated_db.fetch('SELECT guild_id FROM season_announcements WHERE season_month = $1', season)
    assert sorted(r['guild_id'] for r in done) == [831, 832]


@pytest.mark.asyncio(loop_scope='module')
async def test_season_archive_waits_for_privacy_delete_and_does_not_resurrect(migrated_db, monkeypatch):
    """A deletion in progress (user row locked, rows deleted, not yet committed) must win: the archive
    waits on the same lock and then sees the rows gone."""
    import asyncio
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    import asyncpg

    from src.cogs.rpg import rpg_manager
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    monkeypatch.setattr(rpg_manager, 'db', migrated_db)
    uid = 8301
    await svc.award('message', [svc.Award(uid, 7701, quantity=3, xp_base=30)])
    season = datetime.now(UTC).strftime('%Y-%m')
    await migrated_db.execute('DELETE FROM season_archives WHERE season_month = $1', season)

    deleter = await asyncpg.connect(DSN)
    try:
        tx = deleter.transaction()
        await tx.start()
        await deleter.execute('SELECT 1 FROM users WHERE discord_id = $1 FOR UPDATE', str(uid))
        await deleter.execute('DELETE FROM user_activity_daily WHERE user_id = $1', uid)
        await deleter.execute('DELETE FROM leaderboard_snapshots WHERE user_id = $1', uid)

        archive = asyncio.create_task(rpg_manager.RPGManager(MagicMock()).archive_season(datetime.now(UTC).date()))
        await asyncio.sleep(0.5)
        assert not archive.done()  # blocked on the user lock
        await tx.commit()
        await asyncio.wait_for(archive, 10)
    finally:
        await deleter.close()

    assert await migrated_db.fetchval('SELECT COUNT(*) FROM leaderboard_snapshots WHERE user_id = $1', uid) == 0
    assert await migrated_db.fetchval('SELECT 1 FROM season_archives WHERE season_month = $1', season) == 1


@pytest.mark.asyncio(loop_scope='module')
async def test_module_switches_gate_accounting_in_sql(migrated_db, monkeypatch):
    from src.services import activity_service as svc

    monkeypatch.setattr(svc, 'db', migrated_db)
    guild, uid = 8401, 8402
    await migrated_db.execute("INSERT INTO guild_modules (guild_id, disabled) VALUES ($1, ARRAY['leveling'])", guild)
    await svc.award('message', [svc.Award(uid, guild, quantity=3, xp_base=30)])
    row = await migrated_db.fetch_one(
        'SELECT messages, xp_earned FROM user_activity_daily WHERE user_id = $1 AND guild_id = $2', uid, guild
    )
    assert row['messages'] == 3 and row['xp_earned'] == 0
    await migrated_db.execute("UPDATE guild_modules SET disabled = ARRAY['activity'] WHERE guild_id = $1", guild)
    await svc.award('message', [svc.Award(uid, guild, quantity=3, xp_base=30)])
    assert (
        await migrated_db.fetchval(
            'SELECT messages FROM user_activity_daily WHERE user_id = $1 AND guild_id = $2', uid, guild
        )
        == 3
    )
    await migrated_db.execute("UPDATE guild_modules SET disabled = '{}' WHERE guild_id = $1", guild)
    await svc.award('message', [svc.Award(uid, guild, quantity=1, xp_base=10)])
    row = await migrated_db.fetch_one(
        'SELECT messages, xp_earned FROM user_activity_daily WHERE user_id = $1 AND guild_id = $2', uid, guild
    )
    assert row['messages'] == 4 and row['xp_earned'] == 10
