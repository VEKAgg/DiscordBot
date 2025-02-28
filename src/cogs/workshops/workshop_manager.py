import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from typing import Dict, List, Optional
import json

logger = logging.getLogger('VEKA.workshops')

class WorkshopManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        self.active_workshops = {}

    def cog_unload(self):
        self.scheduler.shutdown()

    @commands.group(name="workshop", invoke_without_command=True)
    async def workshop(self, ctx):
        """Workshop management commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="Workshop Commands",
                description="Manage and participate in virtual workshops!",
                color=nextcord.Color.blue()
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

            # Get workshop details
            await ctx.send("What's the title of the workshop?")
            title_msg = await self.bot.wait_for('message', check=check, timeout=60)
            title = title_msg.content

            await ctx.send("Provide a description of the workshop:")
            desc_msg = await self.bot.wait_for('message', check=check, timeout=120)
            description = desc_msg.content

            await ctx.send("When will the workshop be held? (Format: YYYY-MM-DD HH:MM)")
            date_msg = await self.bot.wait_for('message', check=check, timeout=60)
            try:
                workshop_date = datetime.strptime(date_msg.content, "%Y-%m-%d %H:%M")
            except ValueError:
                await ctx.send("❌ Invalid date format. Workshop creation cancelled.")
                return

            await ctx.send("What's the maximum number of participants? (Enter a number)")
            max_msg = await self.bot.wait_for('message', check=check, timeout=60)
            try:
                max_participants = int(max_msg.content)
            except ValueError:
                await ctx.send("❌ Invalid number. Workshop creation cancelled.")
                return

            # Create workshop
            workshop_id = str(len(self.active_workshops) + 1)
            workshop = {
                'id': workshop_id,
                'title': title,
                'description': description,
                'date': workshop_date,
                'max_participants': max_participants,
                'participants': [],
                'creator': ctx.author.id,
                'created_at': datetime.utcnow()
            }
            self.active_workshops[workshop_id] = workshop

            # Schedule reminders
            self.schedule_workshop_reminders(workshop)

            # Create announcement
            embed = nextcord.Embed(
                title="🎓 New Workshop Announced!",
                description=f"**{title}**\n\n{description}",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Date", value=workshop_date.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
            embed.add_field(name="Spots Available", value=str(max_participants), inline=True)
            embed.add_field(name="Workshop ID", value=workshop_id, inline=True)
            embed.set_footer(text="Use !workshop signup <id> to register!")

            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("❌ Workshop creation timed out. Please try again.")

    @workshop.command(name="list")
    async def workshop_list(self, ctx):
        """List all upcoming workshops"""
        if not self.active_workshops:
            await ctx.send("No upcoming workshops scheduled.")
            return

        embed = nextcord.Embed(
            title="📅 Upcoming Workshops",
            color=nextcord.Color.blue()
        )

        for w_id, workshop in self.active_workshops.items():
            if workshop['date'] > datetime.utcnow():
                spots_left = workshop['max_participants'] - len(workshop['participants'])
                embed.add_field(
                    name=f"{workshop['title']} (ID: {w_id})",
                    value=f"""
                    📆 {workshop['date'].strftime('%Y-%m-%d %H:%M UTC')}
                    👥 {spots_left} spots remaining
                    """,
                    inline=False
                )

        await ctx.send(embed=embed)

    @workshop.command(name="signup")
    async def workshop_signup(self, ctx, workshop_id: str):
        """Sign up for a workshop"""
        if workshop_id not in self.active_workshops:
            await ctx.send("❌ Workshop not found.")
            return

        workshop = self.active_workshops[workshop_id]
        
        if ctx.author.id in workshop['participants']:
            await ctx.send("❌ You're already registered for this workshop!")
            return

        if len(workshop['participants']) >= workshop['max_participants']:
            await ctx.send("❌ Sorry, this workshop is full!")
            return

        if workshop['date'] < datetime.utcnow():
            await ctx.send("❌ This workshop has already started/ended.")
            return

        workshop['participants'].append(ctx.author.id)
        
        embed = nextcord.Embed(
            title="✅ Workshop Registration Successful!",
            description=f"You've been registered for: {workshop['title']}",
            color=nextcord.Color.green()
        )
        embed.add_field(name="Date", value=workshop['date'].strftime("%Y-%m-%d %H:%M UTC"))
        embed.add_field(name="Spots Left", value=str(workshop['max_participants'] - len(workshop['participants'])))
        
        await ctx.send(embed=embed)

    def schedule_workshop_reminders(self, workshop):
        """Schedule reminders for a workshop"""
        # 24 hour reminder
        reminder_24h = workshop['date'] - timedelta(days=1)
        if reminder_24h > datetime.utcnow():
            self.scheduler.add_job(
                self.send_reminder,
                trigger=DateTrigger(reminder_24h),
                args=[workshop, "24 hours"],
                id=f"workshop_{workshop['id']}_24h"
            )

        # 1 hour reminder
        reminder_1h = workshop['date'] - timedelta(hours=1)
        if reminder_1h > datetime.utcnow():
            self.scheduler.add_job(
                self.send_reminder,
                trigger=DateTrigger(reminder_1h),
                args=[workshop, "1 hour"],
                id=f"workshop_{workshop['id']}_1h"
            )

    async def send_reminder(self, workshop: Dict, time_left: str):
        """Send a reminder to workshop participants"""
        for participant_id in workshop['participants']:
            try:
                user = await self.bot.fetch_user(participant_id)
                if user:
                    embed = nextcord.Embed(
                        title="🔔 Workshop Reminder",
                        description=f"Your workshop starts in {time_left}!",
                        color=nextcord.Color.gold()
                    )
                    embed.add_field(name="Workshop", value=workshop['title'])
                    embed.add_field(name="Date", value=workshop['date'].strftime("%Y-%m-%d %H:%M UTC"))
                    
                    await user.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send reminder to user {participant_id}: {str(e)}")

async def setup(bot):
    """Setup the WorkshopManager cog"""
    await bot.add_cog(WorkshopManager(bot))
    return True 