import logging
from typing import Dict, List, Optional

from src.config.config import MENTORSHIP_CATEGORIES, POINTS_CONFIG
from src.database.database import db, get_or_create_user

logger = logging.getLogger('VEKA.mentorship')


class MentorshipService:
    def __init__(self, bot):
        self.bot = bot

    async def _resolve_user_id(self, discord_id: str) -> int:
        user = await get_or_create_user(discord_id)
        return user['id']

    async def create_mentorship_request(self, mentor_id: str, mentee_id: str, category: str) -> Dict:
        if category not in MENTORSHIP_CATEGORIES:
            raise ValueError(f"Invalid category. Must be one of: {', '.join(MENTORSHIP_CATEGORIES)}")

        existing = await self.get_active_mentorship(mentor_id, mentee_id)
        if existing:
            raise ValueError("There's already an active mentorship between these users")

        mentor_user_id = await self._resolve_user_id(mentor_id)
        mentee_user_id = await self._resolve_user_id(mentee_id)

        mentorship = await db.fetch_one(
            """
            INSERT INTO mentorships (mentor_id, mentee_id, category, status, created_at, updated_at)
            VALUES ($1, $2, $3, 'pending', NOW(), NOW())
            RETURNING *
            """,
            mentor_user_id,
            mentee_user_id,
            category,
        )
        return mentorship

    async def accept_mentorship(self, mentorship_id: int, mentor_id: str) -> Dict:
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError('Mentorship not found')

        mentor_user_id = await self._resolve_user_id(mentor_id)
        if mentorship['mentor_id'] != mentor_user_id:
            raise ValueError('Only the mentor can accept this request')

        if mentorship['status'] != 'pending':
            raise ValueError(f"Cannot accept mentorship with status: {mentorship['status']}")

        await db.execute(
            """
            UPDATE mentorships
            SET status = 'active', updated_at = NOW()
            WHERE id = $1
            """,
            mentorship_id,
        )

        mentorship['status'] = 'active'
        return mentorship

    async def complete_mentorship(self, mentorship_id: int, mentor_id: str) -> Dict:
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError('Mentorship not found')

        mentor_user_id = await self._resolve_user_id(mentor_id)
        if mentorship['mentor_id'] != mentor_user_id:
            raise ValueError('Only the mentor can complete this mentorship')

        if mentorship['status'] != 'active':
            raise ValueError(f"Cannot complete mentorship with status: {mentorship['status']}")

        await db.execute(
            """
            UPDATE mentorships
            SET status = 'completed', updated_at = NOW()
            WHERE id = $1
            """,
            mentorship_id,
        )
        return dict(row)

        points = POINTS_CONFIG['mentor_session']
        await db.execute(
            """
            UPDATE users
            SET points = points + $1
            WHERE id = ANY($2::int[])
            """,
            points,
            [mentor_user_id, mentorship['mentee_id']],
        )

        mentorship['status'] = 'completed'
        return mentorship

    async def get_mentorship(self, mentorship_id: int) -> Optional[Dict]:
        return await db.fetch_one(
            'SELECT * FROM mentorships WHERE id = $1',
            mentorship_id,
        )

    async def get_active_mentorship(self, mentor_id: str, mentee_id: str) -> Optional[Dict]:
        mentor_user_id = await self._resolve_user_id(mentor_id)
        mentee_user_id = await self._resolve_user_id(mentee_id)
        return await db.fetch_one(
            """
            SELECT * FROM mentorships
            WHERE mentor_id = $1
              AND mentee_id = $2
              AND status IN ('pending', 'active')
            """,
            mentor_user_id,
            mentee_user_id,
        )

    async def get_user_mentorships(self, user_id: str, status: Optional[str] = None) -> List[Dict]:
        resolved_id = await self._resolve_user_id(user_id)
        query = """
            SELECT *
            FROM mentorships
            WHERE (mentor_id = $1 OR mentee_id = $1)
        """
        params = [resolved_id]

        if status:
            query += " AND status = $2"
            params.append(status)

        return await db.fetch(query, *params)

    async def find_mentors(self, category: str) -> List[Dict]:
        return await db.fetch(
            """
            SELECT u.discord_id,
                   COUNT(*) AS completed_mentorships,
                   COALESCE(u.points, 0) AS points
            FROM mentorships m
            JOIN users u ON m.mentor_id = u.id
            WHERE m.category = $1
              AND m.status = 'completed'
            GROUP BY u.discord_id, u.points
            ORDER BY completed_mentorships DESC
            LIMIT 10
            """,
            category,
        )

    async def get_completed_mentorships(self, user_id: str, as_mentor: bool = True) -> List[Dict]:
        resolved_id = await self._resolve_user_id(user_id)
        if as_mentor:
            query = 'SELECT * FROM mentorships WHERE mentor_id = $1 AND status = \'completed\''
        else:
            query = 'SELECT * FROM mentorships WHERE mentee_id = $1 AND status = \'completed\''
        return await db.fetch(query, resolved_id)

    async def get_mentorship_stats(self) -> Dict:
        total = await db.fetchval('SELECT COUNT(*) FROM mentorships')
        active = await db.fetchval("SELECT COUNT(*) FROM mentorships WHERE status = 'active'")
        completed = await db.fetchval("SELECT COUNT(*) FROM mentorships WHERE status = 'completed'")

        category_stats = {}
        for category in MENTORSHIP_CATEGORIES:
            category_stats[category] = await db.fetchval(
                'SELECT COUNT(*) FROM mentorships WHERE category = $1',
                category,
            )

        return {
            'total_mentorships': total,
            'active_mentorships': active,
            'completed_mentorships': completed,
            'category_distribution': category_stats,
        }

    async def get_user_stats(self, user_id: str) -> Dict:
        resolved_id = await self._resolve_user_id(user_id)
        mentorships_as_mentor = await self.get_completed_mentorships(user_id, as_mentor=True)
        mentorships_as_mentee = await self.get_completed_mentorships(user_id, as_mentor=False)

        return {
            'as_mentor': {
                'total': len([m for m in mentorships_as_mentor if m['mentor_id'] == resolved_id]),
                'active': len([m for m in mentorships_as_mentor if m['mentor_id'] == resolved_id and m['status'] == 'active']),
                'completed': len([m for m in mentorships_as_mentor if m['mentor_id'] == resolved_id and m['status'] == 'completed']),
            },
            'as_mentee': {
                'total': len([m for m in mentorships_as_mentee if m['mentee_id'] == resolved_id]),
                'active': len([m for m in mentorships_as_mentee if m['mentee_id'] == resolved_id and m['status'] == 'active']),
                'completed': len([m for m in mentorships_as_mentee if m['mentee_id'] == resolved_id and m['status'] == 'completed']),
            },
        }
