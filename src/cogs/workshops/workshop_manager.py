import asyncio
import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from typing import Dict, List, Optional
import json
from src.database.mongodb import workshops, workshop_participants

logger = logging.getLogger('VEKA.workshops')

class WorkshopManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        self.db = bot.db.workshops
        self.participants_db = bot.db.workshop_participants

    def cog_unload(self):
        self.scheduler.shutdown()

    @commands.group(name="workshop", invoke_without_command=True)
    async def workshop(self, ctx):
        """Workshop management commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="📚 Workshop Commands",
                description="Manage and participate in virtual workshops!",
                color=nextcord.Color.orange()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!workshop create` - Create a new workshop
                `!workshop list` - List upcoming workshops
                `!workshop info <id>` - Get workshop details
                `!workshop signup <id>` - Sign up for a workshop
                `!workshop cancel <id>` - Cancel workshop registration
                `!workshop remind <id>` - Set a reminder for a workshop
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @workshop.command(name="create")
    @commands.has_permissions(manage_events=True)
    async def workshop_create(self, ctx):
        """Create a new workshop through an interactive process"""
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            # Step 1: Title
            await ctx.send("📝 What's the title of your workshop?")
            title_msg = await self.bot.wait_for('message', check=check, timeout=60)
            title = title_msg.content

            # Step 2: Description
            await ctx.send("📋 Please provide a description for your workshop:")
            desc_msg = await self.bot.wait_for('message', check=check, timeout=120)
            description = desc_msg.content

            # Step 3: Date and Time
            await ctx.send("🗓️ When will the workshop take place? (Format: YYYY-MM-DD HH:MM)")
            date_msg = await self.bot.wait_for('message', check=check, timeout=60)
            try:
                workshop_date = datetime.strptime(date_msg.content, "%Y-%m-%d %H:%M")
            except ValueError:
                await ctx.send("❌ Invalid date format. Workshop creation cancelled.")
                return

            # Step 4: Duration
            await ctx.send("⏱️ How long will the workshop last? (in minutes)")
            duration_msg = await self.bot.wait_for('message', check=check, timeout=60)
            try:
                duration = int(duration_msg.content)
                if duration <= 0:
                    raise ValueError
            except ValueError:
                await ctx.send("❌ Invalid duration. Workshop creation cancelled.")
                return

            # Step 5: Max Participants
            await ctx.send("👥 What's the maximum number of participants? (Enter 0 for unlimited)")
            max_participants_msg = await self.bot.wait_for('message', check=check, timeout=60)
            try:
                max_participants = int(max_participants_msg.content)
                if max_participants < 0:
                    raise ValueError
            except ValueError:
                await ctx.send("❌ Invalid number. Workshop creation cancelled.")
                return

            # Create workshop
            workshop_id = f"ws-{int(datetime.utcnow().timestamp())}"
            workshop = {
                "id": workshop_id,
                "title": title,
                "description": description,
                "date": workshop_date,
                "duration": duration,
                "max_participants": max_participants,
                "created_by": ctx.author.id,
                "created_at": datetime.utcnow()
            }

            # Save workshop to database
            await self.db.insert_one(workshop)
            
            # Schedule reminders
            self.schedule_workshop_reminders(workshop)

            # Confirmation
            embed = nextcord.Embed(
                title="✅ Workshop Created",
                description=f"Your workshop has been scheduled!",
                color=nextcord.Color.orange()
            )
            embed.add_field(name="Title", value=title, inline=False)
            embed.add_field(name="Date & Time", value=workshop_date.strftime("%Y-%m-%d %H:%M"), inline=True)
            embed.add_field(name="Duration", value=f"{duration} minutes", inline=True)
            embed.add_field(name="Workshop ID", value=f"`{workshop_id}`", inline=False)
            embed.add_field(name="Sign Up Command", value=f"`!workshop signup {workshop_id}`", inline=False)
            
            await ctx.send(embed=embed)
            
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Workshop creation timed out. Please try again.")

    @workshop.command(name="list")
    async def workshop_list(self, ctx):
        """List all upcoming workshops"""
        now = datetime.utcnow()
        # Query database for upcoming workshops
        cursor = self.db.find({"date": {"$gt": now}}).sort("date", 1)
        upcoming_workshops = await cursor.to_list(length=None)
        
        if not upcoming_workshops:
            await ctx.send("📅 No upcoming workshops scheduled.")
            return
            
        embed = nextcord.Embed(
            title="📅 Upcoming Workshops",
            description=f"Found {len(upcoming_workshops)} upcoming workshops",
            color=nextcord.Color.orange()
        )
        
        for workshop in upcoming_workshops:
            # Calculate time until workshop
            time_until = workshop["date"] - now
            days = time_until.days
            hours, remainder = divmod(time_until.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            time_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"
            
            # Get participant count from database
            participant_count = await self.participants_db.count_documents({"workshop_id": workshop["id"]})
            max_str = f"/{workshop['max_participants']}" if workshop["max_participants"] > 0 else ""
            
            embed.add_field(
                name=f"📚 {workshop['title']}",
                value=f"**ID:** `{workshop['id']}`\n"
                      f"**When:** {workshop['date'].strftime('%Y-%m-%d %H:%M')} (in {time_str})\n"
                      f"**Duration:** {workshop['duration']} minutes\n"
                      f"**Participants:** {participant_count}{max_str}\n"
                      f"**Sign up:** `!workshop signup {workshop['id']}`",
                inline=False
            )
            
        await ctx.send(embed=embed)

    @workshop.command(name="signup")
    async def workshop_signup(self, ctx, workshop_id: str):
        """Sign up for a workshop"""
        # Find workshop in database
        workshop = await self.db.find_one({"id": workshop_id})
        
        if not workshop:
            await ctx.send("❌ Workshop not found. Use `!workshop list` to see available workshops.")
            return
            
        # Check if workshop is in the future
        if workshop["date"] < datetime.utcnow():
            await ctx.send("❌ This workshop has already started or ended.")
            return
            
        # Check if user is already signed up
        existing = await self.participants_db.find_one({
            "workshop_id": workshop_id,
            "user_id": ctx.author.id
        })
        if existing:
            await ctx.send("⚠️ You're already signed up for this workshop!")
            return
            
        # Check if workshop is full
        if workshop["max_participants"] > 0:
            participant_count = await self.participants_db.count_documents({"workshop_id": workshop_id})
            if participant_count >= workshop["max_participants"]:
                await ctx.send("❌ This workshop is already full.")
                return
            
        # Add user to participants in database
        await self.participants_db.insert_one({
            "workshop_id": workshop_id,
            "user_id": ctx.author.id,
            "registered_at": datetime.utcnow()
        })
        
        # Confirmation
        embed = nextcord.Embed(
            title="✅ Workshop Registration Confirmed",
            description=f"You've successfully signed up for **{workshop['title']}**!",
            color=nextcord.Color.orange()
        )
        
        embed.add_field(
            name="📅 Workshop Details",
            value=f"**Date:** {workshop['date'].strftime('%Y-%m-%d %H:%M')}\n"
                  f"**Duration:** {workshop['duration']} minutes\n"
                  f"**ID:** `{workshop_id}`",
            inline=False
        )
        
        embed.add_field(
            name="📝 Next Steps",
            value="• Add this to your calendar\n"
                  "• Prepare any necessary materials\n"
                  f"• Use `!workshop remind {workshop_id}` to set a reminder",
            inline=False
        )
        
        await ctx.send(embed=embed)

    def schedule_workshop_reminders(self, workshop):
        """Schedule reminders for a workshop"""
        workshop_date = workshop["date"]
        workshop_id = workshop["id"]
        
        # Schedule 1-day reminder
        if datetime.utcnow() < workshop_date - timedelta(days=1):
            one_day_reminder = workshop_date - timedelta(days=1)
            self.scheduler.add_job(
                self.send_reminder,
                trigger=DateTrigger(one_day_reminder),
                args=[workshop_id, "1 day"],
                id=f"{workshop_id}_1day"
            )
        
        # Schedule 1-hour reminder
        if datetime.utcnow() < workshop_date - timedelta(hours=1):
            one_hour_reminder = workshop_date - timedelta(hours=1)
            self.scheduler.add_job(
                self.send_reminder,
                trigger=DateTrigger(one_hour_reminder),
                args=[workshop_id, "1 hour"],
                id=f"{workshop_id}_1hour"
            )

    async def send_reminder(self, workshop_id: str, time_left: str):
        """Send a reminder to workshop participants"""
        # Fetch workshop from database
        workshop = await self.db.find_one({"id": workshop_id})
        if not workshop:
            logger.error(f"Workshop {workshop_id} not found for reminder")
            return
            
        # Fetch participants from database
        participants = await self.participants_db.find({"workshop_id": workshop_id}).to_list(length=None)
        
        for participant in participants:
            try:
                user = await self.bot.fetch_user(participant["user_id"])
                if user:
                    embed = nextcord.Embed(
                        title="⏰ Workshop Reminder",
                        description=f"Your workshop **{workshop['title']}** starts in **{time_left}**!",
                        color=nextcord.Color.orange()
                    )
                    embed.add_field(
                        name="📅 Details",
                        value=f"**Date:** {workshop['date'].strftime('%Y-%m-%d %H:%M')}\n"
                              f"**Duration:** {workshop['duration']} minutes",
                        inline=False
                    )
                    await user.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send reminder to user {participant['user_id']}: {str(e)}")

def setup(bot):
    """Setup the WorkshopManager cog"""
    if bot is not None:
        bot.add_cog(WorkshopManager(bot))
        logging.getLogger('VEKA').info("Loaded cog: src.cogs.workshops.workshop_manager")
    else:
        logging.getLogger('VEKA').error("Bot is None in WorkshopManager cog setup")
