import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime
import aiohttp
import asyncio
from typing import List, Dict, Optional
import json

logger = logging.getLogger('VEKA.skills')

class Skills(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.skills = self.db.skills
        self.endorsements = self.db.endorsements
        self.user_profiles = self.db.profiles
        self.github_cache = {}
        self.leetcode_cache = {}
        self.sync_external_skills.start()

    def cog_unload(self):
        self.sync_external_skills.cancel()

    @tasks.loop(hours=24)
    async def sync_external_skills(self):
        """Daily sync of skills from external platforms"""
        try:
            async for user in self.user_profiles.find({"external_accounts": {"$exists": True}}):
                discord_id = user["user_id"]
                external_accounts = user.get("external_accounts", {})
                
                if github_username := external_accounts.get("github"):
                    await self.sync_github_skills(discord_id, github_username)
                
                if leetcode_username := external_accounts.get("leetcode"):
                    await self.sync_leetcode_skills(discord_id, leetcode_username)
                
                logger.info(f"Synced external skills for user {discord_id}")
                await asyncio.sleep(1)  # Rate limiting
                
        except Exception as e:
            logger.error(f"Error in sync_external_skills: {str(e)}")

    @commands.group(invoke_without_command=True)
    async def skills(self, ctx):
        """Manage your skills and endorsements"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="🌟 Skills Management",
                description="Manage your professional skills and endorsements",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!skills list [@user]` - View your or someone's skills
                `!skills add <skill>` - Add a new skill
                `!skills remove <skill>` - Remove a skill
                `!skills endorse @user <skill>` - Endorse someone's skill
                `!skills sync github` - Sync skills from GitHub
                `!skills sync leetcode` - Sync skills from LeetCode
                `!skills top` - View top endorsed skills
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @skills.command(name="list")
    async def skills_list(self, ctx, member: Optional[nextcord.Member] = None):
        """List skills and their endorsements"""
        target = member or ctx.author
        user_profile = await self.user_profiles.find_one({"user_id": str(target.id)})
        
        if not user_profile or not user_profile.get("skills"):
            if target == ctx.author:
                await ctx.send("You haven't added any skills yet! Use `!skills add <skill>` to add some.")
            else:
                await ctx.send(f"{target.display_name} hasn't added any skills yet.")
            return

        embed = nextcord.Embed(
            title=f"🌟 {target.display_name}'s Skills",
            color=nextcord.Color.blue()
        )

        # Get endorsements for all skills
        all_endorsements = await self.endorsements.find({
            "user_id": str(target.id)
        }).to_list(length=None)

        # Group endorsements by skill
        skill_endorsements = {}
        for end in all_endorsements:
            skill = end["skill"]
            if skill not in skill_endorsements:
                skill_endorsements[skill] = []
            skill_endorsements[skill].append(end)

        # Display skills with endorsements
        for skill in sorted(user_profile["skills"]):
            endorsements = skill_endorsements.get(skill, [])
            endorsers = [self.bot.get_user(int(e["endorser_id"])).name for e in endorsements if self.bot.get_user(int(e["endorser_id"]))]
            value = f"Endorsements: {len(endorsements)}\n"
            if endorsers:
                value += f"Endorsed by: {', '.join(endorsers[:3])}"
                if len(endorsers) > 3:
                    value += f" and {len(endorsers)-3} more"
            embed.add_field(name=skill, value=value, inline=False)

        # Add verification badges if accounts are linked
        external_accounts = user_profile.get("external_accounts", {})
        if external_accounts:
            verification = []
            if "github" in external_accounts:
                verification.append("✓ GitHub Verified")
            if "leetcode" in external_accounts:
                verification.append("✓ LeetCode Verified")
            if verification:
                embed.add_field(
                    name="Verifications",
                    value="\n".join(verification),
                    inline=False
                )

        await ctx.send(embed=embed)

    @skills.command(name="add")
    async def skills_add(self, ctx, *, skill: str):
        """Add a new skill to your profile"""
        skill = skill.strip().lower()
        
        # Update user profile
        result = await self.user_profiles.update_one(
            {"user_id": str(ctx.author.id)},
            {
                "$addToSet": {"skills": skill},
                "$set": {"updated_at": datetime.utcnow()}
            },
            upsert=True
        )

        if result.modified_count > 0:
            await ctx.send(f"✅ Added skill: {skill}")
        else:
            await ctx.send(f"You already have the skill: {skill}")

    @skills.command(name="endorse")
    async def skills_endorse(self, ctx, member: nextcord.Member, *, skill: str):
        """Endorse someone's skill"""
        if member == ctx.author:
            await ctx.send("❌ You can't endorse your own skills!")
            return

        skill = skill.strip().lower()
        
        # Check if user has the skill
        user_profile = await self.user_profiles.find_one({
            "user_id": str(member.id),
            "skills": skill
        })
        
        if not user_profile:
            await ctx.send(f"❌ {member.display_name} doesn't have {skill} listed in their skills.")
            return

        # Check if already endorsed
        existing = await self.endorsements.find_one({
            "user_id": str(member.id),
            "endorser_id": str(ctx.author.id),
            "skill": skill
        })
        
        if existing:
            await ctx.send(f"You've already endorsed {member.display_name} for {skill}!")
            return

        # Create endorsement
        endorsement = {
            "user_id": str(member.id),
            "endorser_id": str(ctx.author.id),
            "skill": skill,
            "created_at": datetime.utcnow()
        }
        await self.endorsements.insert_one(endorsement)

        # Notify the user
        embed = nextcord.Embed(
            title="🌟 New Skill Endorsement!",
            description=f"{ctx.author.mention} has endorsed you for {skill}!",
            color=nextcord.Color.gold()
        )
        try:
            await member.send(embed=embed)
        except nextcord.Forbidden:
            pass  # User has DMs disabled

        await ctx.send(f"✅ You've endorsed {member.display_name} for {skill}!")

    @skills.command(name="sync")
    async def skills_sync(self, ctx, platform: str):
        """Sync skills from external platforms"""
        platform = platform.lower()
        if platform not in ["github", "leetcode"]:
            await ctx.send("❌ Supported platforms: github, leetcode")
            return

        # Get user profile
        user_profile = await self.user_profiles.find_one({"user_id": str(ctx.author.id)})
        if not user_profile:
            await ctx.send("Set up your profile first with `!profile setup`")
            return

        if platform == "github":
            await ctx.send("Please enter your GitHub username:")
        else:
            await ctx.send("Please enter your LeetCode username:")

        try:
            msg = await self.bot.wait_for(
                'message',
                timeout=30.0,
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel
            )
            username = msg.content.strip()

            # Update external accounts
            await self.user_profiles.update_one(
                {"user_id": str(ctx.author.id)},
                {
                    "$set": {
                        f"external_accounts.{platform}": username,
                        "updated_at": datetime.utcnow()
                    }
                }
            )

            # Sync skills
            if platform == "github":
                skills = await self.sync_github_skills(str(ctx.author.id), username)
            else:
                skills = await self.sync_leetcode_skills(str(ctx.author.id), username)

            if skills:
                await ctx.send(f"✅ Synced {len(skills)} skills from your {platform.title()} profile!")
            else:
                await ctx.send(f"No new skills found from {platform.title()}.")

        except asyncio.TimeoutError:
            await ctx.send("❌ Sync request timed out. Please try again.")
        except Exception as e:
            logger.error(f"Error syncing skills: {str(e)}")
            await ctx.send(f"❌ Error syncing skills from {platform.title()}. Please try again later.")

    async def sync_github_skills(self, discord_id: str, github_username: str) -> List[str]:
        """Sync skills from GitHub profile"""
        try:
            # Use GitHub API to get user's repositories and languages
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.github.com/users/{github_username}/repos",
                    headers={"Accept": "application/vnd.github.v3+json"}
                ) as resp:
                    if resp.status != 200:
                        return []
                    repos = await resp.json()

            # Extract languages from repos
            skills = set()
            for repo in repos:
                if langs := repo.get("language"):
                    skills.add(langs.lower())
                
                # Get languages breakdown
                if langs_url := repo.get("languages_url"):
                    async with aiohttp.ClientSession() as session:
                        async with session.get(langs_url) as resp:
                            if resp.status == 200:
                                languages = await resp.json()
                                skills.update(lang.lower() for lang in languages.keys())

            # Update user's skills
            if skills:
                await self.user_profiles.update_one(
                    {"user_id": discord_id},
                    {
                        "$addToSet": {"skills": {"$each": list(skills)}},
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )

            return list(skills)

        except Exception as e:
            logger.error(f"Error syncing GitHub skills: {str(e)}")
            return []

    async def sync_leetcode_skills(self, discord_id: str, leetcode_username: str) -> List[str]:
        """Sync skills from LeetCode profile"""
        try:
            # Use LeetCode API to get user's solved problems
            query = """
            query userProblemsSolved($username: String!) {
                allQuestionsCount {
                    difficulty
                    count
                }
                matchedUser(username: $username) {
                    submitStats {
                        acSubmissionNum {
                            difficulty
                            count
                        }
                    }
                }
            }
            """
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://leetcode.com/graphql",
                    json={
                        "query": query,
                        "variables": {"username": leetcode_username}
                    }
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()

            # Extract skills based on problem-solving stats
            skills = set()
            if "matchedUser" in data.get("data", {}):
                stats = data["data"]["matchedUser"]["submitStats"]["acSubmissionNum"]
                total_solved = sum(s["count"] for s in stats)
                
                if total_solved >= 50:
                    skills.add("data structures")
                    skills.add("algorithms")
                if total_solved >= 100:
                    skills.add("problem solving")
                if total_solved >= 200:
                    skills.add("competitive programming")

                # Add difficulty-based skills
                for stat in stats:
                    if stat["difficulty"] == "Hard" and stat["count"] >= 10:
                        skills.add("advanced algorithms")
                    elif stat["difficulty"] == "Medium" and stat["count"] >= 50:
                        skills.add("intermediate algorithms")

            # Update user's skills
            if skills:
                await self.user_profiles.update_one(
                    {"user_id": discord_id},
                    {
                        "$addToSet": {"skills": {"$each": list(skills)}},
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )

            return list(skills)

        except Exception as e:
            logger.error(f"Error syncing LeetCode skills: {str(e)}")
            return []

    @skills.command(name="top")
    async def skills_top(self, ctx):
        """View top endorsed skills in the server"""
        pipeline = [
            {
                "$group": {
                    "_id": {
                        "user_id": "$user_id",
                        "skill": "$skill"
                    },
                    "count": {"$sum": 1}
                }
            },
            {
                "$sort": {"count": -1}
            },
            {
                "$limit": 10
            }
        ]

        top_skills = await self.endorsements.aggregate(pipeline).to_list(length=None)
        
        if not top_skills:
            await ctx.send("No endorsed skills found in the server yet!")
            return

        embed = nextcord.Embed(
            title="🏆 Top Endorsed Skills",
            description="Most endorsed skills in the server",
            color=nextcord.Color.gold()
        )

        for skill_data in top_skills:
            user_id = skill_data["_id"]["user_id"]
            skill = skill_data["_id"]["skill"]
            count = skill_data["count"]
            
            user = self.bot.get_user(int(user_id))
            if user:
                embed.add_field(
                    name=f"{skill} ({count} endorsements)",
                    value=f"Mastered by {user.display_name}",
                    inline=False
                )

        await ctx.send(embed=embed)

def setup(bot):
    """Setup the Skills cog"""
    bot.add_cog(Skills(bot))
    logger.info("Skills cog loaded successfully")