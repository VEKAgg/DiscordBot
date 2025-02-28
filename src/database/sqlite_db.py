from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, JSON
from datetime import datetime
import os

# Create async engine
DATABASE_URL = "sqlite+aiosqlite:///data/bot.db"
engine = create_async_engine(DATABASE_URL, echo=True)

# Create session factory
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Create base class for declarative models
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True)
    points = Column(Integer, default=0)
    quiz_score = Column(Integer, default=0)
    level = Column(Integer, default=1)
    experience = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Quiz(Base):
    __tablename__ = "quizzes"
    
    id = Column(Integer, primary_key=True)
    category = Column(String)
    difficulty = Column(String)
    question = Column(String)
    correct_answer = Column(String)
    wrong_answers = Column(String)  # JSON string of wrong answers
    explanation = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"))
    correct = Column(Boolean)
    time_taken = Column(Float)  # Time taken in seconds
    created_at = Column(DateTime, default=datetime.utcnow)

class Mentorship(Base):
    __tablename__ = "mentorships"
    
    id = Column(Integer, primary_key=True)
    mentor_id = Column(String)
    mentee_id = Column(String)
    category = Column(String)
    status = Column(String)  # pending, active, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Workshop(Base):
    __tablename__ = "workshops"
    
    id = Column(Integer, primary_key=True)
    title = Column(String)
    description = Column(String)
    host_id = Column(String)
    category = Column(String)
    scheduled_at = Column(DateTime)
    max_participants = Column(Integer)
    current_participants = Column(Integer, default=0)
    status = Column(String, default="scheduled")  # scheduled, ongoing, completed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)

class Portfolio(Base):
    __tablename__ = "portfolios"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    title = Column(String)
    description = Column(String)
    technologies = Column(String)  # JSON string of technologies
    url = Column(String, nullable=True)
    views = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

async def init_db():
    """Initialize the database"""
    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_session() -> AsyncSession:
    """Get a database session"""
    async with async_session() as session:
        return session 