"""Real PostgreSQL queue/revision/isolation tests with a fake canonical core."""

import asyncio
import copy
import os
import uuid
from decimal import Decimal
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

from src.database.database import Database
from src.services.marketplace_core import BASE, CoreClient, CoreError, MarketplaceSync, decoded
from src.services.marketplace_ingestion import MarketplaceIngestion

DSN = os.getenv('VEKA_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DSN, reason='disposable PostgreSQL required')
CATEGORY = '019a0000-0000-7000-8000-000000000002'
INSTALLATION = '019a0000-0000-7000-8000-000000000001'


class FakeCore:
    installation = INSTALLATION
    configured = True

    def __init__(self):
        self.calls = []
        self.receipts = {}
        self.revision = 0
        self.lose_reply = False
        self.failure = None
        self.events = []
        self.binding = {
            'guild_id': '77',
            'channel_id': '78',
            'community_id': INSTALLATION,
            'mode': 'forum',
            'enabled': True,
            'public_syndication_enabled': False,
            'publication_enabled': False,
            'policy_version': '1',
            'categories': [{'id': CATEGORY, 'name': 'Other', 'slug': 'other', 'active': True}],
            'tag_categories': [],
            'default_category_id': CATEGORY,
        }

    def event_key(self, source, revision):
        return CoreClient('', '', INSTALLATION).event_key(source, revision)

    async def request(self, method, path, *, body=None, key=None, data=None):
        if path == BASE + '/media':
            assert data is not None
            import json

            metadata = json.loads(data._fields[0][2])
            assert data._fields[1][1]['Content-Type'] == 'image/webp'
            self.calls.append((method, path, metadata, key))
            return {
                'schema_version': 1,
                'request_id': 'fake',
                'state': 'ready',
                'source_sha256': metadata['sha256'],
                'asset_id': '019a0000-0000-7000-8000-000000000005',
            }
        assert data is None
        self.calls.append((method, path, copy.deepcopy(body), key))
        if self.failure:
            raise self.failure
        if path.startswith(BASE + '/bindings'):
            return {'schema_version': 1, 'request_id': 'fake', 'items': [self.binding], 'next_cursor': None}
        if path.startswith(BASE + '/sources/discord/'):
            revision = int(body['source_revision'])
            if key not in self.receipts:
                self.revision = max(self.revision, revision)
                self.receipts[key] = {
                    'schema_version': 1,
                    'request_id': 'fake',
                    'source_id': '019a0000-0000-7000-8000-000000000003',
                    'listing_id': '019a0000-0000-7000-8000-000000000004',
                    'accepted_source_revision': str(self.revision),
                    'canonical_version': '1',
                    'outcome': 'pending_review',
                    'public_state': 'hidden',
                    'warnings': [],
                }
            if self.lose_reply:
                self.lose_reply = False
                raise CoreError(503, 'reply_lost')
            return self.receipts[key]
        if path.startswith(BASE + '/sources?'):
            return {'schema_version': 1, 'request_id': 'fake', 'items': [], 'next_cursor': None}
        if path.startswith(BASE + '/events'):
            return {
                'schema_version': 1,
                'request_id': 'fake',
                'items': self.events,
                'next_cursor': self.events[-1]['cursor']
                if self.events
                else ('snapshot-0' if 'resnapshot=true' in path else ''),
            }
        if path.endswith('/event-acks'):
            return {'schema_version': 1, 'request_id': 'fake', 'acknowledged_cursor': body['cursor']}
        raise AssertionError(path)


@pytest_asyncio.fixture
async def integration(monkeypatch):
    assert DSN
    admin = await asyncpg.connect(DSN)
    name = 'marketplace_' + uuid.uuid4().hex
    await admin.execute('CREATE DATABASE ' + name)
    url = urlsplit(DSN)
    database = Database()
    database.pool = await asyncpg.create_pool(
        urlunsplit((url.scheme, url.netloc, '/' + name, url.query, url.fragment)), min_size=1, max_size=8
    )
    try:
        await database.run_migrations()
        monkeypatch.setattr('src.services.marketplace_images.db', database)
        fake = FakeCore()
        sync = MarketplaceSync(cast(CoreClient, fake), database)
        await sync.refresh_bindings()
        yield database, fake, sync, MarketplaceIngestion(sync, database)
    finally:
        await database.close()
        await admin.execute('DROP DATABASE ' + name + ' WITH (FORCE)')
        await admin.close()


async def observe(repository, **changes):
    args = dict(
        guild_id=77,
        channel_id=78,
        message_id=79,
        author_id=80,
        source_kind='forum',
        title='Example keyboard',
        description='Details',
        price=Decimal('12.34'),
        currency='AED',
        category_id=CATEGORY,
    )
    args.update(changes)
    return await repository.save(**args)


async def test_observation_and_outbox_atomic_idempotent_and_origin_preserved(integration):
    database, fake, sync, repository = integration
    listing = await observe(repository)
    await observe(repository)
    row = await database.fetch_one(
        'SELECT guild_id,origin_channel_id,status,audience FROM marketplace_listings WHERE id=$1', listing
    )
    assert dict(row) == {'guild_id': 77, 'origin_channel_id': 78, 'status': 'pending_review', 'audience': 'private'}
    assert await database.fetchval('SELECT count(*) FROM marketplace_core_outbox') == 1
    body = decoded(await database.fetchval('SELECT body FROM marketplace_core_outbox'))
    assert body['source_revision'] == '1'
    assert body['proposed']['price'] == {
        'kind': 'fixed',
        'amount_minor': '1234',
        'currency': 'AED',
        'confidence': 'explicit',
    }
    assert body['consent'] is None and 'image_url' not in str(body)
    with pytest.raises(ValueError, match='identity'):
        await observe(repository, author_id=81)
    assert await database.fetchval('SELECT count(*) FROM marketplace_core_outbox') == 1


async def test_lost_receipt_retries_identical_key_body_without_duplicate_core_create(integration):
    database, fake, sync, repository = integration
    await observe(repository)
    fake.lose_reply = True
    assert await sync.deliver_one()
    assert await database.fetchval('SELECT status FROM marketplace_core_outbox') == 'pending'
    await database.execute('UPDATE marketplace_core_outbox SET next_attempt_at=now()')
    assert await sync.deliver_one()
    assert await database.fetchval('SELECT status FROM marketplace_core_outbox') == 'sent'
    calls = [c for c in fake.calls if c[0] == 'PUT']
    assert len(calls) == 2 and calls[0][2:] == calls[1][2:]
    assert len(fake.receipts) == 1
    assert await database.fetchval('SELECT accepted_revision FROM marketplace_core_sources') == 1


async def test_two_workers_cannot_claim_the_same_event(integration):
    database, fake, sync, repository = integration
    await observe(repository)
    await asyncio.gather(sync.deliver_one(), MarketplaceSync(cast(CoreClient, fake), database).deliver_one())
    assert len([c for c in fake.calls if c[0] == 'PUT']) == 1
    assert await database.fetchval('SELECT status FROM marketplace_core_outbox') == 'sent'


async def test_delete_tombstone_wins_over_late_active_observation(integration):
    database, fake, sync, repository = integration
    listing = await observe(repository)
    await repository.source_state(listing, 'deleted')
    await observe(repository, title='Old gateway event')
    assert await database.fetchval('SELECT count(*) FROM marketplace_core_outbox') == 2
    assert await database.fetchval('SELECT tombstone FROM marketplace_core_sources')
    assert await database.fetchval('SELECT status FROM marketplace_listings') == 'withdrawn'


async def test_retry_after_and_permanent_failure_are_durable(integration):
    database, fake, sync, repository = integration
    await observe(repository)
    fake.failure = CoreError(429, 'rate_limited', 60)
    await sync.deliver_one()
    assert await database.fetchval("SELECT next_attempt_at>now()+interval '50 seconds' FROM marketplace_core_outbox")
    await database.execute('UPDATE marketplace_core_outbox SET next_attempt_at=now()')
    fake.failure = CoreError(422, 'invalid_input')
    await sync.deliver_one()
    assert await database.fetchval('SELECT status FROM marketplace_core_outbox') == 'dead'
    assert await database.fetchval('SELECT error_code FROM marketplace_core_outbox') == 'invalid_input'


async def test_binding_expiry_and_public_consent_fail_closed(integration):
    database, fake, sync, repository = integration
    with pytest.raises(ValueError, match='Public syndication'):
        await observe(repository, consent={'audience': 'public'})
    await database.execute("UPDATE marketplace_core_bindings SET refreshed_at=now()-interval '6 minutes'")
    assert await sync.binding(77, 78) is None
    with pytest.raises(ValueError, match='binding'):
        await observe(repository)
    assert await database.fetchval('SELECT count(*) FROM marketplace_core_sources') == 0


async def test_canonical_event_is_applied_before_ack_and_not_reingested(integration):
    database, fake, sync, repository = integration
    await observe(repository)
    await sync.deliver_one()
    fake.events = [
        {
            'event_id': str(uuid.uuid4()),
            'cursor': 'cursor-1',
            'type': 'listing.changed',
            'listing_id': '019a0000-0000-7000-8000-000000000004',
            'canonical_version': '2',
            'source_id': '019a0000-0000-7000-8000-000000000003',
            'source_key': {'guild_id': '77', 'channel_id': '78', 'message_id': '79'},
            'lifecycle': 'withdrawn',
            'moderation': 'approved',
            'audience': 'private',
            'public_state': 'hidden',
            'expires_at': None,
            'listing': None,
            'delivery': None,
        }
    ]

    async def deliver(_event):
        assert await database.fetchval('SELECT status FROM marketplace_listings') == 'withdrawn'
        assert not [c for c in fake.calls if c[1].endswith('/event-acks')]

    await sync.poll_events(deliver)
    assert await database.fetchval('SELECT cursor FROM marketplace_core_consumer') == 'cursor-1'
    assert len([c for c in fake.calls if c[1].endswith('/event-acks')]) == 1
    assert await database.fetchval('SELECT count(*) FROM marketplace_core_outbox') == 1


async def test_failed_reverse_delivery_is_not_acknowledged(integration):
    database, fake, sync, repository = integration
    fake.events = [{'event_id': str(uuid.uuid4()), 'cursor': 'cursor-1', 'type': 'binding.changed'}]

    async def fail(_event):
        raise CoreError(503, 'discord_unavailable')

    # A changed listing triggers the delivery callback; binding-only does not.
    fake.events[0].update(
        type='listing.unpublish',
        listing_id=str(uuid.uuid4()),
        canonical_version='1',
        delivery={'publication_key': 'one'},
    )
    with pytest.raises(CoreError):
        await sync.poll_events(fail)
    assert await database.fetchval('SELECT cursor FROM marketplace_core_consumer') == ''
    assert not [c for c in fake.calls if c[1].endswith('/event-acks')]


async def test_images_use_frozen_bytes_not_signed_urls_and_wire_retries_are_stable(integration, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.services.marketplace_images import StoredImage

    database, fake, sync, repository = integration
    image = StoredImage(b'normalized-webp-bytes', 'a' * 64, 10, 20)
    monkeypatch.setattr('src.services.marketplace_images.download_image', AsyncMock(return_value=image))
    attachment = SimpleNamespace(
        id=81, content_type='image/png', url='https://cdn.discordapp.com/private?signature=not-for-core'
    )
    await observe(repository, attachments=[attachment])
    fake.lose_reply = True
    await sync.deliver_one()
    await database.execute('UPDATE marketplace_core_outbox SET next_attempt_at=now()')
    await sync.deliver_one()
    assert len([c for c in fake.calls if c[1] == BASE + '/media']) == 1
    calls = [c for c in fake.calls if c[0] == 'PUT']
    assert len(calls) == 2 and calls[0][2:] == calls[1][2:]
    assert calls[0][2]['proposed']['images'][0]['asset_id'] == '019a0000-0000-7000-8000-000000000005'
    assert 'signature' not in str(calls)


async def test_real_sql_visibility_is_origin_channel_and_canonical_state_scoped(integration, mock_interaction):
    from unittest.mock import MagicMock

    import nextcord

    database, fake, sync, repository = integration
    await observe(repository)
    await database.execute(
        "UPDATE marketplace_listings SET status='active',core_moderation='approved',core_visible=TRUE,audience='community'"
    )
    channel = MagicMock()
    channel.id = 78
    channel.permissions_for.return_value = nextcord.Permissions(view_channel=True, read_message_history=True)
    mock_interaction.guild.channels = [channel]
    mock_interaction.guild.id = 77
    mock_interaction.user.id = 81
    assert len(await repository.rows(mock_interaction)) == 1
    mock_interaction.guild.id = 88
    assert await repository.rows(mock_interaction, listing_id='MP79') == []
    mock_interaction.guild.id = 77
    channel.permissions_for.return_value = nextcord.Permissions.none()
    assert await repository.rows(mock_interaction, listing_id='MP79') == []
    channel.permissions_for.return_value = nextcord.Permissions(view_channel=True, read_message_history=True)
    await database.execute('UPDATE marketplace_listings SET core_visible=FALSE')
    assert await repository.rows(mock_interaction) == []


async def test_concurrent_observations_keep_durable_unique_revisions(integration):
    database, fake, sync, repository = integration
    await asyncio.gather(*(observe(repository, title=f'Keyboard revision {i}') for i in range(5)))
    revisions = await database.fetch('SELECT revision FROM marketplace_core_outbox ORDER BY revision')
    assert [r['revision'] for r in revisions] == [1, 2, 3, 4, 5]
    assert await database.fetchval('SELECT count(*) FROM marketplace_listings') == 1


async def test_quota_is_atomic_for_concurrent_submissions(integration):
    database, fake, sync, repository = integration
    results = await asyncio.gather(
        *(observe(repository, message_id=100 + i) for i in range(22)), return_exceptions=True
    )
    assert sum(isinstance(r, ValueError) for r in results) == 2
    assert await database.fetchval('SELECT count(*) FROM marketplace_core_outbox') == 20


async def test_hidden_canonical_event_cannot_expose_locally_retained_source(integration, mock_interaction):
    database, fake, sync, repository = integration
    await observe(repository)
    await sync.deliver_one()
    await database.execute(
        "UPDATE marketplace_listings SET status='active',core_moderation='approved',core_visible=TRUE,audience='public'"
    )
    await sync.apply_event(
        {
            'event_id': str(uuid.uuid4()),
            'cursor': 'hidden-1',
            'type': 'listing.changed',
            'listing_id': '019a0000-0000-7000-8000-000000000004',
            'canonical_version': '2',
            'lifecycle': 'active',
            'moderation': 'approved',
            'audience': 'public',
            'public_state': 'hidden',
            'expires_at': None,
            'listing': None,
            'source_key': None,
        }
    )
    assert not await database.fetchval('SELECT core_visible FROM marketplace_listings')
    mock_interaction.guild.id = 77
    assert await repository.rows(mock_interaction) == []


async def test_expired_asset_repair_is_a_new_revision_not_mutated_put(integration, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.services.marketplace_images import StoredImage

    database, fake, sync, repository = integration
    image = StoredImage(b'normalized', 'b' * 64, 10, 20)
    monkeypatch.setattr('src.services.marketplace_images.download_image', AsyncMock(return_value=image))
    await observe(
        repository,
        attachments=[SimpleNamespace(id=81, content_type='image/png', url='https://cdn.discordapp.com/image')],
    )
    fake.failure = CoreError(410, 'asset_expired')
    await sync.deliver_one()
    event = await database.fetch_one('SELECT event_id,wire_body FROM marketplace_core_outbox')
    old_wire = event['wire_body']
    await sync.retry_event(str(event['event_id']), 999)
    fake.failure = None
    await sync.deliver_one()
    assert (
        await database.fetchval('SELECT wire_body FROM marketplace_core_outbox WHERE event_id=$1', event['event_id'])
        == old_wire
    )
    assert await database.fetchval('SELECT max(revision) FROM marketplace_core_outbox') == 2
    keys = [c[3] for c in fake.calls if c[1] == BASE + '/media']
    assert len(keys) == 2 and keys[0].endswith(':1') and keys[1].endswith(':2')


async def test_expired_event_cursor_resnapshots_then_follows_normal_after(integration):
    database, fake, sync, repository = integration

    async def deliver(_event):
        return None

    fake.failure = CoreError(410, 'cursor_expired')
    with pytest.raises(CoreError):
        await sync.poll_events(deliver)
    assert await database.fetchval('SELECT resnapshot FROM marketplace_core_consumer')
    fake.failure = None
    await sync.poll_events(deliver)
    assert await database.fetchval('SELECT cursor FROM marketplace_core_consumer') == 'snapshot-0'
    assert not await database.fetchval('SELECT resnapshot FROM marketplace_core_consumer')
    await sync.poll_events(deliver)
    paths = [c[1] for c in fake.calls if c[1].startswith(BASE + '/events')]
    assert 'resnapshot=true' in paths[-2] and 'after=snapshot-0' in paths[-1]
