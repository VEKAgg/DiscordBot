import logging
from src.config.config import MENTORSHIP_CATEGORIES, POINTS_CONFIG
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from src.database.mongodb import mentorships, users, get_or_create_user
from bson import ObjectId

logger = logging.getLogger('VEKA.mentorship')

class MentorshipService:
    def __init__(self, bot):
        self.bot = bot

    async def create_mentorship_request(self, mentor_id: str, mentee_id: str,
                                      category: str) -> Dict:
        """Create a new mentorship request"""
        if category not in MENTORSHIP_CATEGORIES:
            raise ValueError(f"Invalid category. Must be one of: {', '.join(MENTORSHIP_CATEGORIES)}")

        # Check if there's already an active mentorship
        existing = await self.get_active_mentorship(mentor_id, mentee_id)
        if existing:
            raise ValueError("There's already an active mentorship between these users")

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

    async def accept_mentorship(self, mentorship_id: str, mentor_id: str) -> Dict:
        """Accept a mentorship request"""
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError("Mentorship not found")
        
        if mentorship["mentor_id"] != mentor_id:
            raise ValueError("Only the mentor can accept this request")
        
        if mentorship["status"] != "pending":
            raise ValueError(f"Cannot accept mentorship with status: {mentorship['status']}")

        await mentorships.update_one(
            {"_id": ObjectId(mentorship_id)},
            {
                "$set": {
                    "status": "active",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        mentorship["status"] = "active"
        return mentorship

    async def complete_mentorship(self, mentorship_id: str, mentor_id: str) -> Dict:
        """Complete a mentorship"""
        mentorship = await self.get_mentorship(mentorship_id)
        if not mentorship:
            raise ValueError("Mentorship not found")
        
        if mentorship["mentor_id"] != mentor_id:
            raise ValueError("Only the mentor can complete this mentorship")
        
        if mentorship["status"] != "active":
            raise ValueError(f"Cannot complete mentorship with status: {mentorship['status']}")

        await mentorships.update_one(
            {"_id": ObjectId(mentorship_id)},
            {
                "$set": {
                    "status": "completed",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        # Award points to both mentor and mentee
        points = POINTS_CONFIG['mentor_session']
        await users.update_many(
            {"discord_id": {"$in": [mentor_id, mentorship["mentee_id"]]}},
            {"$inc": {"points": points}}
        )

        mentorship["status"] = "completed"
        return mentorship

    async def get_mentorship(self, mentorship_id: str) -> Optional[Dict]:
        """Get a specific mentorship by ID"""
        return await mentorships.find_one({"_id": ObjectId(mentorship_id)})

    async def get_active_mentorship(self, mentor_id: str, mentee_id: str) -> Optional[Dict]:
        """Get active mentorship between two users"""
        return await mentorships.find_one({
            "mentor_id": mentor_id,
            "mentee_id": mentee_id,
            "status": {"$in": ["pending", "active"]}
        })

    async def get_user_mentorships(self, user_id: str, status: Optional[str] = None) -> List[Dict]:
        """Get all mentorships for a user"""
        query = {
            "$or": [
                {"mentor_id": user_id},
                {"mentee_id": user_id}
            ]
        }
        
        if status:
            query["status"] = status
            
        cursor = mentorships.find(query)
        return await cursor.to_list(length=None)

    async def find_mentors(self, category: str) -> List[Dict]:
        """Find potential mentors in a category"""
        pipeline = [
            {
                "$match": {
                    "category": category,
                    "status": "completed"
                }
            },
            {
                "$group": {
                    "_id": "$mentor_id",
                    "completed_mentorships": {"$sum": 1}
                }
            },
            {
                "$lookup": {
                    "from": "users",
                    "localField": "_id",
                    "foreignField": "discord_id",
                    "as": "user_info"
                }
            },
            {
                "$unwind": "$user_info"
            }
        ]
        
        cursor = mentorships.aggregate(pipeline)
        mentors = await cursor.to_list(length=None)
        
        return [{
            'discord_id': mentor['_id'],
            'completed_mentorships': mentor['completed_mentorships'],
            'points': mentor['user_info'].get('points', 0)
        } for mentor in mentors]

    async def get_completed_mentorships(self, user_id: str, as_mentor: bool = True) -> List[Dict]:
        """Get completed mentorships for a user"""
        query = {
            "mentor_id" if as_mentor else "mentee_id": user_id,
            "status": "completed"
        }
        cursor = mentorships.find(query)
        return await cursor.to_list(length=None)

    async def get_mentorship_stats(self) -> Dict:
        """Get overall mentorship statistics"""
        total = await mentorships.count_documents({})
        active = await mentorships.count_documents({"status": "active"})
        completed = await mentorships.count_documents({"status": "completed"})

        # Get stats by category
        category_stats = {}
        for category in MENTORSHIP_CATEGORIES:
            count = await mentorships.count_documents({"category": category})
            category_stats[category] = count

        return {
            'total_mentorships': total,
            'active_mentorships': active,
            'completed_mentorships': completed,
            'category_distribution': category_stats
        }

    async def get_user_stats(self, user_id: str) -> Dict:
        """Get mentorship statistics for a user"""
        mentorships_as_mentor = await self.get_user_mentorships(user_id)
        mentorships_as_mentee = await self.get_user_mentorships(user_id)

        return {
            'as_mentor': {
                'total': len([m for m in mentorships_as_mentor if m['mentor_id'] == user_id]),
                'active': len([m for m in mentorships_as_mentor if m['mentor_id'] == user_id and m['status'] == "active"]),
                'completed': len([m for m in mentorships_as_mentor if m['mentor_id'] == user_id and m['status'] == "completed"])
            },
            'as_mentee': {
                'total': len([m for m in mentorships_as_mentee if m['mentee_id'] == user_id]),
                'active': len([m for m in mentorships_as_mentee if m['mentee_id'] == user_id and m['status'] == "active"]),
                'completed': len([m for m in mentorships_as_mentee if m['mentee_id'] == user_id and m['status'] == "completed"])
            }
        } 