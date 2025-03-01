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

    async def record_attempt(self, user_id: str, quiz_id: str,
                           correct: bool, time_taken: float) -> Dict:
        """Record a quiz attempt"""
        attempt = {
            "user_id": user_id,
            "quiz_id": quiz_id,
            "correct": correct,
            "time_taken": time_taken,
            "created_at": datetime.utcnow()
        }
        await quiz_attempts.insert_one(attempt)

        # Update user points if correct
        if correct:
            await users.update_one(
                {"discord_id": user_id},
                {
                    "$inc": {
                        "points": POINTS_CONFIG['quiz_correct'],
                        "quiz_score": 1
                    }
                }
            )

        return attempt

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
        
        # Get average time
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {"_id": None, "avg_time": {"$avg": "$time_taken"}}}
        ]
        avg_result = await quiz_attempts.aggregate(pipeline).to_list(length=1)
        avg_time = avg_result[0]["avg_time"] if avg_result else 0

        return {
            'total_attempts': total_attempts,
            'correct_attempts': correct_attempts,
            'accuracy': (correct_attempts / total_attempts * 100) if total_attempts else 0,
            'average_time': round(avg_time, 2),
            'total_points': user.get('points', 0),
            'quiz_score': user.get('quiz_score', 0)
        }

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