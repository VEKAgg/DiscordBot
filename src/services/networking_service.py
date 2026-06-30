import logging

from src.database.database import db, get_or_create_user

logger = logging.getLogger('VEKA.networking')


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
        user_id = await self._resolve_user_id(discord_id)
        await db.execute(
            """
            INSERT INTO profiles (user_id, title, skills, bio, links, looking_for, last_updated)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                title = $2,
                skills = $3,
                bio = $4,
                links = $5,
                looking_for = $6,
                last_updated = NOW()
            """,
            user_id,
            data.get('title'),
            data.get('skills'),
            data.get('bio'),
            data.get('links'),
            data.get('looking_for'),
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

    async def create_request(self, from_user_id: str, to_user_id: str, message: str = '') -> None:
        requester_id = await self._resolve_user_id(from_user_id)
        recipient_id = await self._resolve_user_id(to_user_id)
        if requester_id == recipient_id:
            raise ValueError('You cannot send a connection request to yourself.')

        if await self.connection_exists(from_user_id, to_user_id):
            raise ValueError('You are already connected with this member.')

        if await self.has_pending_request(from_user_id, to_user_id):
            raise ValueError('You already have a pending request to this member.')

        if await self.has_pending_request(to_user_id, from_user_id):
            raise ValueError('There is already a pending request from this member. Accept it or decline it first.')

        await db.execute(
            """
            INSERT INTO connection_requests (requester_id, recipient_id, message, status, created_at)
            VALUES ($1, $2, $3, 'pending', NOW())
            """,
            requester_id,
            recipient_id,
            message or 'Would like to connect with you!',
        )

    async def create_connection(self, user1_discord_id: str, user2_discord_id: str) -> None:
        user1_id = await self._resolve_user_id(user1_discord_id)
        user2_id = await self._resolve_user_id(user2_discord_id)
        if user1_id == user2_id:
            return
        if await self.connection_exists(user1_discord_id, user2_discord_id):
            return
        await db.execute(
            """
            INSERT INTO connections (user1_id, user2_id, connected_at)
            VALUES ($1, $2, NOW())
            """,
            user1_id,
            user2_id,
        )

    async def update_request_status(self, request_id: int, status: str) -> None:
        await db.execute(
            """
            UPDATE connection_requests
            SET status = $1
            WHERE id = $2
            """,
            status,
            request_id,
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
