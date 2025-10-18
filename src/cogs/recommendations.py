import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import asyncio
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

logger = logging.getLogger('VEKA.recommendations')

class Recommendations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.recommendations = self.db.recommendations
        self.user_preferences = self.db.user_preferences
        self.vectorizer = TfidfVectorizer(stop_words='english')
        self.check_inactive_users.start()
        self.update_recommendations.start()

    def cog_unload(self):
        self.check_inactive_users.cancel()
        self.update_recommendations.cancel()

    @tasks.loop(hours=24)
    async def check_inactive_users(self):
        """Check for inactive users and send reminders"""
        try:
            # Get user activity data
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            async for user in self.db.users.find({"last_active": {"$lt": seven_days_ago}}):
                discord_user = self.bot.get_user(int(user['discord_id']))
                if discord_user:
                    try:
                        embed = nextcord.Embed(
                            title="👋 We Miss You!",
                            description=(
                                f"Hey {discord_user.name}! We noticed you haven't been active "
                                "in the community lately. Here's what you've missed:"
                            ),
                            color=nextcord.Color.blue()
                        )
                        
                        # Get pending connections
                        pending_connections = await self.db.connections.count_documents({
                            "user2_id": str(discord_user.id),
                            "status": "pending"
                        })
                        if pending_connections:
                            embed.add_field(
                                name="📫 Pending Connections",
                                value=f"You have {pending_connections} pending connection requests",
                                inline=False
                            )

                        # Get new recommendations
                        recommendations = await self.get_top_recommendations(str(discord_user.id), limit=3)
                        if recommendations:
                            rec_text = "\n".join([f"• {rec['reason']}" for rec in recommendations])
                            embed.add_field(
                                name="👥 New Recommendations",
                                value=rec_text,
                                inline=False
                            )

                        embed.add_field(
                            name="🔄 Ready to Return?",
                            value="Use `!profile update` to refresh your profile and start connecting!",
                            inline=False
                        )

                        await discord_user.send(embed=embed)
                        
                    except nextcord.Forbidden:
                        logger.warning(f"Could not send inactive reminder to {discord_user.id}")
                        continue

        except Exception as e:
            logger.error(f"Error checking inactive users: {str(e)}")

    @tasks.loop(hours=24)
    async def update_recommendations(self):
        """Update recommendations for all users"""
        try:
            async for user in self.db.users.find({}):
                discord_id = user['discord_id']
                preferences = await self.user_preferences.find_one({"user_id": discord_id})
                
                if not preferences or preferences.get('recommendation_frequency') == 'off':
                    continue

                frequency = preferences.get('recommendation_frequency', 'weekly')
                last_update = preferences.get('last_recommendation_update', datetime.min)
                
                # Check if it's time to update based on frequency
                should_update = False
                if frequency == 'daily':
                    should_update = datetime.utcnow() - last_update > timedelta(days=1)
                elif frequency == 'weekly':
                    should_update = datetime.utcnow() - last_update > timedelta(days=7)
                elif frequency == 'monthly':
                    should_update = datetime.utcnow() - last_update > timedelta(days=30)

                if should_update:
                    recommendations = await self.generate_recommendations(discord_id)
                    if recommendations:
                        discord_user = self.bot.get_user(int(discord_id))
                        if discord_user:
                            await self.send_recommendation_dm(discord_user, recommendations)
                            
                        # Update last recommendation time
                        await self.user_preferences.update_one(
                            {"user_id": discord_id},
                            {
                                "$set": {
                                    "last_recommendation_update": datetime.utcnow()
                                }
                            },
                            upsert=True
                        )

        except Exception as e:
            logger.error(f"Error updating recommendations: {str(e)}")

    async def generate_recommendations(self, user_id: str) -> List[Dict]:
        """Generate personalized recommendations using ML"""
        try:
            user_profile = await self.db.profiles.find_one({"user_id": user_id})
            if not user_profile:
                return []

            recommendations = []

            # Get connection recommendations
            connection_recs = await self.get_connection_recommendations(user_id)
            recommendations.extend(connection_recs)

            # Get skill recommendations
            skill_recs = await self.get_skill_recommendations(user_id)
            recommendations.extend(skill_recs)

            # Get event recommendations
            event_recs = await self.get_event_recommendations(user_id)
            recommendations.extend(event_recs)

            return recommendations

        except Exception as e:
            logger.error(f"Error generating recommendations: {str(e)}")
            return []

    async def get_connection_recommendations(self, user_id: str) -> List[Dict]:
        """Get recommended connections based on profile similarity"""
        user_profile = await self.db.profiles.find_one({"user_id": user_id})
        if not user_profile:
            return []

        # Get all other profiles
        other_profiles = await self.db.profiles.find({"user_id": {"$ne": user_id}}).to_list(length=None)
        if not other_profiles:
            return []

        # Prepare profile texts
        profile_texts = []
        profile_ids = []
        
        # Add user's profile
        user_text = f"{user_profile.get('title', '')} {user_profile.get('headline', '')} {' '.join(user_profile.get('skills', []))}"
        profile_texts.append(user_text)
        profile_ids.append(user_id)

        # Add other profiles
        for profile in other_profiles:
            text = f"{profile.get('title', '')} {profile.get('headline', '')} {' '.join(profile.get('skills', []))}"
            profile_texts.append(text)
            profile_ids.append(profile['user_id'])

        # Calculate similarities
        try:
            tfidf_matrix = self.vectorizer.fit_transform(profile_texts)
            similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:])
            
            recommendations = []
            for idx, score in enumerate(similarities[0]):
                if score > 0.3:  # Minimum similarity threshold
                    profile = other_profiles[idx]
                    common_skills = set(user_profile.get('skills', [])) & set(profile.get('skills', []))
                    recommendations.append({
                        'type': 'connection',
                        'user_id': profile['user_id'],
                        'score': float(score),
                        'reason': f"Professional with similar background in {', '.join(common_skills) if common_skills else profile.get('title', 'your field')}",
                        'action': f"Use !connect with @{self.bot.get_user(int(profile['user_id'])).name if self.bot.get_user(int(profile['user_id'])) else 'user'}"
                    })
            
            recommendations.sort(key=lambda x: x['score'], reverse=True)
            return recommendations[:5]  # Return top 5 connection recommendations
            
        except Exception as e:
            logger.error(f"Error calculating connection recommendations: {str(e)}")
            return []

    async def get_skill_recommendations(self, user_id: str) -> List[Dict]:
        """Get skill recommendations based on user's profile and industry trends"""
        try:
            user_profile = await self.db.profiles.find_one({"user_id": user_id})
            if not user_profile:
                return []

            current_skills = set(user_profile.get('skills', []))
            recommended_skills = set()

            # Get skills from successful professionals in the same field
            similar_profiles = await self.db.profiles.find({
                "title": {"$regex": user_profile.get('title', ''), "$options": 'i'},
                "user_id": {"$ne": user_id}
            }).limit(10).to_list(length=None)

            for profile in similar_profiles:
                recommended_skills.update(profile.get('skills', []))

            # Remove skills the user already has
            recommended_skills = recommended_skills - current_skills

            # Convert to recommendation format
            return [
                {
                    'type': 'skill',
                    'skill': skill,
                    'reason': f"Popular skill among {user_profile.get('title', 'professionals')} in your field",
                    'action': "Update your profile to add this skill"
                }
                for skill in list(recommended_skills)[:3]  # Top 3 skill recommendations
            ]

        except Exception as e:
            logger.error(f"Error generating skill recommendations: {str(e)}")
            return []

    async def get_event_recommendations(self, user_id: str) -> List[Dict]:
        """Get event recommendations based on user's interests and location"""
        try:
            user_profile = await self.db.profiles.find_one({"user_id": user_id})
            if not user_profile:
                return []

            # Get upcoming events
            upcoming_events = await self.db.events.find({
                "date": {"$gt": datetime.utcnow()}
            }).sort("date", 1).to_list(length=None)

            if not upcoming_events:
                return []

            recommendations = []
            user_skills = set(user_profile.get('skills', []))

            for event in upcoming_events:
                event_tags = set(event.get('tags', []))
                if user_skills & event_tags:  # If there's overlap in skills/tags
                    recommendations.append({
                        'type': 'event',
                        'event_id': str(event['_id']),
                        'title': event['title'],
                        'reason': f"Event matching your interests in {', '.join(user_skills & event_tags)}",
                        'action': f"Use !event join {event['_id']} to register"
                    })

            return recommendations[:3]  # Return top 3 event recommendations

        except Exception as e:
            logger.error(f"Error generating event recommendations: {str(e)}")
            return []

    async def send_recommendation_dm(self, user: nextcord.User, recommendations: List[Dict]):
        """Send personalized recommendations via DM"""
        try:
            embed = nextcord.Embed(
                title="🎯 Personalized Recommendations",
                description="Here are some recommendations based on your profile:",
                color=nextcord.Color.blue()
            )

            # Group recommendations by type
            connections = [r for r in recommendations if r['type'] == 'connection']
            skills = [r for r in recommendations if r['type'] == 'skill']
            events = [r for r in recommendations if r['type'] == 'event']

            if connections:
                connections_text = "\n".join([f"• {r['reason']}\n  → {r['action']}" for r in connections[:3]])
                embed.add_field(
                    name="🤝 Recommended Connections",
                    value=connections_text,
                    inline=False
                )

            if skills:
                skills_text = "\n".join([f"• {r['skill']}: {r['reason']}" for r in skills])
                embed.add_field(
                    name="🌟 Recommended Skills",
                    value=skills_text,
                    inline=False
                )

            if events:
                events_text = "\n".join([f"• {r['title']}: {r['reason']}" for r in events])
                embed.add_field(
                    name="📅 Recommended Events",
                    value=events_text,
                    inline=False
                )

            embed.set_footer(text="Use !recommendations settings to adjust notification frequency")
            await user.send(embed=embed)

        except nextcord.Forbidden:
            logger.warning(f"Could not send recommendations to user {user.id}")
        except Exception as e:
            logger.error(f"Error sending recommendations: {str(e)}")

    @commands.group(invoke_without_command=True)
    async def recommendations(self, ctx):
        """View and manage your recommendations"""
        if ctx.invoked_subcommand is None:
            recommendations = await self.generate_recommendations(str(ctx.author.id))
            if not recommendations:
                await ctx.send("No recommendations available at this time. Try updating your profile!")
                return

            embed = nextcord.Embed(
                title="🎯 Your Recommendations",
                description="Here's what we recommend for you:",
                color=nextcord.Color.blue()
            )

            # Group and display recommendations
            for rec_type in ['connection', 'skill', 'event']:
                type_recs = [r for r in recommendations if r['type'] == rec_type]
                if type_recs:
                    title = {
                        'connection': '🤝 Recommended Connections',
                        'skill': '🌟 Recommended Skills',
                        'event': '📅 Recommended Events'
                    }[rec_type]
                    
                    content = "\n".join([f"• {r['reason']}\n  → {r['action']}" for r in type_recs[:3]])
                    embed.add_field(name=title, value=content, inline=False)

            embed.set_footer(text="Use !recommendations settings to adjust your preferences")
            await ctx.send(embed=embed)

    @recommendations.command(name="settings")
    async def recommendation_settings(self, ctx):
        """Update your recommendation preferences"""
        embed = nextcord.Embed(
            title="⚙️ Recommendation Settings",
            description="Choose how often you want to receive recommendations:",
            color=nextcord.Color.blue()
        )
        embed.add_field(
            name="Frequency Options",
            value="🔵 Daily\n🟢 Weekly\n🟡 Monthly\n⚫ Off",
            inline=False
        )
        msg = await ctx.send(embed=embed)
        
        for emoji in ['🔵', '🟢', '🟡', '⚫']:
            await msg.add_reaction(emoji)

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ['🔵', '🟢', '🟡', '⚫']

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
            frequency = {
                '🔵': 'daily',
                '🟢': 'weekly',
                '🟡': 'monthly',
                '⚫': 'off'
            }[str(reaction.emoji)]

            await self.user_preferences.update_one(
                {"user_id": str(ctx.author.id)},
                {
                    "$set": {
                        "recommendation_frequency": frequency,
                        "updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )

            await ctx.send(f"✅ Your recommendation frequency has been updated to: {frequency}")

        except asyncio.TimeoutError:
            await ctx.send("❌ Settings update timed out. Please try again.")

def setup(bot):
    """Setup the Recommendations cog"""
    bot.add_cog(Recommendations(bot))
    logger.info("Recommendations cog loaded successfully")