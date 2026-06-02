import logging
from typing import Dict, List, Optional
from src.database.database import db, get_or_create_user

logger = logging.getLogger('VEKA.networking')


class NetworkingService:
    """PostgreSQL-backed service for profiles, connections, and connection requests."""

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    async def get_profile(self, discord_id: str) -> Optional[Dict]:
        row = await db.fetch_one(
            """
            SELECT p.*, u.discord_id
              FROM profiles p
              JOIN users u ON u.id = p.user_id
             WHERE u.discord_id = $1
            """,
            discord_id
        )
        return dict(row) if row else None

    async def upsert_profile(self, discord_id: str, data: Dict) -> None:
        user = await get_or_create_user(discord_id)
        await db.execute(
            """
            INSERT INTO profiles (user_id, title, skills, experience, looking_for, last_updated)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                title        = EXCLUDED.title,
                skills       = EXCLUDED.skills,
                experience   = EXCLUDED.experience,
                looking_for  = EXCLUDED.looking_for,
                last_updated = NOW()
            """,
            user['id'],
            data.get('title'),
            data.get('skills'),
            data.get('experience'),
            data.get('looking_for'),
        )

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    async def connection_exists(self, discord_id1: str, discord_id2: str) -> bool:
        row = await db.fetch_one(
            """
            SELECT 1 FROM connections c
              JOIN users u1 ON u1.id = c.user1_id
              JOIN users u2 ON u2.id = c.user2_id
             WHERE (u1.discord_id = $1 AND u2.discord_id = $2)
                OR (u1.discord_id = $2 AND u2.discord_id = $1)
            """,
            discord_id1, discord_id2
        )
        return row is not None

    async def create_connection(self, discord_id1: str, discord_id2: str) -> None:
        u1 = await get_or_create_user(discord_id1)
        u2 = await get_or_create_user(discord_id2)
        await db.execute(
            "INSERT INTO connections (user1_id, user2_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            u1['id'], u2['id']
        )

    async def get_connections(self, discord_id: str) -> List[Dict]:
        rows = await db.fetch_many(
            """
            SELECT
                CASE WHEN u1.discord_id = $1 THEN u2.discord_id ELSE u1.discord_id END AS other_discord_id,
                c.connected_at
              FROM connections c
              JOIN users u1 ON u1.id = c.user1_id
              JOIN users u2 ON u2.id = c.user2_id
             WHERE u1.discord_id = $1 OR u2.discord_id = $1
            """,
            discord_id
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Connection requests
    # ------------------------------------------------------------------

    async def get_pending_request(self, from_discord_id: str, to_discord_id: str) -> Optional[Dict]:
        row = await db.fetch_one(
            """
            SELECT cr.id, cr.message, cr.status, cr.created_at
              FROM connection_requests cr
              JOIN users r ON r.id = cr.requester_id
              JOIN users t ON t.id = cr.recipient_id
             WHERE r.discord_id = $1 AND t.discord_id = $2 AND cr.status = 'pending'
            """,
            from_discord_id, to_discord_id
        )
        return dict(row) if row else None

    async def create_request(self, from_discord_id: str, to_discord_id: str, message: str = '') -> None:
        requester = await get_or_create_user(from_discord_id)
        recipient = await get_or_create_user(to_discord_id)
        await db.execute(
            """
            INSERT INTO connection_requests (requester_id, recipient_id, message, status)
            VALUES ($1, $2, $3, 'pending')
            """,
            requester['id'], recipient['id'], message or 'Would like to connect with you!'
        )

    async def update_request_status(self, request_id: int, status: str) -> None:
        await db.execute(
            "UPDATE connection_requests SET status = $1 WHERE id = $2",
            status, request_id
        )
