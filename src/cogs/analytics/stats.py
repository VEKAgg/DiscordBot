import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger

logger = setup_logger()

class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @app_commands.command(name="analytics", description="View server analytics")
    @app_commands.describe(type="Type of analytics to view")
    @app_commands.choices(type=[
        app_commands.Choice(name="Overview", value="overview"),
        app_commands.Choice(name="Members", value="members"),
        app_commands.Choice(name="Activity", value="activity")
    ])
    async def analytics(self, interaction: discord.Interaction, type: str):
        await interaction.response.defer()
        
        try:
            if type == "overview":
                # Fetch server overview stats
                stats = await self.get_overview_stats(interaction.guild_id)
                await interaction.followup.send(embed=self.create_overview_embed(stats))
            elif type == "members":
                # Fetch member stats
                stats = await self.get_member_stats(interaction.guild_id)
                await interaction.followup.send(embed=self.create_member_embed(stats))
            elif type == "activity":
                # Fetch activity stats
                stats = await self.get_activity_stats(interaction.guild_id)
                await interaction.followup.send(embed=self.create_activity_embed(stats))
                
        except Exception as e:
            logger.error(f"Error in analytics command: {str(e)}")
            await interaction.followup.send("An error occurred while fetching analytics.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot)) 