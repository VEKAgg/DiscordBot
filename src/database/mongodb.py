import motor.motor_asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict
from src.config.config import MONGODB_URI

logger = logging.getLogger('VEKA.database')

# MongoDB Client
client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = client.veka_bot

# Collections
users = db.users
quizzes = db.quizzes
quiz_attempts = db.quiz_attempts
resources = db.resources
mentorships = db.mentorships
challenges = db.challenges
challenge_attempts = db.challenge_attempts

async def init_db():
    """Initialize database indexes"""
    try:
        # Users collection indexes
        await users.create_index("discord_id", unique=True)
        
        # Quizzes collection indexes
        await quizzes.create_index([("category", 1), ("difficulty", 1)])
        
        # Quiz attempts indexes
        await quiz_attempts.create_index([("user_id", 1), ("quiz_id", 1)])
        
        # Resources indexes
        await resources.create_index([("category", 1), ("title", 1)])
        
        # Mentorships indexes
        await mentorships.create_index([("mentor_id", 1), ("mentee_id", 1)])
        await mentorships.create_index([("status", 1)])
        
        # Challenges indexes
        await challenges.create_index([("category", 1), ("difficulty", 1)])
        
        logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating database indexes: {str(e)}")
        raise

# User operations
async def get_user(discord_id: str) -> Optional[Dict]:
    """Get a user by Discord ID"""
    return await users.find_one({"discord_id": discord_id})

async def create_user(discord_id: str) -> Dict:
    """Create a new user"""
    user = {
        "discord_id": discord_id,
        "points": 0,
        "quiz_score": 0,
        "challenge_score": 0,
        "daily_streak": 0,
        "last_daily": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    await users.insert_one(user)
    return user

async def get_or_create_user(discord_id: str) -> Dict:
    """Get an existing user or create a new one"""
    user = await get_user(discord_id)
    if not user:
        user = await create_user(discord_id)
    return user

# Quiz operations
async def create_quiz(category: str, difficulty: str, question: str,
                     correct_answer: str, wrong_answers: List[str],
                     explanation: Optional[str] = None) -> Dict:
    """Create a new quiz"""
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

# Mentorship operations
async def create_mentorship(mentor_id: str, mentee_id: str, category: str) -> Dict:
    """Create a new mentorship"""
    mentorship = {
        "mentor_id": mentor_id,
        "mentee_id": mentee_id,
        "category": category,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    result = await mentorships.insert_one(mentorship)
    mentorship["_id"] = result.inserted_id
    return mentorship

async def update_mentorship_status(mentorship_id: str, status: str) -> bool:
    """Update mentorship status"""
    result = await mentorships.update_one(
        {"_id": mentorship_id},
        {
            "$set": {
                "status": status,
                "updated_at": datetime.utcnow()
            }
        }
    )
    return result.modified_count > 0 