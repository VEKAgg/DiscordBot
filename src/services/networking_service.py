import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.database.database import db, get_or_create_user
from src.utils.embed_limits import text_units

logger = logging.getLogger('VEKA.networking')


def normalize_skills(value: str | list[str] | None) -> list[str]:
    parts = value.split(',') if isinstance(value, str) else value or []
    skills = list(dict.fromkeys(item.strip() for item in parts if item.strip()))
    if len(skills) > 20 or any(len(item) > 64 for item in skills):
        raise ValueError('Use at most 20 skills, each at most 64 characters.')
    return skills


def normalize_timezone(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Use a valid timezone, such as UTC or Europe/Berlin.') from None
    return value


class NetworkingService:
    """Database-backed networking service for profiles and connections."""

    async def _resolve_user_id(self, discord_id: str) -> int:
        user = await get_or_create_user(discord_id)
        return user['id']

    async def get_profile(self, discord_id: str) -> dict | None:
        return await db.fetch_one(
            """
            SELECT p.*, u.discord_id
            FROM profiles p
            JOIN users u ON p.user_id = u.id
            WHERE u.discord_id = $1
            """,
            discord_id,
        )

    async def upsert_profile(self, discord_id: str, data: dict) -> None:
        skills = normalize_skills(data.get('skills'))
        timezone = normalize_timezone(data.get('timezone'))
        user_id = await self._resolve_user_id(discord_id)
        await db.execute(
            """
            INSERT INTO profiles (user_id, title, skills, bio, links, looking_for, timezone, last_updated)
            VALUES ($1, $2, $3::text[], $4, $5, $6, $7, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                title = $2,
                skills = $3,
                bio = $4,
                links = $5,
                looking_for = $6,
                timezone = CASE WHEN $8::bool THEN $7 ELSE profiles.timezone END,
                last_updated = NOW()
            """,
            user_id,
            data.get('title'),
            skills,
            data.get('bio'),
            data.get('links'),
            data.get('looking_for'),
            timezone,
            'timezone' in data,
        )

    async def connection_exists(self, user1_id: str, user2_id: str) -> bool:
        owner_id = await self._resolve_user_id(user1_id)
        target_id = await self._resolve_user_id(user2_id)
        row = await db.fetch_one(
            """
            SELECT 1 FROM connections
            WHERE (user1_id = $1 AND user2_id = $2)
               OR (user1_id = $2 AND user2_id = $1)
            """,
            owner_id,
            target_id,
        )
        return row is not None

    async def has_pending_request(self, from_user_id: str, to_user_id: str) -> bool:
        requester_id = await self._resolve_user_id(from_user_id)
        recipient_id = await self._resolve_user_id(to_user_id)
        row = await db.fetch_one(
            """
            SELECT 1 FROM connection_requests
            WHERE requester_id = $1
              AND recipient_id = $2
              AND status = 'pending'
            """,
            requester_id,
            recipient_id,
        )
        return row is not None

    async def get_pending_request(self, from_user_id: str, to_user_id: str) -> dict | None:
        requester_id = await self._resolve_user_id(from_user_id)
        recipient_id = await self._resolve_user_id(to_user_id)
        return await db.fetch_one(
            """
            SELECT * FROM connection_requests
            WHERE requester_id = $1
              AND recipient_id = $2
              AND status = 'pending'
            """,
            requester_id,
            recipient_id,
        )

    async def get_requests_for_user(self, discord_id: str) -> list[dict]:
        user_id = await self._resolve_user_id(discord_id)
        return await db.fetch(
            """
            SELECT r.*, u1.discord_id AS requester_discord_id, u2.discord_id AS recipient_discord_id,
                   u1.id AS requester_user_id, u2.id AS recipient_user_id
            FROM connection_requests r
            JOIN users u1 ON r.requester_id = u1.id
            JOIN users u2 ON r.recipient_id = u2.id
            WHERE r.requester_id = $1 OR r.recipient_id = $1
            ORDER BY r.created_at DESC
            """,
            user_id,
        )

    async def create_request(self, from_user_id: str, to_user_id: str, message: str = '') -> int:
        if text_units(message) > 1000:
            raise ValueError('Connection messages must be at most 1000 characters.')
        requester_id = await self._resolve_user_id(from_user_id)
        recipient_id = await self._resolve_user_id(to_user_id)
        if requester_id == recipient_id:
            raise ValueError('You cannot send a connection request to yourself.')
        async with db.transaction() as conn:
            await self._lock_pair(conn, requester_id, recipient_id)
            connected = await conn.fetchval(
                'SELECT 1 FROM connections WHERE (user1_id = $1 AND user2_id = $2) '
                'OR (user1_id = $2 AND user2_id = $1)',
                requester_id,
                recipient_id,
            )
            if connected:
                raise ValueError('You are already connected with this member.')
            pending = await conn.fetchval(
                "SELECT 1 FROM connection_requests WHERE status = 'pending' AND "
                '((requester_id = $1 AND recipient_id = $2) OR (requester_id = $2 AND recipient_id = $1))',
                requester_id,
                recipient_id,
            )
            if pending:
                raise ValueError('A pending request already exists between you. Accept or decline it first.')
            return await conn.fetchval(
                'INSERT INTO connection_requests (requester_id, recipient_id, message, status, created_at) '
                "VALUES ($1, $2, $3, 'pending', NOW()) RETURNING id",
                requester_id,
                recipient_id,
                message or 'Would like to connect with you!',
            )

    @staticmethod
    async def _lock_pair(conn, first: int, second: int) -> None:
        key = f'connection:{min(first, second)}:{max(first, second)}'
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))', key)

    async def respond_request(self, request_id: int, recipient_discord_id: str, *, accept: bool) -> bool:
        # Read immutable participants first to acquire the pair lock in the same order as creation.
        request = await db.fetch_one(
            'SELECT requester_id, recipient_id FROM connection_requests WHERE id = $1', request_id
        )
        if request is None:
            return False
        async with db.transaction() as conn:
            await self._lock_pair(conn, request['requester_id'], request['recipient_id'])
            changed = await conn.fetchrow(
                'UPDATE connection_requests r SET status = $3 FROM users u '
                "WHERE r.id = $1 AND r.status = 'pending' AND r.recipient_id = u.id AND u.discord_id = $2 "
                'RETURNING r.requester_id, r.recipient_id',
                request_id,
                recipient_discord_id,
                'accepted' if accept else 'declined',
            )
            if changed is None:
                return False
            if accept:
                await conn.execute(
                    'INSERT INTO connections (user1_id, user2_id, connected_at) '
                    'SELECT $1, $2, NOW() WHERE NOT EXISTS ('
                    'SELECT 1 FROM connections WHERE (user1_id = $1 AND user2_id = $2) '
                    'OR (user1_id = $2 AND user2_id = $1))',
                    min(changed['requester_id'], changed['recipient_id']),
                    max(changed['requester_id'], changed['recipient_id']),
                )
        return True

    async def get_pending_requests(self, *, after_id: int = 0, limit: int = 500) -> list[dict]:
        if type(after_id) is not int or after_id < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Use a nonnegative request cursor and page size 1–500.')
        return await db.fetch(
            'SELECT r.id, u1.discord_id AS requester_discord_id, u2.discord_id AS recipient_discord_id '
            'FROM connection_requests r JOIN users u1 ON u1.id = r.requester_id '
            "JOIN users u2 ON u2.id = r.recipient_id WHERE r.status = 'pending' AND r.id > $1 "
            'ORDER BY r.id LIMIT $2',
            after_id,
            limit,
        )

    async def get_connections(self, discord_id: str) -> list[dict]:
        user_id = await self._resolve_user_id(discord_id)
        return await db.fetch(
            """
            SELECT c.*, u1.discord_id AS user1_discord_id, u2.discord_id AS user2_discord_id
            FROM connections c
            LEFT JOIN users u1 ON c.user1_id = u1.id
            LEFT JOIN users u2 ON c.user2_id = u2.id
            WHERE c.user1_id = $1 OR c.user2_id = $1
            ORDER BY c.connected_at DESC
            """,
            user_id,
        )

    async def get_connection_count(self, discord_id: str) -> int:
        user_id = await self._resolve_user_id(discord_id)
        row = await db.fetch_one(
            """
            SELECT COUNT(*) AS cnt FROM connections
            WHERE user1_id = $1 OR user2_id = $1
            """,
            user_id,
        )
        return row['cnt'] if row else 0

    async def get_mutual_connections(self, user1_discord_id: str, user2_discord_id: str) -> list[str]:
        conns1 = await self.get_connections(user1_discord_id)
        conns2 = await self.get_connections(user2_discord_id)

        def _other_ids(conns: list[dict], uid: str) -> set[str]:
            ids: set[str] = set()
            for c in conns:
                other = c['user2_discord_id'] if c['user1_discord_id'] == uid else c['user1_discord_id']
                if other:
                    ids.add(other)
            return ids

        ids1 = _other_ids(conns1, user1_discord_id)
        ids2 = _other_ids(conns2, user2_discord_id)
        return sorted(ids1 & ids2)

    async def get_seller_stats(self, discord_id: str) -> dict | None:
        user_id = await self._resolve_user_id(discord_id)
        return await db.fetch_one(
            """
            SELECT total_sales, total_revenue, average_rating, review_count
            FROM marketplace_seller_stats WHERE user_id = $1
            """,
            user_id,
        )

    async def append_profile_link(self, discord_id: str, url: str) -> None:
        profile = await self.get_profile(discord_id)
        existing_links = (profile.get('links') or '') if profile else ''
        link_list = [lnk.strip() for lnk in existing_links.splitlines() if lnk.strip()]
        if url in link_list:
            return
        link_list.append(url)
        new_links = '\n'.join(link_list)
        if profile:
            user_id = await self._resolve_user_id(discord_id)
            await db.execute(
                'UPDATE profiles SET links = $1, last_updated = NOW() WHERE user_id = $2',
                new_links,
                user_id,
            )
