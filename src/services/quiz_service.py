from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from src.database.sqlite_db import Quiz, QuizAttempt, User
from src.config.config import QUIZ_CATEGORIES, QUIZ_DIFFICULTY_LEVELS, POINTS_CONFIG
from typing import List, Dict, Optional, Tuple
import json
import random
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('VEKA.quiz')

class QuizService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_quiz(self, category: str, difficulty: str, question: str,
                         correct_answer: str, wrong_answers: List[str],
                         explanation: Optional[str] = None) -> Quiz:
        """Create a new quiz question"""
        quiz = Quiz(
            category=category,
            difficulty=difficulty,
            question=question,
            correct_answer=correct_answer,
            wrong_answers=json.dumps(wrong_answers),
            explanation=explanation
        )
        self.session.add(quiz)
        await self.session.commit()
        return quiz

    async def get_random_quiz(self, category: Optional[str] = None,
                            difficulty: Optional[str] = None) -> Optional[Quiz]:
        """Get a random quiz question with optional filters"""
        query = select(Quiz)
        if category:
            query = query.where(Quiz.category == category)
        if difficulty:
            query = query.where(Quiz.difficulty == difficulty)
        
        # Get total count
        count = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        if count == 0:
            return None

        # Get random quiz
        offset = random.randint(0, count - 1)
        result = await self.session.execute(query.offset(offset).limit(1))
        quiz = result.scalar_one_or_none()
        return quiz

    async def record_attempt(self, user_id: str, quiz_id: int,
                           correct: bool, time_taken: float) -> QuizAttempt:
        """Record a quiz attempt"""
        attempt = QuizAttempt(
            user_id=user_id,
            quiz_id=quiz_id,
            correct=correct,
            time_taken=time_taken
        )
        self.session.add(attempt)

        # Update user points if correct
        if correct:
            user = await self.get_or_create_user(user_id)
            user.points += POINTS_CONFIG['quiz_correct']
            user.quiz_score += 1

        await self.session.commit()
        return attempt

    async def get_user_stats(self, user_id: str) -> Dict:
        """Get quiz statistics for a user"""
        user = await self.get_or_create_user(user_id)
        
        # Get total attempts
        total_attempts = await self.session.scalar(
            select(func.count())
            .select_from(QuizAttempt)
            .where(QuizAttempt.user_id == user_id)
        )

        # Get correct attempts
        correct_attempts = await self.session.scalar(
            select(func.count())
            .select_from(QuizAttempt)
            .where(QuizAttempt.user_id == user_id)
            .where(QuizAttempt.correct == True)
        )

        # Get average time
        avg_time = await self.session.scalar(
            select(func.avg(QuizAttempt.time_taken))
            .select_from(QuizAttempt)
            .where(QuizAttempt.user_id == user_id)
        )

        return {
            'total_attempts': total_attempts or 0,
            'correct_attempts': correct_attempts or 0,
            'accuracy': (correct_attempts / total_attempts * 100) if total_attempts else 0,
            'average_time': round(avg_time or 0, 2),
            'total_points': user.points,
            'quiz_score': user.quiz_score
        }

    async def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Get the quiz leaderboard"""
        query = select(User).order_by(User.quiz_score.desc()).limit(limit)
        result = await self.session.execute(query)
        users = result.scalars().all()

        return [{
            'discord_id': user.discord_id,
            'quiz_score': user.quiz_score,
            'total_points': user.points
        } for user in users]

    async def get_or_create_user(self, user_id: str) -> User:
        """Get or create a user record"""
        result = await self.session.execute(
            select(User).where(User.discord_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(discord_id=user_id)
            self.session.add(user)
            await self.session.commit()
        
        return user

    async def get_category_stats(self) -> Dict[str, Dict]:
        """Get statistics for each quiz category"""
        stats = {}
        for category in QUIZ_CATEGORIES:
            # Get total questions
            total_questions = await self.session.scalar(
                select(func.count())
                .select_from(Quiz)
                .where(Quiz.category == category)
            )

            # Get difficulty distribution
            difficulty_counts = {}
            for difficulty in QUIZ_DIFFICULTY_LEVELS:
                count = await self.session.scalar(
                    select(func.count())
                    .select_from(Quiz)
                    .where(Quiz.category == category)
                    .where(Quiz.difficulty == difficulty)
                )
                difficulty_counts[difficulty] = count or 0

            stats[category] = {
                'total_questions': total_questions or 0,
                'difficulty_distribution': difficulty_counts
            }

        return stats

    async def get_daily_challenge(self) -> Tuple[Quiz, bool]:
        """Get the daily challenge quiz"""
        # Try to get a quiz that hasn't been used recently
        recent_quizzes = await self.session.execute(
            select(QuizAttempt.quiz_id)
            .where(QuizAttempt.created_at >= datetime.utcnow() - timedelta(days=7))
            .distinct()
        )
        recent_ids = [r[0] for r in recent_quizzes.all()]

        # Get a random quiz that hasn't been used recently
        query = select(Quiz)
        if recent_ids:
            query = query.where(Quiz.id.notin_(recent_ids))

        count = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        if count == 0:
            # If all quizzes have been used recently, just get any random quiz
            return await self.get_random_quiz(), False

        offset = random.randint(0, count - 1)
        result = await self.session.execute(query.offset(offset).limit(1))
        quiz = result.scalar_one_or_none()
        return quiz, True 