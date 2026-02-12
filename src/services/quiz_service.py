import logging
from src.config.config import QUIZ_CATEGORIES, QUIZ_DIFFICULTY_LEVELS, POINTS_CONFIG
from typing import List, Dict, Optional, Tuple
import json
from datetime import datetime, timedelta
from src.database.mongodb import quizzes, quiz_attempts, users, get_or_create_user
import random

logger = logging.getLogger('VEKA.quiz')

class QuizService:
    def __init__(self, bot):
        self.bot = bot

    async def create_quiz(self, category: str, difficulty: str, question: str,
                         correct_answer: str, wrong_answers: List[str],
                         explanation: Optional[str] = None) -> Dict:
        """Create a new quiz question"""
        quiz = {
            "category": category,
            "difficulty": difficulty,
            "question": question,
            "correct_answer": correct_answer,
            "wrong_answers": wrong_answers,
            "explanation": explanation,
            "created_at": datetime.utcnow()
        }
        result = await quizzes.insert_one(quiz)
        quiz["_id"] = result.inserted_id
        return quiz

    async def get_random_quiz(self, category: Optional[str] = None,
                            difficulty: Optional[str] = None) -> Optional[Dict]:
        """Get a random quiz question with optional filters"""
        filter_query = {}
        if category:
            filter_query["category"] = category
        if difficulty:
            filter_query["difficulty"] = difficulty
        
        # Get total count
        count = await quizzes.count_documents(filter_query)
        if count == 0:
            return None

        # Get random quiz
        random_quiz = await quizzes.aggregate([
            {"$match": filter_query},
            {"$sample": {"size": 1}}
        ]).to_list(length=1)
        
        return random_quiz[0] if random_quiz else None

    async def record_quiz_attempt(self, user_id: str, quiz_id: str,
                           correct: bool, is_daily: bool = False) -> int:
        """Record a quiz attempt and return points earned"""
        attempt = {
            "user_id": user_id,
            "quiz_id": quiz_id,
            "correct": correct,
            "is_daily": is_daily,
            "created_at": datetime.utcnow()
        }
        await quiz_attempts.insert_one(attempt)

        # Update user points if correct
        points_earned = 0
        if correct:
            points_earned = POINTS_CONFIG['quiz_correct']
            if is_daily:
                points_earned += POINTS_CONFIG['daily_streak']
            await users.update_one(
                {"discord_id": user_id},
                {
                    "$inc": {
                        "points": points_earned,
                        "quiz_score": 1
                    }
                }
            )

        return points_earned

    async def get_user_stats(self, user_id: str) -> Dict:
        """Get quiz statistics for a user"""
        user = await get_or_create_user(user_id)
        
        # Get total attempts
        total_attempts = await quiz_attempts.count_documents({"user_id": user_id})
        
        # Get correct attempts
        correct_attempts = await quiz_attempts.count_documents({
            "user_id": user_id,
            "correct": True
        })
        
        # Get category breakdown
        category_pipeline = [
            {"$match": {"user_id": user_id}},
            {"$lookup": {
                "from": "quizzes",
                "localField": "quiz_id",
                "foreignField": "_id",
                "as": "quiz"
            }},
            {"$unwind": "$quiz"},
            {"$group": {
                "_id": "$quiz.category",
                "total": {"$sum": 1},
                "correct": {"$sum": {"$cond": ["$correct", 1, 0]}}
            }}
        ]
        category_stats = await quiz_attempts.aggregate(category_pipeline).to_list(length=None)
        categories = {}
        for stat in category_stats:
            cat = stat['_id']
            categories[cat] = {
                'total': stat['total'],
                'correct': stat['correct'],
                'percentage': round((stat['correct'] / stat['total']) * 100, 1) if stat['total'] > 0 else 0
            }
        
        # Get recent quizzes (last 5)
        recent_pipeline = [
            {"$match": {"user_id": user_id}},
            {"$sort": {"created_at": -1}},
            {"$limit": 5},
            {"$lookup": {
                "from": "quizzes",
                "localField": "quiz_id",
                "foreignField": "_id",
                "as": "quiz"
            }},
            {"$unwind": "$quiz"},
            {"$project": {
                "category": "$quiz.category",
                "difficulty": "$quiz.difficulty",
                "correct": 1,
                "created_at": 1
            }}
        ]
        recent_quizzes = await quiz_attempts.aggregate(recent_pipeline).to_list(length=None)

        return {
            'total_quizzes': total_attempts,
            'correct_answers': correct_attempts,
            'accuracy': round((correct_attempts / total_attempts * 100), 1) if total_attempts > 0 else 0,
            'points': user.get('points', 0),
            'categories': categories,
            'recent_quizzes': recent_quizzes
        }

    async def check_daily_taken(self, user_id: str) -> bool:
        """Check if user has taken today's daily quiz"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        daily_attempt = await quiz_attempts.find_one({
            "user_id": user_id,
            "is_daily": True,
            "created_at": {"$gte": today_start, "$lt": today_end}
        })
        
        return daily_attempt is not None

    async def get_time_until_next_daily(self) -> str:
        """Get formatted time until next daily quiz is available"""
        now = datetime.utcnow()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        time_diff = tomorrow - now
        
        hours = time_diff.seconds // 3600
        minutes = (time_diff.seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    async def get_daily_quiz(self) -> Optional[Dict]:
        """Get the daily quiz for today"""
        # Use the existing get_daily_challenge method but with better return
        quiz, is_new = await self.get_daily_challenge()
        return quiz

    async def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Get the quiz leaderboard"""
        cursor = users.find(
            {"quiz_score": {"$exists": True}},
            {"discord_id": 1, "quiz_score": 1, "points": 1}
        ).sort("quiz_score", -1).limit(limit)
        
        return await cursor.to_list(length=limit)

    async def get_category_stats(self) -> Dict[str, Dict]:
        """Get statistics for each quiz category"""
        stats = {}
        for category in QUIZ_CATEGORIES:
            # Get total questions
            total_questions = await quizzes.count_documents({"category": category})
            
            # Get difficulty distribution
            difficulty_counts = {}
            for difficulty in QUIZ_DIFFICULTY_LEVELS:
                count = await quizzes.count_documents({
                    "category": category,
                    "difficulty": difficulty
                })
                difficulty_counts[difficulty] = count

            stats[category] = {
                'total_questions': total_questions,
                'difficulty_distribution': difficulty_counts
            }

        return stats

    async def get_daily_challenge(self) -> Tuple[Dict, bool]:
        """Get the daily challenge quiz"""
        # Get recently used quiz IDs (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_attempts = await quiz_attempts.distinct(
            "quiz_id",
            {"created_at": {"$gte": week_ago}}
        )

        # Try to get a quiz that hasn't been used recently
        unused_quiz = await quizzes.aggregate([
            {"$match": {"_id": {"$nin": recent_attempts}}},
            {"$sample": {"size": 1}}
        ]).to_list(length=1)

        if unused_quiz:
            return unused_quiz[0], True

        # If all quizzes have been used recently, just get any random quiz
        random_quiz = await quizzes.aggregate([
            {"$sample": {"size": 1}}
        ]).to_list(length=1)
        
        return random_quiz[0] if random_quiz else None, False 