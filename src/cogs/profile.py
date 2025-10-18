import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime
from typing import Optional, Dict
import json

logger = logging.getLogger('VEKA.profile')

class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.profiles = self.db.profiles
        self.privacy_levels = {
            1: "Basic (Public)",
            2: "Standard (Connections Only)",
            3: "Full (Members Only)"
        }

    @commands.group(invoke_without_command=True)
    async def profile(self, ctx, member: Optional[nextcord.Member] = None):
        """View a user's profile at their chosen privacy level"""
        target = member or ctx.author
        profile = await self.profiles.find_one({"user_id": str(target.id)})

        if not profile:
            if target == ctx.author:
                await ctx.send("You haven't set up your profile yet! Use `!profile setup` to get started.")
            else:
                await ctx.send(f"{target.display_name} hasn't set up their profile yet.")
            return

        # Check privacy level and viewer's permissions
        privacy_level = profile.get('privacy_level', 1)
        can_view_full = await self.can_view_profile(ctx.author, target, privacy_level)

        embed = await self.create_profile_embed(target, profile, can_view_full)
        await ctx.send(embed=embed)

    @profile.command(name="setup")
    async def profile_setup(self, ctx):
        """Interactive profile setup with privacy controls"""
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            # Start profile setup
            embed = nextcord.Embed(
                title="Professional Profile Setup",
                description="Let's set up your professional profile! I'll ask you a series of questions.\n"
                          "You can type 'skip' to skip any question.",
                color=nextcord.Color.blue()
            )
            await ctx.send(embed=embed)

            # Basic Info (Level 1 - Public)
            await ctx.send("📝 What's your professional title? (e.g., 'Software Engineer', 'Product Manager')")
            title = (await self.bot.wait_for('message', check=check, timeout=300)).content

            await ctx.send("🎯 What's your headline? (A brief one-liner about yourself)")
            headline = (await self.bot.wait_for('message', check=check, timeout=300)).content

            # Standard Info (Level 2 - Connections)
            await ctx.send("💼 What's your current company/organization? (Type 'skip' to keep private)")
            company = (await self.bot.wait_for('message', check=check, timeout=300)).content
            
            await ctx.send("🌟 What are your key skills? (comma-separated)")
            skills_msg = await self.bot.wait_for('message', check=check, timeout=300)
            skills = [s.strip() for s in skills_msg.content.split(',') if s.strip()]

            # Detailed Info (Level 3 - Members)
            await ctx.send("📚 Describe your experience (can be multiple lines, type 'done' when finished)")
            experience_lines = []
            while True:
                line = (await self.bot.wait_for('message', check=check, timeout=300)).content
                if line.lower() == 'done':
                    break
                experience_lines.append(line)
            experience = '\n'.join(experience_lines)

            # Privacy Settings
            privacy_embed = nextcord.Embed(
                title="Privacy Settings",
                description="Choose your profile privacy level:\n"
                           "1️⃣ Basic (Public) - Title and Headline only\n"
                           "2️⃣ Standard (Connections) - Includes Company and Skills\n"
                           "3️⃣ Full (Members) - All Information",
                color=nextcord.Color.blue()
            )
            privacy_msg = await ctx.send(embed=privacy_embed)
            for emoji in ['1️⃣', '2️⃣', '3️⃣']:
                await privacy_msg.add_reaction(emoji)

            def reaction_check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ['1️⃣', '2️⃣', '3️⃣']

            reaction, _ = await self.bot.wait_for('reaction_add', check=reaction_check, timeout=300)
            privacy_level = {'1️⃣': 1, '2️⃣': 2, '3️⃣': 3}[str(reaction.emoji)]

            # Save profile
            profile_data = {
                "user_id": str(ctx.author.id),
                "title": title if title.lower() != 'skip' else None,
                "headline": headline if headline.lower() != 'skip' else None,
                "company": company if company.lower() != 'skip' else None,
                "skills": skills,
                "experience": experience,
                "privacy_level": privacy_level,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }

            await self.profiles.update_one(
                {"user_id": str(ctx.author.id)},
                {"$set": profile_data},
                upsert=True
            )

            await ctx.send("✅ Profile setup complete! Use `!profile` to view your profile.")

        except Exception as e:
            logger.error(f"Error in profile setup: {str(e)}")
            await ctx.send("❌ An error occurred during profile setup. Please try again.")

    async def can_view_profile(self, viewer: nextcord.Member, target: nextcord.Member, privacy_level: int) -> bool:
        """Check if a user can view another user's profile at the specified privacy level"""
        if viewer == target:
            return True
        if privacy_level == 1:
            return True
        if privacy_level == 2:
            # Check if users are connected
            connection = await self.db.connections.find_one({
                "$or": [
                    {"user1_id": str(viewer.id), "user2_id": str(target.id)},
                    {"user1_id": str(target.id), "user2_id": str(viewer.id)}
                ],
                "status": "accepted"
            })
            return bool(connection)
        if privacy_level == 3:
            return True  # All server members can view level 3 profiles
        return False

    async def create_profile_embed(self, user: nextcord.Member, profile: Dict, full_view: bool) -> nextcord.Embed:
        """Create a profile embed with appropriate information based on privacy level"""
        embed = nextcord.Embed(
            title=f"{user.display_name}'s Professional Profile",
            color=nextcord.Color.blue()
        )
        embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)

        # Basic Info (Level 1)
        if profile.get('title'):
            embed.add_field(name="Title", value=profile['title'], inline=True)
        if profile.get('headline'):
            embed.add_field(name="Headline", value=profile['headline'], inline=False)

        if full_view or profile['privacy_level'] <= 2:
            # Standard Info (Level 2)
            if profile.get('company'):
                embed.add_field(name="Company", value=profile['company'], inline=True)
            if profile.get('skills'):
                embed.add_field(name="Skills", value=', '.join(profile['skills']), inline=False)

        if full_view or profile['privacy_level'] <= 3:
            # Detailed Info (Level 3)
            if profile.get('experience'):
                embed.add_field(name="Experience", value=profile['experience'], inline=False)

        embed.set_footer(text=f"Profile Privacy: {self.privacy_levels[profile['privacy_level']]}")
        return embed

def setup(bot):
    """Setup the Profile cog"""
    bot.add_cog(Profile(bot))
    logger.info("Profile cog loaded successfully")