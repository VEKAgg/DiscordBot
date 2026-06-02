import logging
import random
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from src.config.config import QUIZ_CATEGORIES, QUIZ_DIFFICULTY_LEVELS, POINTS_CONFIG
from src.database.database import db, get_or_create_user

logger = logging.getLogger('VEKA.quiz')


class QuizService:
    def __init__(self, bot):
        self.bot = bot

    async def create_quiz(self, category: str, difficulty: str, question: str,
                          correct_answer: str, wrong_answers: List[str],
                          explanation: Optional[str] = None) -> Dict:
        row = await db.fetch_one(
            """
            INSERT INTO quizzes (category, difficulty, question, correct_answer, wrong_answers, explanation)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            category, difficulty, question, correct_answer, wrong_answers, explanation
        )
        return dict(row)

    async def get_random_quiz(self, category: Optional[str] = None,
                              difficulty: Optional[str] = None) -> Optional[Dict]:
        """Return a random quiz row using ORDER BY RANDOM() (fast enough for small tables)."""
        conditions = []
        args = []
        if category:
            args.append(category)
            conditions.append(f"category = ${len(args)}")
        if difficulty:
            args.append(difficulty)
            conditions.append(f"difficulty = ${len(args)}")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        row = await db.fetch_one(
            f"SELECT * FROM quizzes {where} ORDER BY RANDOM() LIMIT 1", *args
        )
        return dict(row) if row else None

    async def record_quiz_attempt(self, discord_id, quiz_id: int,
                                  correct: bool, is_daily: bool = False) -> int:
        user = await get_or_create_user(str(discord_id))
        await db.execute(
            """
            INSERT INTO quiz_attempts (user_id, quiz_id, correct, is_daily)
            VALUES ($1, $2, $3, $4)
            """,
            user['id'], quiz_id, correct, is_daily
        )
        points_earned = 0
        if correct:
            points_earned = POINTS_CONFIG['quiz_correct']
            if is_daily:
                points_earned += POINTS_CONFIG['daily_streak']
            await db.execute(
                """
                UPDATE users
                   SET points     = points + $1,
                       quiz_score = quiz_score + 1,
                       updated_at = NOW()
                 WHERE id = $2
                """,
                points_earned, user['id']
            )
        return points_earned

    async def get_user_stats(self, discord_id) -> Dict:
        user = await get_or_create_user(str(discord_id))

        totals = await db.fetch_one(
            """
            SELECT COUNT(*) AS total, SUM(correct::int) AS correct_count
              FROM quiz_attempts WHERE user_id = $1
            """,
            user['id']
        )
        total = totals['total'] or 0
        correct = totals['correct_count'] or 0

        cat_rows = await db.fetch_many(
            """
            SELECT q.category,
                   COUNT(*)             AS total,
                   SUM(a.correct::int)  AS correct
              FROM quiz_attempts a
              JOIN quizzes q ON q.id = a.quiz_id
             WHERE a.user_id = $1
             GROUP BY q.category
            """,
            user['id']
        )
        categories = {}
        for r in cat_rows:
            t = r['total'] or 0
            c = r['correct'] or 0
            categories[r['category']] = {
                'total': t,
                'correct': c,
                'percentage': round(c / t * 100, 1) if t else 0,
            }

        recent = await db.fetch_many(
            """
            SELECT q.category, q.difficulty, a.correct, a.created_at
              FROM quiz_attempts a
              JOIN quizzes q ON q.id = a.quiz_id
             WHERE a.user_id = $1
             ORDER BY a.created_at DESC
             LIMIT 5
            """,
            user['id']
        )

        return {
            'total_quizzes': total,
            'correct_answers': correct,
            'accuracy': round(correct / total * 100, 1) if total else 0,
            'points': user['points'],
            'categories': categories,
            'recent_quizzes': [dict(r) for r in recent],
        }

    async def check_daily_taken(self, discord_id) -> bool:
        user = await get_or_create_user(str(discord_id))
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        row = await db.fetch_one(
            """
            SELECT 1 FROM quiz_attempts
             WHERE user_id = $1 AND is_daily = TRUE
               AND created_at >= $2 AND created_at < $3
            """,
            user['id'], today_start, today_end
        )
        return row is not None

    async def get_time_until_next_daily(self) -> str:
        now = datetime.utcnow()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        diff = tomorrow - now
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"

    async def get_daily_quiz(self) -> Optional[Dict]:
        quiz, _ = await self.get_daily_challenge()
        return quiz

    async def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        rows = await db.fetch_many(
            """
            SELECT u.discord_id,
                   u.quiz_score                                       AS correct_answers,
                   COUNT(a.id)                                        AS total_attempts,
                   ROUND(u.quiz_score::numeric /
                         NULLIF(COUNT(a.id), 0) * 100, 1)            AS accuracy
              FROM users u
              JOIN quiz_attempts a ON a.user_id = u.id
             GROUP BY u.discord_id, u.quiz_score
             ORDER BY u.quiz_score DESC
             LIMIT $1
            """,
            limit
        )
        return [dict(r) for r in rows]

    async def get_category_stats(self) -> Dict[str, Dict]:
        rows = await db.fetch_many(
            "SELECT category, difficulty, COUNT(*) AS n FROM quizzes GROUP BY category, difficulty"
        )
        stats: Dict[str, Dict] = {
            cat: {'total_questions': 0, 'difficulty_distribution': {}}
            for cat in QUIZ_CATEGORIES
        }
        for r in rows:
            cat = r['category']
            if cat in stats:
                stats[cat]['total_questions'] += r['n']
                stats[cat]['difficulty_distribution'][r['difficulty']] = r['n']
        return stats

    async def get_daily_challenge(self) -> Tuple[Optional[Dict], bool]:
        """Return a quiz not used in the last 7 days, or any random quiz as fallback."""
        week_ago = datetime.utcnow() - timedelta(days=7)
        row = await db.fetch_one(
            """
            SELECT * FROM quizzes
             WHERE id NOT IN (
                 SELECT DISTINCT quiz_id FROM quiz_attempts
                  WHERE is_daily = TRUE AND created_at >= $1
             )
             ORDER BY RANDOM() LIMIT 1
            """,
            week_ago
        )
        if row:
            return dict(row), True

        row = await db.fetch_one("SELECT * FROM quizzes ORDER BY RANDOM() LIMIT 1")
        return (dict(row) if row else None), False
