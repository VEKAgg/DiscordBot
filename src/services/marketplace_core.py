"""Versioned marketplace transport and durable delivery to the canonical core.

No Discord URLs, user OAuth tokens or credentials are stored in queue payloads.
The service key authenticates an installation, never an arbitrary end user.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import aiohttp

from src.database.database import Database, db
from src.services.marketplace_images import StoredImage, validated_core_image

logger = logging.getLogger('VEKA.marketplace.core')
BASE = '/v1/integrations/marketplace'


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


class CoreError(Exception):
    def __init__(self, status: int, code: str, retry_after: int = 0):
        super().__init__(code)
        self.status, self.code, self.retry_after = status, code, min(3600, max(0, retry_after))


class CoreClient:
    def __init__(self, origin: str, key: str, installation: str):
        if origin:
            parts = urlsplit(origin)
            if parts.scheme not in {'https', 'http'} or not parts.hostname or parts.username or parts.password:
                raise ValueError('VEKA_CORE_URL must be an http(s) service origin without credentials')
            if parts.path not in {'', '/'} or parts.query or parts.fragment:
                raise ValueError('VEKA_CORE_URL must not contain a path, query or fragment')
        self.origin, self.key, self.installation = origin.rstrip('/'), key, installation
        self.session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.origin and self.key and self.installation)

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def request(self, method: str, path: str, *, body=None, data=None, key: str | None = None, binary=False):
        if not self.configured:
            raise CoreError(503, 'core_unconfigured')
        if not path.startswith(BASE + '/'):
            raise ValueError('Invalid marketplace integration path')
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=False)
        headers = {'X-Veka-Service-Key': self.key}
        if key:
            headers['Idempotency-Key'] = key
        try:
            async with self.session.request(
                method, self.origin + path, json=body, data=data, headers=headers, allow_redirects=False
            ) as response:
                cap = 2 * 1024 * 1024 if binary else 1024 * 1024
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > cap:
                        raise CoreError(502, 'core_response_too_large')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                if response.status >= 300:
                    try:
                        code = json.loads(raw).get('error', {}).get('code', 'core_error')
                        if not isinstance(code, str) or len(code) > 80 or not code.replace('_', '').isalnum():
                            code = 'core_error'
                    except (ValueError, AttributeError):
                        code = 'core_error'
                    retry = response.headers.get('Retry-After', '0')
                    raise CoreError(response.status, code, int(retry) if retry.isdecimal() else 0)
                if binary:
                    mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                    try:
                        return await asyncio.to_thread(validated_core_image, raw, mime)
                    except (ValueError, OSError):
                        raise CoreError(502, 'invalid_core_media') from None
                try:
                    result = json.loads(raw)
                except ValueError:
                    raise CoreError(502, 'invalid_core_json') from None
                if not isinstance(result, dict) or result.get('schema_version') != 1:
                    raise CoreError(502, 'invalid_core_schema')
                return result
        except (aiohttp.ClientError, TimeoutError):
            raise CoreError(503, 'core_unavailable') from None

    def event_key(self, source, revision) -> str:
        return (
            f'{self.installation}:discord:{source["guild_id"]}:{source["channel_id"]}:{source["message_id"]}:{revision}'
        )


class MarketplaceSync:
    def __init__(self, client: CoreClient, database: Database = db):
        self.client, self.db = client, database

    async def refresh_bindings(self):
        items: list[dict] = []
        cursor, seen = '', set()
        while True:
            from urllib.parse import urlencode

            reply = await self.client.request('GET', BASE + '/bindings?' + urlencode({'cursor': cursor, 'limit': 100}))
            batch = reply.get('items')
            if not isinstance(batch, list) or len(items) + len(batch) > 10000:
                raise CoreError(502, 'invalid_bindings')
            items.extend(batch)
            cursor = reply.get('next_cursor') or ''
            if not cursor:
                break
            if cursor in seen:
                raise CoreError(502, 'binding_cursor_loop')
            seen.add(cursor)
        # A complete snapshot replaces the cache, including revoked/removed bindings.
        async with self.db.transaction() as conn:
            await conn.execute('DELETE FROM marketplace_core_bindings')
            for binding in items:
                guild, channel = int(binding['guild_id']), int(binding['channel_id'])
                if binding.get('mode') not in {'forum', 'text'} or not isinstance(binding.get('categories'), list):
                    raise CoreError(502, 'invalid_bindings')
                await conn.execute(
                    'INSERT INTO marketplace_core_bindings(guild_id,channel_id,body) VALUES($1,$2,$3::jsonb)',
                    guild,
                    channel,
                    encode(binding),
                )
                for category in binding['categories']:
                    await conn.execute(
                        'INSERT INTO marketplace_categories(name,core_id,is_active) VALUES($1,$2,$3) '
                        'ON CONFLICT(core_id) DO UPDATE SET name=EXCLUDED.name,is_active=EXCLUDED.is_active',
                        category['name'],
                        uuid.UUID(category['id']),
                        bool(category['active']),
                    )

    async def binding(self, guild_id: int, channel_id: int):
        row = await self.db.fetch_one(
            'SELECT body FROM marketplace_core_bindings WHERE guild_id=$1 AND channel_id=$2 '
            "AND refreshed_at > now() - interval '300 seconds'",
            guild_id,
            channel_id,
        )
        binding = decoded(row['body']) if row else None
        return binding if binding and binding.get('enabled') is True else None

    async def enqueue(self, conn, listing_id: str, observation: dict, images: list[tuple[int, StoredImage]]):
        """Called inside the same transaction as the local observation/projection.

        Images are immutable per event. A transient capture failure must happen before
        entering this transaction, never publish a partial set or silently retain one.
        """
        source = await conn.fetchrow(
            'SELECT * FROM marketplace_core_sources WHERE listing_id=$1 FOR UPDATE', listing_id
        )
        if source is None:
            raise ValueError('Missing persisted Discord source')
        observation = dict(observation)
        digest_input = {'observation': observation, 'images': [(str(a), i.sha256) for a, i in images]}
        digest = hashlib.sha256(encode(digest_input).encode()).hexdigest()
        if source['tombstone'] and observation['source_state'] != 'deleted':
            return False
        if digest == source['observation_hash']:
            return False
        revision = max(source['revision'], source['accepted_revision']) + 1
        event = uuid.uuid4()
        body = {
            **observation,
            'schema_version': 1,
            'event_id': str(event),
            'source_revision': str(revision),
            'observed_at': datetime.now(UTC).isoformat(),
        }
        if body.get('proposed') is not None:
            body['proposed'] = {**body['proposed'], 'images': []}
        await conn.execute(
            'UPDATE marketplace_core_sources SET revision=$2,observation_hash=$3,tombstone=tombstone OR $4 WHERE listing_id=$1',
            listing_id,
            revision,
            digest,
            observation['source_state'] == 'deleted',
        )
        await conn.execute(
            'INSERT INTO marketplace_core_outbox(event_id,listing_id,revision,body) VALUES($1,$2,$3,$4::jsonb)',
            event,
            listing_id,
            revision,
            encode(body),
        )
        for position, (attachment_id, image) in enumerate(images):
            await conn.execute(
                'INSERT INTO marketplace_core_outbox_images(event_id,position,attachment_id,sha256,width,height,bytes) '
                'VALUES($1,$2,$3,$4,$5,$6,$7)',
                event,
                position,
                attachment_id,
                image.sha256,
                image.width,
                image.height,
                image.data,
            )
        return True

    async def claim(self):
        lease = uuid.uuid4()
        row = await self.db.fetch_one(
            "WITH due AS (SELECT event_id FROM marketplace_core_outbox WHERE status='pending' AND next_attempt_at<=now() "
            'AND (lease_until IS NULL OR lease_until<now()) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) '
            "UPDATE marketplace_core_outbox o SET lease_id=$1,lease_until=now()+interval '5 minutes',attempts=attempts+1 "
            'FROM due WHERE o.event_id=due.event_id RETURNING o.*',
            lease,
        )
        return row

    async def deliver_one(self):
        row = await self.claim()
        if row is None:
            return False
        source = await self.db.fetch_one(
            'SELECT * FROM marketplace_core_sources WHERE listing_id=$1', row['listing_id']
        )
        try:
            if source is None:
                raise ValueError('Missing source mapping')
            body = decoded(row['wire_body']) if row['wire_body'] else decoded(row['body'])
            key = self.client.event_key(source, row['revision'])
            if not row['wire_body']:
                images = await self.db.fetch(
                    'SELECT * FROM marketplace_core_outbox_images WHERE event_id=$1 ORDER BY position', row['event_id']
                )
                ready = []
                for picture in images:
                    asset = picture['asset_id']
                    if asset is None:
                        metadata = {
                            'schema_version': 1,
                            **{k: str(source[k]) for k in ('guild_id', 'channel_id', 'message_id')},
                            'attachment_id': str(picture['attachment_id']),
                            'sha256': picture['sha256'],
                            'width': picture['width'],
                            'height': picture['height'],
                        }
                        form = aiohttp.FormData()
                        form.add_field('metadata', encode(metadata), content_type='application/json')
                        form.add_field(
                            'file', bytes(picture['bytes']), filename='listing.webp', content_type='image/webp'
                        )
                        media_key = (
                            self.client.event_key(source, 'attachment')
                            + f':{picture["attachment_id"]}:{picture["sha256"]}:{row["revision"]}'
                        )
                        result = await self.client.request('POST', BASE + '/media', data=form, key=media_key)
                        if result.get('state') != 'ready' or result.get('source_sha256') != picture['sha256']:
                            raise CoreError(502, 'invalid_media_receipt')
                        asset = uuid.UUID(result['asset_id'])
                        await self.db.execute(
                            'UPDATE marketplace_core_outbox_images SET asset_id=$3 WHERE event_id=$1 AND position=$2',
                            row['event_id'],
                            picture['position'],
                            asset,
                        )
                    ready.append(
                        {
                            'asset_id': str(asset),
                            'position': picture['position'],
                            'alt': (body.get('proposed') or {}).get('title', ''),
                        }
                    )
                if body.get('proposed') is not None:
                    body['proposed']['images'] = ready
                # Freeze the exact wire body before the first PUT; never change it on retry.
                changed = await self.db.fetch_one(
                    'UPDATE marketplace_core_outbox SET wire_body=$3::jsonb WHERE event_id=$1 AND lease_id=$2 RETURNING event_id',
                    row['event_id'],
                    row['lease_id'],
                    encode(body),
                )
                if changed is None:
                    return True
            result = await self.client.request(
                'PUT',
                BASE + f'/sources/discord/{source["guild_id"]}/{source["channel_id"]}/{source["message_id"]}',
                body=body,
                key=key,
            )
            if result.get('outcome') not in {'applied', 'pending_review', 'unchanged', 'stale'}:
                raise CoreError(502, 'invalid_source_receipt')
            revision = int(result['accepted_source_revision'])
            if revision < row['revision']:
                raise CoreError(502, 'invalid_source_revision')
            async with self.db.transaction() as conn:
                await conn.execute('SELECT pg_advisory_xact_lock($1)', source['message_id'])
                done = await conn.fetchrow(
                    "UPDATE marketplace_core_outbox SET status='sent',delivered_at=now(),lease_until=NULL,error_code=NULL "
                    'WHERE event_id=$1 AND lease_id=$2 RETURNING event_id',
                    row['event_id'],
                    row['lease_id'],
                )
                if done:
                    await conn.execute(
                        'UPDATE marketplace_core_sources SET source_id=$2,accepted_revision=GREATEST(accepted_revision,$3) WHERE listing_id=$1',
                        row['listing_id'],
                        uuid.UUID(result['source_id']),
                        revision,
                    )
                    if result.get('listing_id'):
                        await conn.execute(
                            'UPDATE marketplace_listings SET core_listing_id=$2 WHERE id=$1',
                            row['listing_id'],
                            uuid.UUID(result['listing_id']),
                        )
        except CoreError as exc:
            status = (
                'blocked'
                if exc.status in {401, 403, 409, 410}
                else 'dead'
                if 400 <= exc.status < 500 and exc.status not in {408, 429}
                else 'pending'
            )
            delay = max(exc.retry_after, min(3600, 2 ** min(row['attempts'], 11)) + random.randint(0, 5))
            await self.db.execute(
                "UPDATE marketplace_core_outbox SET status=$3,error_code=$4,next_attempt_at=now()+$5::double precision*interval '1 second',lease_until=NULL "
                'WHERE event_id=$1 AND lease_id=$2',
                row['event_id'],
                row['lease_id'],
                status,
                exc.code,
                float(delay),
            )
            logger.warning('Marketplace delivery %s (%s); event retained', status, exc.code)
        except (KeyError, ValueError, TypeError):
            # A malformed successful response is a protocol failure, not acknowledged delivery.
            await self.db.execute(
                "UPDATE marketplace_core_outbox SET error_code='invalid_receipt',lease_until=NULL,next_attempt_at=now()+interval '1 minute' "
                'WHERE event_id=$1 AND lease_id=$2',
                row['event_id'],
                row['lease_id'],
            )
        return True

    async def retry_event(self, event_id: str, actor_id: int):
        event = uuid.UUID(event_id)
        async with self.db.transaction() as conn:
            source = await conn.fetchrow(
                'SELECT s.* FROM marketplace_core_sources s JOIN marketplace_core_outbox o ON o.listing_id=s.listing_id WHERE o.event_id=$1',
                event,
            )
            if source is None:
                raise ValueError('Event not found.')
            await conn.execute('SELECT pg_advisory_xact_lock($1)', source['message_id'])
            row = await conn.fetchrow('SELECT * FROM marketplace_core_outbox WHERE event_id=$1 FOR UPDATE', event)
            if row is None or row['status'] not in {'blocked', 'dead'}:
                raise ValueError('Only retained blocked/dead events can be retried.')
            if row['error_code'] in {'policy_changed', 'idempotency_conflict', 'revision_conflict'}:
                raise ValueError(
                    'This conflict requires a fresh source revision/consent, not replay of an old payload.'
                )
            if row['error_code'] == 'asset_expired':
                current_revision = await conn.fetchval(
                    'SELECT revision FROM marketplace_core_sources WHERE listing_id=$1 FOR UPDATE', source['listing_id']
                )
                if current_revision != row['revision']:
                    raise ValueError('A newer submission already exists; repair its event instead.')
                body = decoded(row['body'])
                observation = {
                    k: v
                    for k, v in body.items()
                    if k not in {'schema_version', 'event_id', 'source_revision', 'observed_at'}
                }
                pictures = await conn.fetch(
                    'SELECT * FROM marketplace_core_outbox_images WHERE event_id=$1 ORDER BY position', event
                )
                images = [
                    (p['attachment_id'], StoredImage(bytes(p['bytes']), p['sha256'], p['width'], p['height']))
                    for p in pictures
                ]
                await conn.execute(
                    'UPDATE marketplace_core_sources SET observation_hash=NULL WHERE listing_id=$1',
                    source['listing_id'],
                )
                await self.enqueue(conn, source['listing_id'], observation, images)
            else:
                await conn.execute(
                    "UPDATE marketplace_core_outbox SET status='pending',next_attempt_at=now(),lease_until=NULL WHERE event_id=$1",
                    event,
                )
            await conn.execute(
                "INSERT INTO audit_logs(user_id,action,details,severity) VALUES($1,'marketplace_queue_retry',$2::jsonb,'info')",
                str(actor_id),
                encode({'event_id': str(event)}),
            )

    async def apply_event(self, event: dict):
        """Persist/apply projection before the cursor is advanced. Never feed back into ingestion."""
        async with self.db.transaction() as conn:
            prior = await conn.fetchrow(
                'SELECT applied_at FROM marketplace_core_events WHERE event_id=$1', uuid.UUID(event['event_id'])
            )
            if prior and prior['applied_at']:
                return
            await conn.execute(
                'INSERT INTO marketplace_core_events(event_id,cursor,body) VALUES($1,$2,$3::jsonb) ON CONFLICT DO NOTHING',
                uuid.UUID(event['event_id']),
                event['cursor'],
                encode(event),
            )
            if event['type'] == 'listing.changed':
                listing_id = uuid.UUID(event['listing_id'])
                source_key = event.get('source_key')
                if source_key:
                    await conn.execute(
                        'UPDATE marketplace_listings SET core_listing_id=$4 WHERE guild_id=$1 AND origin_channel_id=$2 AND source_message_id=$3 '
                        'AND (core_listing_id IS NULL OR core_listing_id=$4)',
                        int(source_key['guild_id']),
                        int(source_key['channel_id']),
                        int(source_key['message_id']),
                        listing_id,
                    )
                version = int(event['canonical_version'])
                listing = event.get('listing')
                lifecycle = event['lifecycle']
                if lifecycle not in {'draft', 'active', 'reserved', 'sold', 'withdrawn', 'expired'}:
                    raise CoreError(502, 'invalid_lifecycle')
                await conn.execute(
                    'UPDATE marketplace_listings SET status=$2::text,core_moderation=$3,audience=$4,core_version=$5,core_expires_at=$6, '
                    "is_expired=($2::text='expired'),core_visible=$7 WHERE core_listing_id=$1 AND core_version<$5",
                    listing_id,
                    lifecycle if event['moderation'] != 'removed' else 'removed',
                    event['moderation'],
                    event['audience'],
                    version,
                    datetime.fromisoformat(event['expires_at'].replace('Z', '+00:00'))
                    if event.get('expires_at')
                    else None,
                    bool(listing) and (event['audience'] == 'community' or event['public_state'] == 'public'),
                )
                if listing:
                    price = listing['price']
                    from decimal import Decimal

                    await conn.execute(
                        'UPDATE marketplace_listings SET title=$2,description=$3,price=$4,currency=$5 '
                        'WHERE core_listing_id=$1 AND core_version=$6',
                        listing_id,
                        listing['title'],
                        listing['description_plaintext'],
                        Decimal(price['amount_minor']) / 100 if price['amount_minor'] is not None else None,
                        price['currency'] or 'USD',
                        version,
                    )
                    projection = await conn.fetchrow(
                        'SELECT id FROM marketplace_listings WHERE core_listing_id=$1 AND core_version=$2 FOR UPDATE',
                        listing_id,
                        version,
                    )
                    if projection:
                        approved_images = []
                        missing = False
                        for image in listing.get('images', []):
                            picture = await conn.fetchrow(
                                'SELECT i.* FROM marketplace_core_outbox_images i JOIN marketplace_core_outbox o ON o.event_id=i.event_id '
                                'WHERE o.listing_id=$1 AND i.asset_id=$2 ORDER BY o.revision DESC LIMIT 1',
                                projection['id'],
                                uuid.UUID(image['asset_id']),
                            )
                            if picture is None:
                                missing = True
                                break
                            approved_images.append(
                                (
                                    picture['attachment_id'],
                                    StoredImage(
                                        bytes(picture['bytes']), picture['sha256'], picture['width'], picture['height']
                                    ),
                                )
                            )
                        from src.services.marketplace_images import image_store

                        await image_store.replace(conn, projection['id'], approved_images if not missing else [])
                        await conn.execute(
                            'UPDATE marketplace_listings SET image_missing=$2 WHERE id=$1', projection['id'], missing
                        )
            elif event['type'] not in {'binding.changed', 'listing.publish', 'listing.unpublish'}:
                raise CoreError(502, 'unknown_marketplace_event')
            await conn.execute(
                'UPDATE marketplace_core_events SET applied_at=now() WHERE event_id=$1', uuid.UUID(event['event_id'])
            )

    async def poll_events(self, deliver):
        """One leased consumer: outbound delivery is retryable; never acknowledge a failed send."""
        lease = uuid.uuid4()
        consumer = await self.db.fetch_one(
            "UPDATE marketplace_core_consumer SET lease_id=$1,lease_until=now()+interval '5 minutes' "
            'WHERE id=TRUE AND (lease_until IS NULL OR lease_until<now()) RETURNING cursor,resnapshot',
            lease,
        )
        if consumer is None:
            return
        try:
            from urllib.parse import urlencode

            params = (
                {'resnapshot': 'true', 'limit': 10}
                if consumer['resnapshot']
                else {'after': consumer['cursor'], 'limit': 10}
            )
            if consumer['resnapshot']:
                await self.refresh_bindings()
                await self.reconcile()
            try:
                reply = await self.client.request('GET', BASE + '/events?' + urlencode(params))
            except CoreError as exc:
                if exc.status == 410:
                    await self.db.execute(
                        'UPDATE marketplace_core_consumer SET resnapshot=TRUE WHERE id=TRUE AND lease_id=$1', lease
                    )
                raise
            for event in reply['items']:
                if event['type'] == 'binding.changed':
                    await self.refresh_bindings()
                await self.apply_event(event)
                if event['type'] in {'listing.publish', 'listing.unpublish', 'listing.changed'}:
                    await deliver(event)
                await self.db.execute(
                    'UPDATE marketplace_core_consumer SET cursor=$2,updated_at=now() WHERE id=TRUE AND lease_id=$1',
                    lease,
                    event['cursor'],
                )
            cursor = reply['next_cursor']
            if cursor:
                await self.db.execute(
                    'UPDATE marketplace_core_consumer SET cursor=$2,resnapshot=FALSE WHERE id=TRUE AND lease_id=$1',
                    lease,
                    cursor,
                )
                await self.client.request(
                    'POST',
                    BASE + '/event-acks',
                    body={'schema_version': 1, 'cursor': cursor},
                    key=f'{self.client.installation}:marketplace-ack:{hashlib.sha256(cursor.encode()).hexdigest()}',
                )
        finally:
            await self.db.execute(
                'UPDATE marketplace_core_consumer SET lease_until=NULL WHERE id=TRUE AND lease_id=$1', lease
            )

    async def reconcile(self):
        """Compare receipts, including tombstones, without resurrecting source observations."""
        row = await self.db.fetch_one('SELECT reconcile_cursor FROM marketplace_core_consumer WHERE id=TRUE')
        if row is None:
            return
        from urllib.parse import urlencode

        reply = await self.client.request(
            'GET', BASE + '/sources?' + urlencode({'cursor': row['reconcile_cursor'], 'limit': 100})
        )
        async with self.db.transaction() as conn:
            for source in reply['items']:
                await conn.execute(
                    'UPDATE marketplace_core_sources SET accepted_revision=GREATEST(accepted_revision,$4),source_id=$5, '
                    'tombstone=tombstone OR $6 WHERE guild_id=$1 AND channel_id=$2 AND message_id=$3',
                    int(source['guild_id']),
                    int(source['channel_id']),
                    int(source['message_id']),
                    int(source['source_revision']),
                    uuid.UUID(source['source_id']),
                    source['source_state'] == 'deleted',
                )
            await conn.execute(
                'UPDATE marketplace_core_consumer SET reconcile_cursor=$1 WHERE id=TRUE', reply.get('next_cursor') or ''
            )


def configured_sync(database: Database = db):
    from src.config.config import VEKA_CORE_INSTALLATION_ID, VEKA_CORE_SERVICE_KEY, VEKA_CORE_URL

    return MarketplaceSync(CoreClient(VEKA_CORE_URL, VEKA_CORE_SERVICE_KEY, VEKA_CORE_INSTALLATION_ID), database)
