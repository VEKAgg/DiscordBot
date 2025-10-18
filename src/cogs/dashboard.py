import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import jwt
from typing import Dict, List, Optional
import aiohttp
import json
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

logger = logging.getLogger('VEKA.dashboard')

class DashboardIntegration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.api_tokens = self.db.api_tokens
        self.user_settings = self.db.user_settings
        self.server_settings = self.db.server_settings
        self.jwt_secret = "your-secret-key"  # Move to env vars
        self.token_expiry = timedelta(days=7)
        self.api = FastAPI()
        self.setup_api_routes()
        self.security = HTTPBearer()

    def setup_api_routes(self):
        """Setup FastAPI routes for dashboard integration"""
        
        class UserAuth(BaseModel):
            discord_id: str
            username: str

        @self.api.post("/api/auth/discord")
        async def auth_discord(user: UserAuth):
            """Authenticate Discord user and generate API token"""
            try:
                # Verify user exists in bot's cache
                discord_user = self.bot.get_user(int(user.discord_id))
                if not discord_user:
                    raise HTTPException(status_code=404, detail="User not found")

                # Generate JWT token
                token = self.generate_token(user.discord_id)
                
                # Store token
                await self.api_tokens.insert_one({
                    "user_id": user.discord_id,
                    "token": token,
                    "created_at": datetime.utcnow(),
                    "expires_at": datetime.utcnow() + self.token_expiry
                })

                return {"token": token}

            except Exception as e:
                logger.error(f"Auth error: {str(e)}")
                raise HTTPException(status_code=500, detail="Authentication failed")

        @self.api.get("/api/user/profile")
        async def get_user_profile(credentials: HTTPAuthorizationCredentials = Security(self.security)):
            """Get user's profile data"""
            try:
                user_id = self.verify_token(credentials.credentials)
                profile = await self.db.profiles.find_one({"user_id": user_id})
                if not profile:
                    raise HTTPException(status_code=404, detail="Profile not found")
                
                # Clean up profile data for API response
                clean_profile = {
                    "id": str(profile["_id"]),
                    "user_id": profile["user_id"],
                    "username": self.bot.get_user(int(user_id)).name,
                    "title": profile.get("title"),
                    "headline": profile.get("headline"),
                    "skills": profile.get("skills", []),
                    "connections": await self.get_connection_count(user_id),
                    "created_at": profile.get("created_at").isoformat()
                }
                
                return clean_profile

            except jwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="Invalid token")
            except Exception as e:
                logger.error(f"Profile fetch error: {str(e)}")
                raise HTTPException(status_code=500, detail="Could not fetch profile")

        @self.api.get("/api/user/connections")
        async def get_user_connections(credentials: HTTPAuthorizationCredentials = Security(self.security)):
            """Get user's connections"""
            try:
                user_id = self.verify_token(credentials.credentials)
                connections = await self.get_user_connections(user_id)
                return {"connections": connections}

            except jwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="Invalid token")
            except Exception as e:
                logger.error(f"Connections fetch error: {str(e)}")
                raise HTTPException(status_code=500, detail="Could not fetch connections")

        @self.api.get("/api/user/analytics")
        async def get_user_analytics(credentials: HTTPAuthorizationCredentials = Security(self.security)):
            """Get user's engagement analytics"""
            try:
                user_id = self.verify_token(credentials.credentials)
                analytics = await self.get_user_analytics(user_id)
                return analytics

            except jwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="Invalid token")
            except Exception as e:
                logger.error(f"Analytics fetch error: {str(e)}")
                raise HTTPException(status_code=500, detail="Could not fetch analytics")

        @self.api.post("/api/user/settings")
        async def update_user_settings(
            settings: dict,
            credentials: HTTPAuthorizationCredentials = Security(self.security)
        ):
            """Update user's settings"""
            try:
                user_id = self.verify_token(credentials.credentials)
                await self.user_settings.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        **settings,
                        "updated_at": datetime.utcnow()
                    }},
                    upsert=True
                )
                return {"status": "success"}

            except jwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="Invalid token")
            except Exception as e:
                logger.error(f"Settings update error: {str(e)}")
                raise HTTPException(status_code=500, detail="Could not update settings")

    def generate_token(self, user_id: str) -> str:
        """Generate JWT token for user"""
        payload = {
            "user_id": user_id,
            "exp": datetime.utcnow() + self.token_expiry
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> str:
        """Verify JWT token and return user_id"""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return payload["user_id"]
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    async def get_connection_count(self, user_id: str) -> int:
        """Get count of user's connections"""
        return await self.db.connections.count_documents({
            "$or": [
                {"user_id": user_id},
                {"connected_id": user_id}
            ],
            "status": "connected"
        })

    async def get_user_connections(self, user_id: str) -> List[Dict]:
        """Get user's connections with details"""
        connections = []
        
        # Get all connections
        cursor = self.db.connections.find({
            "$or": [
                {"user_id": user_id},
                {"connected_id": user_id}
            ],
            "status": "connected"
        })

        async for conn in cursor:
            # Get connected user's ID
            connected_id = conn["connected_id"] if conn["user_id"] == user_id else conn["user_id"]
            
            # Get connected user's profile
            profile = await self.db.profiles.find_one({"user_id": connected_id})
            if profile:
                discord_user = self.bot.get_user(int(connected_id))
                if discord_user:
                    connections.append({
                        "user_id": connected_id,
                        "username": discord_user.name,
                        "avatar_url": str(discord_user.avatar.url) if discord_user.avatar else None,
                        "title": profile.get("title"),
                        "connected_since": conn.get("connected_at").isoformat()
                    })

        return connections

    async def get_user_analytics(self, user_id: str) -> Dict:
        """Get user's engagement analytics"""
        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)

        # Get monthly activity
        monthly_activity = await self.db.user_activity.find({
            "user_id": user_id,
            "timestamp": {"$gte": month_ago}
        }).to_list(length=None)

        # Get skills and endorsements
        skills = await self.db.profiles.find_one(
            {"user_id": user_id},
            {"skills": 1}
        )
        
        endorsements = await self.db.endorsements.find({
            "user_id": user_id
        }).to_list(length=None)

        # Get event participation
        events_attended = await self.db.event_registrations.count_documents({
            "user_id": user_id,
            "status": "attended"
        })

        # Compile analytics
        return {
            "activity": {
                "total_actions": len(monthly_activity),
                "messages_sent": sum(1 for a in monthly_activity if a.get("type") == "message"),
                "reactions_given": sum(1 for a in monthly_activity if a.get("type") == "reaction")
            },
            "skills": {
                "total": len(skills.get("skills", [])) if skills else 0,
                "endorsed": len(set(e["skill"] for e in endorsements))
            },
            "networking": {
                "connections": await self.get_connection_count(user_id),
                "events_attended": events_attended
            },
            "engagement_score": await self.calculate_engagement_score(user_id)
        }

    async def calculate_engagement_score(self, user_id: str) -> float:
        """Calculate user's overall engagement score"""
        try:
            now = datetime.utcnow()
            month_ago = now - timedelta(days=30)

            # Weight factors for different activities
            weights = {
                "message": 1,
                "reaction": 0.5,
                "connection": 5,
                "event": 10,
                "profile_update": 2,
                "endorsement": 3
            }

            # Get monthly activities
            activities = await self.db.user_activity.find({
                "user_id": user_id,
                "timestamp": {"$gte": month_ago}
            }).to_list(length=None)

            # Calculate weighted score
            score = sum(weights.get(activity.get("type"), 0) for activity in activities)

            # Normalize score (0-100)
            max_score = 1000  # Arbitrary max score
            normalized_score = min(100, (score / max_score) * 100)

            return round(normalized_score, 2)

        except Exception as e:
            logger.error(f"Error calculating engagement score: {str(e)}")
            return 0.0

    @commands.group(invoke_without_command=True)
    async def dashboard(self, ctx):
        """Dashboard management commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="🖥️ Dashboard Commands",
                description="Manage your dashboard access",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!dashboard link` - Get dashboard access link
                `!dashboard revoke` - Revoke dashboard access
                `!dashboard privacy` - Update privacy settings
                `!dashboard export` - Export your data (GDPR)
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @dashboard.command(name="link")
    async def dashboard_link(self, ctx):
        """Get dashboard access link"""
        try:
            # Generate new token
            token = self.generate_token(str(ctx.author.id))
            
            # Store token
            await self.api_tokens.insert_one({
                "user_id": str(ctx.author.id),
                "token": token,
                "created_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + self.token_expiry
            })

            # Send DM with link
            dashboard_url = f"http://localhost:3000/auth?token={token}"  # Update with actual URL
            
            embed = nextcord.Embed(
                title="🔗 Dashboard Access",
                description="Click the link below to access your dashboard:",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Link",
                value=f"[Access Dashboard]({dashboard_url})",
                inline=False
            )
            embed.add_field(
                name="Note",
                value="This link will expire in 7 days. Keep it private!",
                inline=False
            )
            
            try:
                await ctx.author.send(embed=embed)
                await ctx.send("✅ Dashboard access link sent to your DMs!")
            except nextcord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

        except Exception as e:
            logger.error(f"Error generating dashboard link: {str(e)}")
            await ctx.send("❌ An error occurred while generating your dashboard link.")

    @dashboard.command(name="revoke")
    async def dashboard_revoke(self, ctx):
        """Revoke all dashboard access tokens"""
        try:
            result = await self.api_tokens.delete_many({
                "user_id": str(ctx.author.id)
            })
            
            await ctx.send(f"✅ Revoked {result.deleted_count} dashboard access tokens.")

        except Exception as e:
            logger.error(f"Error revoking tokens: {str(e)}")
            await ctx.send("❌ An error occurred while revoking your tokens.")

    @dashboard.command(name="privacy")
    async def dashboard_privacy(self, ctx):
        """Update dashboard privacy settings"""
        try:
            # Send privacy options
            embed = nextcord.Embed(
                title="🔒 Dashboard Privacy Settings",
                description="React to update your privacy preferences:",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Options",
                value="""
                1️⃣ Show online status
                2️⃣ Show connection count
                3️⃣ Show skills and endorsements
                4️⃣ Show event participation
                ❌ Hide all information
                """,
                inline=False
            )
            
            msg = await ctx.send(embed=embed)
            for emoji in ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '❌']:
                await msg.add_reaction(emoji)

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '❌']

            try:
                reaction, _ = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
                
                # Update privacy settings
                settings = {
                    "show_online_status": False,
                    "show_connections": False,
                    "show_skills": False,
                    "show_events": False
                }

                if str(reaction.emoji) == '1️⃣':
                    settings["show_online_status"] = True
                elif str(reaction.emoji) == '2️⃣':
                    settings["show_connections"] = True
                elif str(reaction.emoji) == '3️⃣':
                    settings["show_skills"] = True
                elif str(reaction.emoji) == '4️⃣':
                    settings["show_events"] = True
                # ❌ keeps all settings false

                await self.user_settings.update_one(
                    {"user_id": str(ctx.author.id)},
                    {
                        "$set": {
                            "privacy": settings,
                            "updated_at": datetime.utcnow()
                        }
                    },
                    upsert=True
                )

                await ctx.send("✅ Privacy settings updated!")

            except asyncio.TimeoutError:
                await ctx.send("❌ Privacy settings update timed out.")

        except Exception as e:
            logger.error(f"Error updating privacy settings: {str(e)}")
            await ctx.send("❌ An error occurred while updating privacy settings.")

    @dashboard.command(name="export")
    async def dashboard_export(self, ctx):
        """Export user data (GDPR compliance)"""
        try:
            # Collect user data
            user_data = {
                "profile": await self.db.profiles.find_one({"user_id": str(ctx.author.id)}),
                "connections": await self.get_user_connections(str(ctx.author.id)),
                "activities": await self.db.user_activity.find({
                    "user_id": str(ctx.author.id)
                }).to_list(length=None),
                "settings": await self.user_settings.find_one({"user_id": str(ctx.author.id)}),
                "events": await self.db.event_registrations.find({
                    "user_id": str(ctx.author.id)
                }).to_list(length=None)
            }

            # Convert to JSON
            json_data = json.dumps(user_data, default=str, indent=2)
            
            # Send as file
            file = nextcord.File(
                fp=io.StringIO(json_data),
                filename=f"user_data_{ctx.author.id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
            )
            
            try:
                await ctx.author.send("Here's your exported data:", file=file)
                await ctx.send("✅ Your data has been sent to your DMs!")
            except nextcord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

        except Exception as e:
            logger.error(f"Error exporting user data: {str(e)}")
            await ctx.send("❌ An error occurred while exporting your data.")

def setup(bot):
    """Setup the Dashboard Integration cog"""
    bot.add_cog(DashboardIntegration(bot))
    logger.info("Dashboard Integration cog loaded successfully")