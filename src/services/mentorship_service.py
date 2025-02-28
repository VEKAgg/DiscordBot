from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from src.database.sqlite_db import Mentorship, User
from src.config.config import MENTORSHIP_CATEGORIES, POINTS_CONFIG
from typing import List, Dict, Optional, Tuple
import logging
from datetime import datetime

logger = logging.getLogger('VEKA.mentorship')

class MentorshipService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_mentorship_request(self, mentor_id: str, mentee_id: str,
                                      category: str) -> Mentorship:
        """Create a new mentorship request"""
        if category not in MENTORSHIP_CATEGORIES:
            raise ValueError(f"Invalid category. Must be one of: {', '.join(MENTORSHIP_CATEGORIES)}")

        # Check if there's already an active mentorship
        existing = await self.get_active_mentorship(mentor_id, mentee_id)
        if existing:
            raise ValueError("There's already an active mentorship between these users")

        mentorship = Mentorship(
            mentor_id=mentor_id,
            mentee_id=mentee_id,
            category=category,
            status="pending"
        )
        self.session.add(mentorship)
        await self.session.commit()
        return mentorship

    async def accept_mentorship(self, mentorship_id: int, mentor_id: str) -> Mentorship:
        """Accept a mentorship request"""
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError("Mentorship not found")
        
        if mentorship.mentor_id != mentor_id:
            raise ValueError("Only the mentor can accept this request")
        
        if mentorship.status != "pending":
            raise ValueError(f"Cannot accept mentorship with status: {mentorship.status}")

        mentorship.status = "active"
        await self.session.commit()
        return mentorship

    async def complete_mentorship(self, mentorship_id: int,
                                mentor_id: str) -> Mentorship:
        """Complete a mentorship"""
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError("Mentorship not found")
        
        if mentorship.mentor_id != mentor_id:
            raise ValueError("Only the mentor can complete this mentorship")
        
        if mentorship.status != "active":
            raise ValueError(f"Cannot complete mentorship with status: {mentorship.status}")

        mentorship.status = "completed"
        
        # Award points to both mentor and mentee
        mentor = await self.get_user(mentor_id)
        mentee = await self.get_user(mentorship.mentee_id)
        
        if mentor and mentee:
            mentor.points += POINTS_CONFIG['mentor_session']
            mentee.points += POINTS_CONFIG['mentor_session']

        await self.session.commit()
        return mentorship

    async def get_mentorship(self, mentorship_id: int) -> Optional[Mentorship]:
        """Get a specific mentorship by ID"""
        result = await self.session.execute(
            select(Mentorship).where(Mentorship.id == mentorship_id)
        )
        return result.scalar_one_or_none()

    async def get_active_mentorship(self, mentor_id: str,
                                  mentee_id: str) -> Optional[Mentorship]:
        """Get active mentorship between two users"""
        result = await self.session.execute(
            select(Mentorship)
            .where(and_(
                Mentorship.mentor_id == mentor_id,
                Mentorship.mentee_id == mentee_id,
                Mentorship.status.in_(["pending", "active"])
            ))
        )
        return result.scalar_one_or_none()

    async def get_user_mentorships(self, user_id: str,
                                 status: Optional[str] = None) -> List[Mentorship]:
        """Get all mentorships for a user"""
        query = select(Mentorship).where(
            or_(
                Mentorship.mentor_id == user_id,
                Mentorship.mentee_id == user_id
            )
        )
        
        if status:
            query = query.where(Mentorship.status == status)
            
        result = await self.session.execute(query)
        return result.scalars().all()

    async def find_mentors(self, category: str) -> List[Dict]:
        """Find potential mentors in a category"""
        # Get users who have completed mentorships as mentors
        result = await self.session.execute(
            select(User, Mentorship)
            .join(Mentorship, User.discord_id == Mentorship.mentor_id)
            .where(and_(
                Mentorship.category == category,
                Mentorship.status == "completed"
            ))
            .group_by(User.discord_id)
        )
        mentors = result.all()

        return [{
            'discord_id': mentor.User.discord_id,
            'completed_mentorships': len(await self.get_completed_mentorships(mentor.User.discord_id, as_mentor=True)),
            'points': mentor.User.points
        } for mentor in mentors]

    async def get_completed_mentorships(self, user_id: str,
                                      as_mentor: bool = True) -> List[Mentorship]:
        """Get completed mentorships for a user"""
        query = select(Mentorship).where(and_(
            Mentorship.mentor_id == user_id if as_mentor else Mentorship.mentee_id == user_id,
            Mentorship.status == "completed"
        ))
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_mentorship_stats(self) -> Dict:
        """Get overall mentorship statistics"""
        total = await self.session.scalar(select(func.count()).select_from(Mentorship))
        active = await self.session.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(Mentorship.status == "active")
        )
        completed = await self.session.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(Mentorship.status == "completed")
        )

        # Get stats by category
        category_stats = {}
        for category in MENTORSHIP_CATEGORIES:
            count = await self.session.scalar(
                select(func.count())
                .select_from(Mentorship)
                .where(Mentorship.category == category)
            )
            category_stats[category] = count or 0

        return {
            'total_mentorships': total or 0,
            'active_mentorships': active or 0,
            'completed_mentorships': completed or 0,
            'category_distribution': category_stats
        }

    async def get_user(self, user_id: str) -> Optional[User]:
        """Get a user by Discord ID"""
        result = await self.session.execute(
            select(User).where(User.discord_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_stats(self, user_id: str) -> Dict:
        """Get mentorship statistics for a user"""
        mentorships_as_mentor = await self.get_user_mentorships(user_id)
        mentorships_as_mentee = await self.get_user_mentorships(user_id)

        return {
            'as_mentor': {
                'total': len([m for m in mentorships_as_mentor if m.mentor_id == user_id]),
                'active': len([m for m in mentorships_as_mentor if m.mentor_id == user_id and m.status == "active"]),
                'completed': len([m for m in mentorships_as_mentor if m.mentor_id == user_id and m.status == "completed"])
            },
            'as_mentee': {
                'total': len([m for m in mentorships_as_mentee if m.mentee_id == user_id]),
                'active': len([m for m in mentorships_as_mentee if m.mentee_id == user_id and m.status == "active"]),
                'completed': len([m for m in mentorships_as_mentee if m.mentee_id == user_id and m.status == "completed"])
            }
        } 