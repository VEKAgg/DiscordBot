from typing import Optional, Dict, List
import aiohttp
import datetime
from ..config.config import Config
from ..database.mongodb import MongoDatabase

class LeetCodeService:
    def __init__(self):
        self.config = Config()
        self.db = MongoDatabase()
        self.client_id = self.config.get("leetcode_client_id")
        self.client_secret = self.config.get("leetcode_client_secret")
        self.redirect_uri = self.config.get("leetcode_redirect_uri")
        self.graphql_endpoint = "https://leetcode.com/graphql"

    def get_oauth_url(self, user_id: int) -> str:
        """Generate LeetCode OAuth URL"""
        state = f"leetcode_{user_id}"
        return (
            f"https://leetcode.com/oauth/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&state={state}"
            f"&scope=read:user"
        )

    async def exchange_code(self, code: str) -> Optional[str]:
        """Exchange OAuth code for access token"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://leetcode.com/oauth/token",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code"
                },
                headers={"Accept": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("access_token")
        return None

    async def get_user_stats(self, access_token: str) -> Optional[Dict]:
        """Get user's LeetCode statistics"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        query = """
        {
            user {
                username
                profile {
                    reputation
                    ranking
                }
                submitStats {
                    acSubmissionNum {
                        difficulty
                        count
                        submissions
                    }
                }
                problemsSolvedBeatsStats {
                    difficulty
                    percentage
                }
                badges {
                    id
                    name
                    shortName
                    displayName
                    icon
                    hoverText
                }
                activeBadge {
                    id
                }
                tagProblemCounts {
                    advanced {
                        tagName
                        problemsSolved
                    }
                    intermediate {
                        tagName
                        problemsSolved
                    }
                    fundamental {
                        tagName
                        problemsSolved
                    }
                }
            }
        }
        """

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.graphql_endpoint,
                json={"query": query},
                headers=headers
            ) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                user_data = data.get("data", {}).get("user", {})
                
                if not user_data:
                    return None

                # Process submission statistics
                submissions = user_data.get("submitStats", {}).get("acSubmissionNum", [])
                total_solved = sum(sub.get("count", 0) for sub in submissions)
                
                # Calculate difficulty distribution
                difficulty_stats = {
                    sub.get("difficulty"): {
                        "solved": sub.get("count", 0),
                        "submissions": sub.get("submissions", 0)
                    }
                    for sub in submissions
                }

                # Process topic statistics
                topics = []
                for level in ["fundamental", "intermediate", "advanced"]:
                    level_data = user_data.get("tagProblemCounts", {}).get(level, [])
                    for topic in level_data:
                        topics.append({
                            "name": topic.get("tagName"),
                            "solved": topic.get("problemsSolved", 0),
                            "level": level
                        })

                # Sort topics by solved count
                topics.sort(key=lambda x: x["solved"], reverse=True)
                top_categories = [topic["name"] for topic in topics[:5]]

                # Process badges
                badges = []
                for badge in user_data.get("badges", []):
                    badges.append({
                        "name": badge.get("name"),
                        "display_name": badge.get("displayName"),
                        "icon": badge.get("icon"),
                        "hover_text": badge.get("hoverText")
                    })

                return {
                    "username": user_data.get("username"),
                    "reputation": user_data.get("profile", {}).get("reputation", 0),
                    "ranking": user_data.get("profile", {}).get("ranking", 0),
                    "solved": total_solved,
                    "difficulty_stats": difficulty_stats,
                    "top_categories": top_categories,
                    "badges": badges,
                    "topics": topics,
                    "updated_at": datetime.datetime.utcnow()
                }

    async def verify_user(self, user_id: int) -> bool:
        """Verify if the user's LeetCode account meets minimum criteria"""
        token_doc = await self.db.oauth_tokens.find_one({
            "user_id": user_id,
            "platform": "leetcode"
        })
        
        if not token_doc:
            return False

        stats = await self.get_user_stats(token_doc["access_token"])
        if not stats:
            return False

        # Define verification criteria
        MIN_PROBLEMS = 50
        MIN_MEDIUM = 20
        MIN_HARD = 5

        # Get difficulty counts
        difficulty_stats = stats["difficulty_stats"]
        medium_solved = difficulty_stats.get("Medium", {}).get("solved", 0)
        hard_solved = difficulty_stats.get("Hard", {}).get("solved", 0)

        return (
            stats["solved"] >= MIN_PROBLEMS and
            medium_solved >= MIN_MEDIUM and
            hard_solved >= MIN_HARD
        )