import logging
from typing import Dict, List, Optional
from src.config.config import MENTORSHIP_CATEGORIES, POINTS_CONFIG
from src.database.database import db, get_or_create_user

logger = logging.getLogger('VEKA.mentorship')


class MentorshipService:
    def __init__(self, bot):
        self.bot = bot

    async def create_mentorship_request(self, mentor_discord_id: str, mentee_discord_id: str, category: str) -> Dict:
        if category not in MENTORSHIP_CATEGORIES:
            raise ValueError(f"Invalid category. Must be one of: {', '.join(MENTORSHIP_CATEGORIES)}")

        existing = await self.get_active_mentorship(mentor_discord_id, mentee_discord_id)
        if existing:
            raise ValueError("There's already an active mentorship between these users")

        mentor = await get_or_create_user(mentor_discord_id)
        mentee = await get_or_create_user(mentee_discord_id)

        row = await db.fetch_one(
            """
            INSERT INTO mentorships (mentor_id, mentee_id, category, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING *
            """,
            mentor['id'], mentee['id'], category
        )
        return dict(row)

    async def accept_mentorship(self, mentorship_id: int, mentor_discord_id: str) -> Dict:
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError("Mentorship not found")

        mentor = await get_or_create_user(mentor_discord_id)
        if mentorship['mentor_id'] != mentor['id']:
            raise ValueError("Only the mentor can accept this request")
        if mentorship['status'] != 'pending':
            raise ValueError(f"Cannot accept mentorship with status: {mentorship['status']}")

        row = await db.fetch_one(
            "UPDATE mentorships SET status = 'active', updated_at = NOW() WHERE id = $1 RETURNING *",
            mentorship_id
        )
        return dict(row)

    async def complete_mentorship(self, mentorship_id: int, mentor_discord_id: str) -> Dict:
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError("Mentorship not found")

        mentor = await get_or_create_user(mentor_discord_id)
        if mentorship['mentor_id'] != mentor['id']:
            raise ValueError("Only the mentor can complete this mentorship")
        if mentorship['status'] != 'active':
            raise ValueError(f"Cannot complete mentorship with status: {mentorship['status']}")

        row = await db.fetch_one(
            "UPDATE mentorships SET status = 'completed', updated_at = NOW() WHERE id = $1 RETURNING *",
            mentorship_id
        )

        points = POINTS_CONFIG['mentor_session']
        await db.execute(
            """
            UPDATE users SET points = points + $1, updated_at = NOW()
             WHERE id = $2 OR id = $3
            """,
            points, mentorship['mentor_id'], mentorship['mentee_id']
        )
        return dict(row)

    async def get_mentorship(self, mentorship_id: int) -> Optional[Dict]:
        row = await db.fetch_one("SELECT * FROM mentorships WHERE id = $1", mentorship_id)
        return dict(row) if row else None

    async def get_active_mentorship(self, mentor_discord_id: str, mentee_discord_id: str) -> Optional[Dict]:
        row = await db.fetch_one(
            """
            SELECT m.* FROM mentorships m
              JOIN users mentor ON mentor.id = m.mentor_id
              JOIN users mentee ON mentee.id = m.mentee_id
             WHERE mentor.discord_id = $1
               AND mentee.discord_id = $2
               AND m.status IN ('pending', 'active')
            """,
            mentor_discord_id, mentee_discord_id
        )
        return dict(row) if row else None

    async def get_user_mentorships(self, discord_id: str, status: Optional[str] = None) -> List[Dict]:
        user = await get_or_create_user(discord_id)
        if status:
            rows = await db.fetch_many(
                "SELECT * FROM mentorships WHERE (mentor_id = $1 OR mentee_id = $1) AND status = $2",
                user['id'], status
            )
        else:
            rows = await db.fetch_many(
                "SELECT * FROM mentorships WHERE mentor_id = $1 OR mentee_id = $1",
                user['id']
            )
        return [dict(r) for r in rows]

    async def find_mentors(self, category: Optional[str] = None) -> List[Dict]:
        if category:
            rows = await db.fetch_many(
                """
                SELECT u.discord_id, u.points, COUNT(*) AS completed_mentorships
                  FROM mentorships m
                  JOIN users u ON u.id = m.mentor_id
                 WHERE m.status = 'completed' AND m.category = $1
                 GROUP BY u.discord_id, u.points
                 ORDER BY completed_mentorships DESC
                """,
                category
            )
        else:
            rows = await db.fetch_many(
                """
                SELECT u.discord_id, u.points, COUNT(*) AS completed_mentorships
                  FROM mentorships m
                  JOIN users u ON u.id = m.mentor_id
                 WHERE m.status = 'completed'
                 GROUP BY u.discord_id, u.points
                 ORDER BY completed_mentorships DESC
                """
            )
        return [dict(r) for r in rows]

    async def get_mentorship_stats(self) -> Dict:
        total = await db.fetch_one("SELECT COUNT(*) AS n FROM mentorships")
        active = await db.fetch_one("SELECT COUNT(*) AS n FROM mentorships WHERE status = 'active'")
        completed = await db.fetch_one("SELECT COUNT(*) AS n FROM mentorships WHERE status = 'completed'")

        cat_rows = await db.fetch_many(
            "SELECT category, COUNT(*) AS n FROM mentorships GROUP BY category"
        )
        category_distribution = {r['category']: r['n'] for r in cat_rows}

        return {
            'total_mentorships': total['n'],
            'active_mentorships': active['n'],
            'completed_mentorships': completed['n'],
            'category_distribution': category_distribution,
        }

    async def get_user_stats(self, discord_id: str) -> Dict:
        rows = await self.get_user_mentorships(discord_id)
        user = await get_or_create_user(discord_id)
        uid = user['id']
        return {
            'as_mentor': {
                'total':     sum(1 for m in rows if m['mentor_id'] == uid),
                'active':    sum(1 for m in rows if m['mentor_id'] == uid and m['status'] == 'active'),
                'completed': sum(1 for m in rows if m['mentor_id'] == uid and m['status'] == 'completed'),
            },
            'as_mentee': {
                'total':     sum(1 for m in rows if m['mentee_id'] == uid),
                'active':    sum(1 for m in rows if m['mentee_id'] == uid and m['status'] == 'active'),
                'completed': sum(1 for m in rows if m['mentee_id'] == uid and m['status'] == 'completed'),
            },
        }
