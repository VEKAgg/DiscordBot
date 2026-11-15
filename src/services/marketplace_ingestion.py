"""Origin-scoped Discord observations, transactional image sets and outbox intents."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import nextcord

from src.database.database import Database, db
from src.services.marketplace_core import MarketplaceSync, decoded
from src.services.marketplace_images import image_store
from src.services.marketplace_service import validate_listing_text


def available_channels(interaction) -> list[int]:
    """Only channels the requesting member can actually read; replies must be ephemeral."""
    if interaction.guild is None or not isinstance(interaction.user, nextcord.Member):
        return []
    return [
        c.id
        for c in interaction.guild.channels
        if c.permissions_for(interaction.user).view_channel and c.permissions_for(interaction.user).read_message_history
    ]


# All discovered content is origin-guild scoped, authorized by current channel
# permissions AND fresh core publication policy. Owners may inspect their own
# pending observations, but never through a different guild.
READ_SCOPE = """l.guild_id=$1 AND l.origin_channel_id=ANY($2::bigint[]) AND (
    (l.status='active' AND NOT EXISTS (SELECT 1 FROM marketplace_core_sources s WHERE s.listing_id=l.id AND s.tombstone) AND l.core_visible AND l.core_moderation='approved' AND l.audience IN ('community','public')
     AND NOT l.is_expired AND (l.core_expires_at IS NULL OR l.core_expires_at>now())
     AND EXISTS (
        SELECT 1 FROM marketplace_core_bindings b WHERE b.guild_id=l.guild_id AND b.channel_id=l.origin_channel_id
        AND b.refreshed_at>now()-interval '300 seconds' AND b.body->>'enabled'='true'
        AND (l.audience<>'public' OR b.body->>'public_syndication_enabled'='true')))
    OR ($3::text IS NOT NULL AND u.discord_id=$3))"""


class MarketplaceIngestion:
    def __init__(self, sync: MarketplaceSync, database: Database = db):
        self.sync, self.db = sync, database

    async def save(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        author_id: int,
        source_kind: str,
        title: str,
        description: str,
        price: Decimal | None,
        currency: str | None,
        category_id: str | None,
        condition='unknown',
        attachments=(),
        edited_at=None,
        consent=None,
    ):
        binding = await self.sync.binding(guild_id, channel_id)
        if not binding:
            raise ValueError('This channel needs an enabled core marketplace binding. Try again after configuration.')
        categories = {c['id']: c for c in binding['categories'] if c['active']}
        if category_id is not None and category_id not in categories:
            raise ValueError('Choose an active category from this channel’s core taxonomy.')
        if consent and consent['audience'] == 'public' and not binding.get('public_syndication_enabled'):
            raise ValueError('Public syndication is not enabled for this channel.')
        title, description = validate_listing_text(title, description)
        listing_id = f'MP{message_id}'
        images = await image_store.prepare_attachments(listing_id, attachments)
        observation = {
            'source_kind': source_kind,
            'thread_id': str(message_id) if source_kind == 'forum' else None,
            'author_discord_id': str(author_id),
            'source_edited_at': edited_at.isoformat() if edited_at else None,
            'source_state': 'active',
            'policy_version': binding['policy_version'],
            'consent': consent,
            'owner_action': None,
            'proposed': {
                'title': title,
                'description_plaintext': description,
                'category_id': category_id,
                'kind': 'goods',
                'price': {
                    'kind': 'fixed' if price is not None else 'on_request',
                    'amount_minor': str(int(price * 100)) if price is not None else None,
                    'currency': currency if price is not None else None,
                    'confidence': 'explicit' if price is not None else 'unknown',
                },
                'condition': condition,
                'images': [],
            },
        }
        async with self.db.transaction() as conn:
            # Same source serializes across tasks/processes before touching projection or bytes.
            await conn.execute('SELECT pg_advisory_xact_lock($1)', message_id)
            await conn.execute('SELECT pg_advisory_xact_lock($1)', author_id)
            existing = await conn.fetchval('SELECT 1 FROM marketplace_core_sources WHERE listing_id=$1', listing_id)
            if not existing:
                count = await conn.fetchval(
                    'SELECT count(*) FROM marketplace_listings l JOIN users u ON u.id=l.seller_id WHERE u.discord_id=$1 '
                    "AND l.guild_id=$2 AND l.status IN ('active','pending_review','reserved')",
                    str(author_id),
                    guild_id,
                )
                if count >= 20:
                    raise ValueError('At most 20 open submissions per seller/server. Close an existing listing first.')
            seller = await conn.fetchval(
                'INSERT INTO users(discord_id) VALUES($1) ON CONFLICT(discord_id) DO UPDATE SET discord_id=EXCLUDED.discord_id RETURNING id',
                str(author_id),
            )
            local_category = await conn.fetchval(
                'SELECT id FROM marketplace_categories WHERE core_id=$1',
                uuid.UUID(category_id) if category_id else None,
            )
            await conn.execute(
                'INSERT INTO marketplace_listings(id,seller_id,title,description,price,category_id,condition,status,source,thread_id,guild_id,origin_channel_id,source_message_id,currency) '
                "VALUES($1,$2,$3,$4,$5,$6,$7,'pending_review',$8,$9,$10,$11,$12,$13) ON CONFLICT(id) DO NOTHING",
                listing_id,
                seller,
                title,
                description,
                price,
                local_category,
                condition,
                source_kind,
                message_id if source_kind == 'forum' else None,
                guild_id,
                channel_id,
                message_id,
                currency or 'USD',
            )
            row = await conn.fetchrow('SELECT * FROM marketplace_listings WHERE id=$1 FOR UPDATE', listing_id)
            if (row['seller_id'], row['guild_id'], row['origin_channel_id'], row['source_message_id']) != (
                seller,
                guild_id,
                channel_id,
                message_id,
            ):
                raise ValueError('The source identity cannot be changed.')
            await conn.execute(
                'INSERT INTO marketplace_core_sources(listing_id,guild_id,channel_id,message_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING',
                listing_id,
                guild_id,
                channel_id,
                message_id,
            )
            changed = await self.sync.enqueue(conn, listing_id, observation, images)
            if changed:
                # A source edit stages a revision; never show unreviewed new content as canonical.
                await conn.execute(
                    'UPDATE marketplace_listings SET title=$2,description=$3,price=$4,category_id=$5,condition=$6,currency=$7, '
                    "status='pending_review',core_moderation='pending',image_url=NULL WHERE id=$1 AND status NOT IN ('sold','withdrawn','removed')",
                    listing_id,
                    title,
                    description,
                    price,
                    local_category,
                    condition,
                    currency or 'USD',
                )
                await image_store.replace(conn, listing_id, images, message_id=message_id)
        return listing_id

    async def source_state(self, listing_id: str, state: str):
        if state not in {'archived', 'locked', 'deleted', 'unavailable'}:
            raise ValueError('Invalid source state')
        async with self.db.transaction() as conn:
            source = await conn.fetchrow('SELECT * FROM marketplace_core_sources WHERE listing_id=$1', listing_id)
            if source is None:
                return
            await conn.execute('SELECT pg_advisory_xact_lock($1)', source['message_id'])
            source = await conn.fetchrow(
                'SELECT * FROM marketplace_core_sources WHERE listing_id=$1 FOR UPDATE', listing_id
            )
            previous = await conn.fetchrow(
                'SELECT body FROM marketplace_core_outbox WHERE listing_id=$1 ORDER BY revision DESC LIMIT 1',
                listing_id,
            )
            body = decoded(previous['body'])
            observation = {
                k: v
                for k, v in body.items()
                if k not in {'schema_version', 'event_id', 'source_revision', 'observed_at'}
            }
            observation.update(source_state=state, proposed=None, consent=None, owner_action=None)
            await conn.execute(
                "UPDATE marketplace_listings SET status=$2,audience='private' WHERE id=$1",
                listing_id,
                'withdrawn' if state == 'deleted' else 'archived',
            )
            await self.sync.enqueue(conn, listing_id, observation, [])

    async def owner_action(self, listing_id: str, guild_id: int, author_id: int, interaction_id: int, action: str):
        if action not in {'withdraw', 'renew'}:
            raise ValueError('Invalid owner action')
        async with self.db.transaction() as conn:
            key = await conn.fetchval('SELECT message_id FROM marketplace_core_sources WHERE listing_id=$1', listing_id)
            if key is None:
                raise ValueError('Listing not found.')
            await conn.execute('SELECT pg_advisory_xact_lock($1)', key)
            row = await conn.fetchrow(
                'SELECT l.id FROM marketplace_listings l JOIN users u ON u.id=l.seller_id '
                'WHERE l.id=$1 AND l.guild_id=$2 AND u.discord_id=$3 FOR UPDATE',
                listing_id,
                guild_id,
                str(author_id),
            )
            if row is None:
                raise ValueError('Listing not found in this server or not owned by you.')
            source = await conn.fetchrow(
                'SELECT * FROM marketplace_core_sources WHERE listing_id=$1 FOR UPDATE', listing_id
            )
            if source is None or source['tombstone']:
                raise ValueError('This listing is closed.')
            previous = await conn.fetchrow(
                'SELECT body FROM marketplace_core_outbox WHERE listing_id=$1 ORDER BY revision DESC LIMIT 1',
                listing_id,
            )
            body = decoded(previous['body'])
            observation = {
                k: v
                for k, v in body.items()
                if k not in {'schema_version', 'event_id', 'source_revision', 'observed_at'}
            }
            observation['owner_action'] = {
                'action': action,
                'actor_discord_id': str(author_id),
                'interaction_id': str(interaction_id),
            }
            # Owner actions aren't content edits; retain the immutable desired image set.
            pictures = await conn.fetch(
                'SELECT source_attachment_id,bytes,sha256,width,height FROM marketplace_listing_images WHERE listing_id=$1 ORDER BY position',
                listing_id,
            )
            from src.services.marketplace_images import StoredImage

            images = [
                (p['source_attachment_id'], StoredImage(bytes(p['bytes']), p['sha256'], p['width'], p['height']))
                for p in pictures
            ]
            await self.sync.enqueue(conn, listing_id, observation, images)
            if action == 'withdraw':
                # Hide immediately locally; only canonical events can authorize subsequent public reads.
                await conn.execute(
                    "UPDATE marketplace_listings SET status='withdrawn',audience='private' WHERE id=$1", listing_id
                )

    async def rows(self, interaction, *, listing_id=None, mine=False, term='', category=None):
        if interaction.guild is None:
            return []
        channels = available_channels(interaction)
        args = [interaction.guild.id, channels, str(interaction.user.id) if mine or listing_id else None]
        sql = f'SELECT l.*,u.discord_id,c.name AS cat_name,c.emoji FROM marketplace_listings l JOIN users u ON u.id=l.seller_id LEFT JOIN marketplace_categories c ON c.id=l.category_id WHERE {READ_SCOPE}'
        if mine:
            sql += ' AND u.discord_id=$3'
        if listing_id:
            args.append(listing_id)
            sql += f' AND l.id=${len(args)}'
        if term:
            args.append(term[:200])
            sql += (
                f" AND (to_tsvector('english',l.title||' '||l.description) @@ plainto_tsquery('english',${len(args)}))"
            )
        if category:
            args.append(uuid.UUID(category))
            sql += f' AND c.core_id=${len(args)}'
        return await self.db.fetch(sql + ' ORDER BY l.created_at DESC,l.id DESC LIMIT 20', *args)

    @staticmethod
    def consent(interaction, audience: str, policy_version: str):
        return {
            'audience': audience,
            'actor_discord_id': str(interaction.user.id),
            'interaction_id': str(interaction.id),
            'accepted_at': datetime.now(UTC).isoformat(),
            'policy_version': policy_version,
        }
