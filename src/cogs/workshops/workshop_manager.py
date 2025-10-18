import asyncio
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

    @nextcord.slash_command(name="workshop", description="Workshop management commands")
    async def workshop(self, interaction: nextcord.Interaction):
        """Workshop management commands"""
        embed = nextcord.Embed(
            title="Workshop Commands",
            description="Manage and participate in workshops!",
            color=nextcord.Color.blue()
        )
        embed.add_field(
            name="Available Commands",
            value="""
            `/workshop create` - Create a new workshop
            `/workshop list [category]` - List upcoming workshops
            `/workshop view <workshop_id>` - View workshop details
            `/workshop register <workshop_id>` - Register for a workshop
            `/workshop unregister <workshop_id>` - Unregister from a workshop
            `/workshop complete <workshop_id>` - Mark a workshop as complete (host only)
            `/workshop cancel <workshop_id>` - Cancel a workshop (host only)
            """,
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @workshop.subcommand(name="create", description="Create a new workshop")
    async def workshop_create(self, interaction: nextcord.Interaction):
        """Create a new workshop"""
        try:
            def check(m):
                return m.author == interaction.user and m.channel == interaction.channel

            await interaction.response.send_message("Let's create a new workshop! I'll ask you a few questions.", ephemeral=True)

            # Get workshop details
            await interaction.followup.send("What's the title of your workshop?", ephemeral=True)
            title_msg = await self.bot.wait_for('message', check=check, timeout=60)
            title = title_msg.content

            await interaction.followup.send("Provide a brief description of your workshop:", ephemeral=True)
            desc_msg = await self.bot.wait_for('message', check=check, timeout=300)
            description = desc_msg.content

            await interaction.followup.send("What category does your workshop belong to? (e.g., 'Programming', 'Design', 'Marketing')", ephemeral=True)
            category_msg = await self.bot.wait_for('message', check=check, timeout=60)
            category = category_msg.content

            await interaction.followup.send("When will the workshop take place? (e.g., '2023-12-25 14:00 UTC')", ephemeral=True)
            date_msg = await self.bot.wait_for('message', check=check, timeout=60)
            date_time_str = date_msg.content

            await interaction.followup.send("What is the duration of the workshop in minutes? (e.g., '60', '90')", ephemeral=True)
            duration_msg = await self.bot.wait_for('message', check=check, timeout=60)
            duration = int(duration_msg.content)

            await interaction.followup.send("What is the maximum number of attendees? (e.g., '20', '50')", ephemeral=True)
            max_attendees_msg = await self.bot.wait_for('message', check=check, timeout=60)
            max_attendees = int(max_attendees_msg.content)

            # Validate date and time
            try:
                scheduled_time = datetime.strptime(date_time_str, "%Y-%m-%d %H:%M %Z")
            except ValueError:
                await interaction.followup.send("❌ Invalid date/time format. Please use YYYY-MM-DD HH:MM UTC. Workshop creation cancelled.", ephemeral=True)
                return

            # Create workshop
            workshop_data = {
                'host_id': str(interaction.user.id),
                'title': title,
                'description': description,
                'category': category,
                'scheduled_time': scheduled_time,
                'duration_minutes': duration,
                'max_attendees': max_attendees,
                'attendees': [],
                'status': 'scheduled',
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }

            result = await self.db.insert_one(workshop_data)
            workshop_data['_id'] = result.inserted_id

            embed = nextcord.Embed(
                title="✅ Workshop Created Successfully!",
                description=f"**{title}** has been scheduled.",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Category", value=category, inline=True)
            embed.add_field(name="Scheduled For", value=scheduled_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
            embed.add_field(name="Duration", value=f"{duration} minutes", inline=True)
            embed.add_field(name="Max Attendees", value=str(max_attendees), inline=True)
            embed.set_footer(text=f"Workshop ID: {result.inserted_id}")

            await interaction.followup.send(embed=embed)

        except asyncio.TimeoutError:
            await interaction.followup.send("❌ Workshop creation timed out. Please try again.", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ Invalid input for duration or max attendees. Please enter numbers. Workshop creation cancelled.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in workshop_create: {str(e)}")
            await interaction.followup.send("An error occurred while creating the workshop. Please try again later.", ephemeral=True)

    @workshop.subcommand(name="list", description="List upcoming workshops")
    async def workshop_list(
        self,
        interaction: nextcord.Interaction,
        category: Optional[str] = nextcord.SlashOption(
            name="category",
            description="Filter workshops by category",
            required=False,
            choices=[{"name": cat.title(), "value": cat} for cat in WORKSHOP_CATEGORIES]
        )
    ):
        """List upcoming workshops"""
        if category and category not in WORKSHOP_CATEGORIES:
            categories = ", ".join(WORKSHOP_CATEGORIES)
            await interaction.response.send_message(f"❌ Invalid category. Available categories: {categories}", ephemeral=True)
            return

        workshops = await self.db.find({'status': 'scheduled'}).to_list(length=None)
        if category:
            workshops = [w for w in workshops if w['category'].lower() == category.lower()]

        if not workshops:
            await interaction.response.send_message("No upcoming workshops found." + (f" for category: {category}" if category else ""), ephemeral=True)
            return

        embed = nextcord.Embed(
            title=f"Upcoming Workshops{f' - {category}' if category else ''}",
            color=nextcord.Color.blue()
        )

        for workshop_data in workshops:
            host = await self.bot.fetch_user(int(workshop_data['host_id']))
            host_name = host.display_name if host else "Unknown User"
            
            embed.add_field(
                name=f"🗓️ {workshop_data['title']}",
                value=f"""
                Host: {host_name}
                Category: {workshop_data['category']}
                Time: {workshop_data['scheduled_time'].strftime("%Y-%m-%d %H:%M UTC")}
                Attendees: {len(workshop_data['attendees'])}/{workshop_data['max_attendees']}
                ID: {workshop_data['_id']}
                """,
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @workshop.subcommand(name="view", description="View workshop details")
    async def workshop_view(
        self,
        interaction: nextcord.Interaction,
        workshop_id: str = nextcord.SlashOption(
            name="workshop_id",
            description="The ID of the workshop to view",
            required=True
        )
    ):
        """View workshop details"""
        try:
            workshop_data = await self.db.find_one({'_id': workshop_id})
            if not workshop_data:
                await interaction.response.send_message("❌ Workshop not found.", ephemeral=True)
                return

            host = await self.bot.fetch_user(int(workshop_data['host_id']))
            host_name = host.display_name if host else "Unknown User"

            embed = nextcord.Embed(
                title=workshop_data['title'],
                description=workshop_data['description'],
                color=nextcord.Color.blue()
            )
            embed.set_author(name=f"Hosted by {host_name}")
            embed.add_field(name="Category", value=workshop_data['category'], inline=True)
            embed.add_field(name="Scheduled Time", value=workshop_data['scheduled_time'].strftime("%Y-%m-%d %H:%M UTC"), inline=True)
            embed.add_field(name="Duration", value=f"{workshop_data['duration_minutes']} minutes", inline=True)
            embed.add_field(name="Max Attendees", value=str(workshop_data['max_attendees']), inline=True)
            embed.add_field(name="Current Attendees", value=str(len(workshop_data['attendees']))), inline=True)
            embed.add_field(name="Status", value=workshop_data['status'].capitalize(), inline=True)
            embed.set_footer(text=f"Workshop ID: {workshop_data['_id']}")

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error viewing workshop: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while viewing the workshop.", ephemeral=True)
    @workshop.subcommand(name="signup", description="Sign up for a workshop")
    async def workshop_signup(
        self,
        interaction: nextcord.Interaction,
        workshop_id: str = nextcord.SlashOption(
            name="workshop_id",
            description="The ID of the workshop to sign up for",
            required=True
        )
    ):
        """Sign up for a workshop"""
        if workshop_id not in self.active_workshops:
            await interaction.response.send_message("❌ Workshop not found.", ephemeral=True)
            return

        workshop = self.active_workshops[workshop_id]
        
        if interaction.user.id in workshop['participants']:
            await interaction.response.send_message("❌ You're already registered for this workshop!", ephemeral=True)
            return

        if len(workshop['participants']) >= workshop['max_participants']:
            await interaction.response.send_message("❌ Sorry, this workshop is full!", ephemeral=True)
            return

        if workshop['date'] < datetime.utcnow():
            await interaction.response.send_message("❌ This workshop has already started/ended.", ephemeral=True)
            return

        workshop['participants'].append(interaction.user.id)
        
        embed = nextcord.Embed(
            title="✅ Workshop Registration Successful!",
            description=f"You've been registered for: {workshop['title']}",
            color=nextcord.Color.green()
        )
        embed.add_field(name="Date", value=workshop['date'].strftime("%Y-%m-%d %H:%M UTC"))
        embed.add_field(name="Spots Left", value=str(workshop['max_participants'] - len(workshop['participants'])))
        
        await interaction.response.send_message(embed=embed)

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

def setup(bot):
    """Setup the WorkshopManager cog"""
    if bot is not None:
        bot.add_cog(WorkshopManager(bot))
        logging.getLogger('VEKA').info("WorkshopManager cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in WorkshopManager cog setup")
