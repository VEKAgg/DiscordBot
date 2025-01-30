import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from datetime import datetime, timedelta
import psutil
import platform
import time

logger = setup_logger()

class Information(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.start_time = datetime.utcnow()
        self.afk_users = {}

    def get_uptime(self):
        delta = datetime.utcnow() - self.start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m {seconds}s"

    @app_commands.command(name="botinfo", description="View bot information and statistics")
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Gather bot statistics
            total_members = sum(guild.member_count for guild in self.bot.guilds)
            total_commands = len(self.bot.commands)
            
            # System information
            cpu_usage = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            memory_usage = f"{memory.percent}%"
            
            embed = discord.Embed(
                title=f"{self.bot.user.name} Information",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.add_field(name="Bot ID", value=self.bot.user.id, inline=True)
            embed.add_field(name="Created", value=discord.utils.format_dt(self.bot.user.created_at, 'R'), inline=True)
            embed.add_field(name="Uptime", value=self.get_uptime(), inline=True)
            embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
            embed.add_field(name="Members", value=f"{total_members:,}", inline=True)
            embed.add_field(name="Commands", value=total_commands, inline=True)
            embed.add_field(name="Python Version", value=platform.python_version(), inline=True)
            embed.add_field(name="Discord.py Version", value=discord.__version__, inline=True)
            embed.add_field(name="CPU Usage", value=f"{cpu_usage}%", inline=True)
            embed.add_field(name="Memory Usage", value=memory_usage, inline=True)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in botinfo command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching bot information.")

    @app_commands.command(name="serverinfo", description="View server information")
    async def serverinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            guild = interaction.guild
            
            # Get role and channel counts
            total_roles = len(guild.roles)
            text_channels = len(guild.text_channels)
            voice_channels = len(guild.voice_channels)
            
            # Get member counts
            total_members = guild.member_count
            online_members = len([m for m in guild.members if m.status != discord.Status.offline])
            bot_count = len([m for m in guild.members if m.bot])
            
            embed = discord.Embed(
                title=f"{guild.name} Information",
                color=guild.owner.color if guild.owner else discord.Color.blue()
            )
            
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            
            embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
            embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, 'R'), inline=True)
            embed.add_field(name="Region", value=str(guild.preferred_locale), inline=True)
            
            embed.add_field(name="Members", value=f"Total: {total_members}\nOnline: {online_members}\nBots: {bot_count}", inline=True)
            embed.add_field(name="Channels", value=f"Text: {text_channels}\nVoice: {voice_channels}", inline=True)
            embed.add_field(name="Roles", value=total_roles, inline=True)
            
            if guild.premium_subscription_count:
                embed.add_field(name="Boost Level", value=f"Level {guild.premium_tier}", inline=True)
                embed.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in serverinfo command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching server information.")

    @app_commands.command(name="avatar", description="View user's avatar")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        
        try:
            target = member or interaction.user
            
            embed = discord.Embed(
                title=f"{target.name}'s Avatar",
                color=target.color
            )
            
            embed.set_image(url=target.display_avatar.url)
            embed.add_field(name="Avatar URL", value=f"[Click here]({target.display_avatar.url})")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in avatar command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching the avatar.")

    @app_commands.command(name="banner", description="View user's banner")
    async def banner(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        
        try:
            target = member or interaction.user
            user = await self.bot.fetch_user(target.id)
            
            if not user.banner:
                await interaction.followup.send("This user doesn't have a banner!")
                return
                
            embed = discord.Embed(
                title=f"{target.name}'s Banner",
                color=target.color
            )
            
            embed.set_image(url=user.banner.url)
            embed.add_field(name="Banner URL", value=f"[Click here]({user.banner.url})")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in banner command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching the banner.")

    @app_commands.command(name="servericon", description="View server icon")
    async def servericon(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            if not interaction.guild.icon:
                await interaction.followup.send("This server doesn't have an icon!")
                return
                
            embed = discord.Embed(
                title=f"{interaction.guild.name}'s Icon",
                color=discord.Color.blue()
            )
            
            embed.set_image(url=interaction.guild.icon.url)
            embed.add_field(name="Icon URL", value=f"[Click here]({interaction.guild.icon.url})")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in servericon command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching the server icon.")

    @app_commands.command(name="serverbanner", description="View server banner")
    async def serverbanner(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            if not interaction.guild.banner:
                await interaction.followup.send("This server doesn't have a banner!")
                return
                
            embed = discord.Embed(
                title=f"{interaction.guild.name}'s Banner",
                color=discord.Color.blue()
            )
            
            embed.set_image(url=interaction.guild.banner.url)
            embed.add_field(name="Banner URL", value=f"[Click here]({interaction.guild.banner.url})")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in serverbanner command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching the server banner.")

    @app_commands.command(name="roles", description="View all server roles")
    async def roles(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            roles = interaction.guild.roles[1:]  # Exclude @everyone
            roles.reverse()  # Show highest roles first
            
            embed = discord.Embed(
                title=f"Roles in {interaction.guild.name}",
                color=discord.Color.blue(),
                description=f"Total Roles: {len(roles)}"
            )
            
            # Group roles by pages of 20
            chunks = [roles[i:i + 20] for i in range(0, len(roles), 20)]
            
            for i, chunk in enumerate(chunks, 1):
                value = "\n".join(f"{role.mention} - {len(role.members)} members" for role in chunk)
                embed.add_field(name=f"Page {i}", value=value or "No roles", inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in roles command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching roles.")

    @app_commands.command(name="userroles", description="View roles of a user")
    async def userroles(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        
        try:
            target = member or interaction.user
            roles = target.roles[1:]  # Exclude @everyone
            roles.reverse()
            
            embed = discord.Embed(
                title=f"Roles for {target.display_name}",
                color=target.color,
                description=f"Total Roles: {len(roles)}"
            )
            
            if roles:
                role_list = "\n".join(f"{role.mention} - <t:{int(role.id >> 22) + 1420070400}:R>" for role in roles)
                embed.add_field(name="Roles", value=role_list, inline=False)
            else:
                embed.description = "This user has no roles."
                
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in userroles command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching user roles.")

    @app_commands.command(name="afk", description="Set your AFK status")
    @app_commands.describe(reason="Reason for going AFK")
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK"):
        await interaction.response.defer()
        
        try:
            self.afk_users[interaction.user.id] = {
                "reason": reason,
                "timestamp": datetime.utcnow()
            }
            
            await self.db.afk_status.update_one(
                {
                    "guild_id": interaction.guild_id,
                    "user_id": interaction.user.id
                },
                {
                    "$set": {
                        "reason": reason,
                        "timestamp": datetime.utcnow()
                    }
                },
                upsert=True
            )
            
            await interaction.followup.send(f"✅ I've set your AFK status: {reason}")
            
            # Add [AFK] to nickname if possible
            try:
                await interaction.user.edit(nick=f"[AFK] {interaction.user.display_name[:26]}")
            except discord.Forbidden:
                pass
            
        except Exception as e:
            logger.error(f"Error in afk command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while setting AFK status.")

    @app_commands.command(name="poll", description="Create a poll")
    @app_commands.describe(
        question="The poll question",
        options="Poll options (separate with commas)",
        duration="Poll duration in minutes (default: 60)"
    )
    async def poll(self, interaction: discord.Interaction, question: str, options: str, duration: int = 60):
        await interaction.response.defer()
        
        try:
            options_list = [opt.strip() for opt in options.split(",")][:10]  # Limit to 10 options
            reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            
            embed = discord.Embed(
                title="📊 " + question,
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            description = "\n".join(f"{reactions[i]} {option}" for i, option in enumerate(options_list))
            embed.description = description
            
            end_time = datetime.utcnow() + timedelta(minutes=duration)
            embed.set_footer(text=f"Poll ends {discord.utils.format_dt(end_time, 'R')}")
            
            poll_msg = await interaction.followup.send(embed=embed)
            
            # Add reactions
            for i in range(len(options_list)):
                await poll_msg.add_reaction(reactions[i])
            
            # Store poll data
            await self.db.polls.insert_one({
                "guild_id": interaction.guild_id,
                "channel_id": interaction.channel_id,
                "message_id": poll_msg.id,
                "end_time": end_time,
                "options": options_list
            })
            
        except Exception as e:
            logger.error(f"Error in poll command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while creating the poll.")

    @app_commands.command(name="nick", description="Change your nickname")
    @app_commands.describe(nickname="Your new nickname (leave empty to reset)")
    async def nick(self, interaction: discord.Interaction, nickname: str = None):
        await interaction.response.defer()
        
        try:
            old_nick = interaction.user.display_name
            await interaction.user.edit(nick=nickname)
            
            if nickname:
                await interaction.followup.send(f"✅ Changed your nickname from `{old_nick}` to `{nickname}`")
            else:
                await interaction.followup.send(f"✅ Reset your nickname from `{old_nick}` to your username")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to change your nickname.")
        except Exception as e:
            logger.error(f"Error in nick command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while changing your nickname.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
            
        # Remove AFK status if user sends a message
        if message.author.id in self.afk_users:
            del self.afk_users[message.author.id]
            await self.db.afk_status.delete_one({
                "guild_id": message.guild.id,
                "user_id": message.author.id
            })
            
            try:
                if message.author.display_name.startswith("[AFK]"):
                    await message.author.edit(nick=message.author.display_name[6:])
            except discord.Forbidden:
                pass
            
            await message.channel.send(f"Welcome back {message.author.mention}! I've removed your AFK status.", delete_after=10)

async def setup(bot: commands.Bot):
    await bot.add_cog(Information(bot)) 