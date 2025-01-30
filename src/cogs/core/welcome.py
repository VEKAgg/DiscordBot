import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger

logger = setup_logger()

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            # Fetch welcome settings from database
            guild_settings = await self.db.welcome_settings.find_one(
                {"guild_id": member.guild.id}
            )
            
            if not guild_settings:
                return

            channel = self.bot.get_channel(guild_settings["channel_id"])
            if not channel:
                return

            # Create welcome embed
            embed = discord.Embed(
                title="Welcome to the server!",
                description=guild_settings["message"].format(
                    user=member.mention,
                    server=member.guild.name
                ),
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            
            await channel.send(embed=embed)
            
            # Assign default role if configured
            if "default_role_id" in guild_settings:
                role = member.guild.get_role(guild_settings["default_role_id"])
                if role:
                    await member.add_roles(role)
                    
        except Exception as e:
            logger.error(f"Error in welcome system: {str(e)}")

    @app_commands.command(name="welcome", description="Configure welcome settings")
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_config(self, interaction: discord.Interaction):
        # Welcome configuration command implementation
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot)) 