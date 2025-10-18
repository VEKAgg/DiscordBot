import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime, timedelta
import asyncio
from typing import List, Dict, Optional
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from collections import Counter

logger = logging.getLogger('VEKA.connections')

class Connections(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.connections = self.db.connections
        self.connection_requests = self.db.connection_requests
        self.user_profiles = self.db.profiles
        self.connection_cache = {}
        self.recommendation_cooldowns = {}

    async def get_pending_requests(self, user_id: str) -> List[Dict]:
        """Get pending connection requests for a user"""
        return await self.connection_requests.find({
            "target_id": user_id,
            "status": "pending"
        }).to_list(length=None)

    async def get_user_connections(self, user_id: str) -> List[str]:
        """Get list of user IDs that are connected to given user"""
        if user_id in self.connection_cache:
            return self.connection_cache[user_id]

        connections = await self.connections.find({
            "$or": [
                {"user_id": user_id},
                {"connected_id": user_id}
            ],
            "status": "connected"
        }).to_list(length=None)

        connected_ids = []
        for conn in connections:
            if conn["user_id"] == user_id:
                connected_ids.append(conn["connected_id"])
            else:
                connected_ids.append(conn["user_id"])

        self.connection_cache[user_id] = connected_ids
        return connected_ids

    async def compute_similarity(self, profile1: Dict, profile2: Dict) -> float:
        """Compute similarity score between two profiles"""
        score = 0.0
        total_weight = 0.0

        # Skills similarity (highest weight)
        weight = 0.4
        skills1 = set(profile1.get("skills", []))
        skills2 = set(profile2.get("skills", []))
        if skills1 and skills2:
            score += weight * len(skills1.intersection(skills2)) / len(skills1.union(skills2))
        total_weight += weight

        # Industry similarity
        weight = 0.2
        if "industry" in profile1 and "industry" in profile2:
            score += weight * (profile1["industry"] == profile2["industry"])
        total_weight += weight

        # Interests similarity
        weight = 0.2
        interests1 = set(profile1.get("interests", []))
        interests2 = set(profile2.get("interests", []))
        if interests1 and interests2:
            score += weight * len(interests1.intersection(interests2)) / len(interests1.union(interests2))
        total_weight += weight

        # Experience level similarity
        weight = 0.2
        exp1 = profile1.get("experience_years", 0)
        exp2 = profile2.get("experience_years", 0)
        if exp1 and exp2:
            score += weight * (1 - abs(exp1 - exp2) / max(exp1, exp2))
        total_weight += weight

        return score / total_weight if total_weight > 0 else 0.0

    @commands.group(invoke_without_command=True)
    async def connections(self, ctx):
        """Connection and networking commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="🤝 Connection Commands",
                description="Build your professional network",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!connections list` - List your connections
                `!connections add @user` - Send connection request
                `!connections remove @user` - Remove connection
                `!connections pending` - View pending requests
                `!connections accept @user` - Accept connection request
                `!connections decline @user` - Decline connection request
                `!connections recommend` - Get connection recommendations
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @connections.command(name="list")
    async def connections_list(self, ctx):
        """List your connections"""
        connected_ids = await self.get_user_connections(str(ctx.author.id))
        if not connected_ids:
            await ctx.send("You don't have any connections yet!")
            return

        embed = nextcord.Embed(
            title="🤝 Your Network",
            description=f"You have {len(connected_ids)} connections",
            color=nextcord.Color.blue()
        )

        # Get connection details
        for connected_id in connected_ids[:10]:  # Show first 10
            profile = await self.user_profiles.find_one({"user_id": connected_id})
            if profile:
                user = self.bot.get_user(int(connected_id))
                if user:
                    embed.add_field(
                        name=user.display_name,
                        value=f"""
                        Title: {profile.get('title', 'Not set')}
                        Skills: {', '.join(profile.get('skills', [])[:3])}
                        Connected since: {profile.get('connection_date', 'Unknown')}
                        """,
                        inline=False
                    )

        if len(connected_ids) > 10:
            embed.set_footer(text=f"Showing 10 of {len(connected_ids)} connections")

        await ctx.send(embed=embed)

    @connections.command(name="add")
    async def connections_add(self, ctx, user: nextcord.Member):
        """Send a connection request"""
        if user == ctx.author:
            await ctx.send("❌ You can't connect with yourself!")
            return

        # Check if already connected
        connected_ids = await self.get_user_connections(str(ctx.author.id))
        if str(user.id) in connected_ids:
            await ctx.send("You're already connected with this user!")
            return

        # Check if request already exists
        existing = await self.connection_requests.find_one({
            "$or": [
                {
                    "user_id": str(ctx.author.id),
                    "target_id": str(user.id)
                },
                {
                    "user_id": str(user.id),
                    "target_id": str(ctx.author.id)
                }
            ],
            "status": "pending"
        })

        if existing:
            await ctx.send("A connection request already exists between you and this user!")
            return

        # Create connection request
        request = {
            "user_id": str(ctx.author.id),
            "target_id": str(user.id),
            "status": "pending",
            "created_at": datetime.utcnow()
        }
        await self.connection_requests.insert_one(request)

        # Notify target user
        embed = nextcord.Embed(
            title="🤝 New Connection Request",
            description=f"{ctx.author.mention} wants to connect with you!",
            color=nextcord.Color.blue()
        )

        # Add sender's profile info
        profile = await self.user_profiles.find_one({"user_id": str(ctx.author.id)})
        if profile:
            embed.add_field(
                name="About",
                value=f"""
                Title: {profile.get('title', 'Not set')}
                Skills: {', '.join(profile.get('skills', [])[:3])}
                """,
                inline=False
            )

        embed.add_field(
            name="Actions",
            value="""
            Use `!connections accept @user` to accept
            Use `!connections decline @user` to decline
            """,
            inline=False
        )

        try:
            await user.send(embed=embed)
        except nextcord.Forbidden:
            pass  # User has DMs disabled

        await ctx.send(f"✅ Connection request sent to {user.mention}")

    @connections.command(name="accept")
    async def connections_accept(self, ctx, user: nextcord.Member):
        """Accept a connection request"""
        request = await self.connection_requests.find_one({
            "user_id": str(user.id),
            "target_id": str(ctx.author.id),
            "status": "pending"
        })

        if not request:
            await ctx.send("No pending connection request from this user!")
            return

        # Create connection
        connection = {
            "user_id": str(user.id),
            "connected_id": str(ctx.author.id),
            "status": "connected",
            "connected_at": datetime.utcnow()
        }
        await self.connections.insert_one(connection)

        # Update request status
        await self.connection_requests.update_one(
            {"_id": request["_id"]},
            {"$set": {"status": "accepted"}}
        )

        # Clear cache
        self.connection_cache.pop(str(user.id), None)
        self.connection_cache.pop(str(ctx.author.id), None)

        # Notify both users
        embed = nextcord.Embed(
            title="🤝 Connection Accepted",
            description=f"You are now connected with {ctx.author.mention}!",
            color=nextcord.Color.green()
        )
        try:
            await user.send(embed=embed)
        except nextcord.Forbidden:
            pass

        embed.description = f"You are now connected with {user.mention}!"
        await ctx.send(embed=embed)

    @connections.command(name="decline")
    async def connections_decline(self, ctx, user: nextcord.Member):
        """Decline a connection request"""
        result = await self.connection_requests.update_one(
            {
                "user_id": str(user.id),
                "target_id": str(ctx.author.id),
                "status": "pending"
            },
            {
                "$set": {
                    "status": "declined",
                    "declined_at": datetime.utcnow()
                }
            }
        )

        if result.modified_count > 0:
            await ctx.send(f"Declined connection request from {user.mention}")
        else:
            await ctx.send("No pending connection request from this user!")

    @connections.command(name="remove")
    async def connections_remove(self, ctx, user: nextcord.Member):
        """Remove a connection"""
        result = await self.connections.update_one(
            {
                "$or": [
                    {
                        "user_id": str(ctx.author.id),
                        "connected_id": str(user.id)
                    },
                    {
                        "user_id": str(user.id),
                        "connected_id": str(ctx.author.id)
                    }
                ],
                "status": "connected"
            },
            {
                "$set": {
                    "status": "removed",
                    "removed_at": datetime.utcnow()
                }
            }
        )

        if result.modified_count > 0:
            # Clear cache
            self.connection_cache.pop(str(user.id), None)
            self.connection_cache.pop(str(ctx.author.id), None)
            
            await ctx.send(f"✅ Removed connection with {user.mention}")
        else:
            await ctx.send("You're not connected with this user!")

    @connections.command(name="pending")
    async def connections_pending(self, ctx):
        """View pending connection requests"""
        # Get incoming requests
        incoming = await self.connection_requests.find({
            "target_id": str(ctx.author.id),
            "status": "pending"
        }).to_list(length=None)

        # Get outgoing requests
        outgoing = await self.connection_requests.find({
            "user_id": str(ctx.author.id),
            "status": "pending"
        }).to_list(length=None)

        if not incoming and not outgoing:
            await ctx.send("No pending connection requests!")
            return

        embed = nextcord.Embed(
            title="📫 Pending Connections",
            color=nextcord.Color.blue()
        )

        if incoming:
            value = "\n".join([
                f"• {self.bot.get_user(int(req['user_id'])).mention} - {req['created_at'].strftime('%Y-%m-%d')}"
                for req in incoming if self.bot.get_user(int(req['user_id']))
            ])
            embed.add_field(
                name=f"Incoming Requests ({len(incoming)})",
                value=value or "None",
                inline=False
            )

        if outgoing:
            value = "\n".join([
                f"• {self.bot.get_user(int(req['target_id'])).mention} - {req['created_at'].strftime('%Y-%m-%d')}"
                for req in outgoing if self.bot.get_user(int(req['target_id']))
            ])
            embed.add_field(
                name=f"Outgoing Requests ({len(outgoing)})",
                value=value or "None",
                inline=False
            )

        await ctx.send(embed=embed)

    @connections.command(name="recommend")
    async def connections_recommend(self, ctx):
        """Get connection recommendations"""
        user_id = str(ctx.author.id)

        # Check cooldown
        if user_id in self.recommendation_cooldowns:
            remaining = (self.recommendation_cooldowns[user_id] + timedelta(hours=24)) - datetime.utcnow()
            if remaining.total_seconds() > 0:
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                await ctx.send(f"Please wait {hours}h {minutes}m for new recommendations.")
                return

        # Get user's profile
        user_profile = await self.user_profiles.find_one({"user_id": user_id})
        if not user_profile:
            await ctx.send("Please set up your profile first using `!profile setup`")
            return

        # Get user's current connections
        connected_ids = await self.get_user_connections(user_id)
        
        # Get all active profiles except user's own and current connections
        profiles = await self.user_profiles.find({
            "user_id": {
                "$nin": [user_id] + connected_ids
            },
            "active": True
        }).to_list(length=None)

        if not profiles:
            await ctx.send("No recommendations available at this time.")
            return

        # Calculate similarity scores
        recommendations = []
        for profile in profiles:
            score = await self.compute_similarity(user_profile, profile)
            if score > 0:
                recommendations.append((profile, score))

        # Sort by similarity score
        recommendations.sort(key=lambda x: x[1], reverse=True)

        # Create recommendations embed
        embed = nextcord.Embed(
            title="👥 Recommended Connections",
            description="People you might want to connect with:",
            color=nextcord.Color.blue()
        )

        for profile, score in recommendations[:5]:
            user = self.bot.get_user(int(profile["user_id"]))
            if user:
                common_skills = set(user_profile.get("skills", [])) & set(profile.get("skills", []))
                embed.add_field(
                    name=f"{user.display_name} ({score:.0%} match)",
                    value=f"""
                    Title: {profile.get('title', 'Not set')}
                    Skills in common: {', '.join(list(common_skills)[:3])}
                    Industry: {profile.get('industry', 'Not set')}
                    Use `!connections add @{user.name}` to connect
                    """,
                    inline=False
                )

        # Update cooldown
        self.recommendation_cooldowns[user_id] = datetime.utcnow()

        await ctx.send(embed=embed)

def setup(bot):
    """Setup the Connections cog"""
    bot.add_cog(Connections(bot))
    logger.info("Connections cog loaded successfully")