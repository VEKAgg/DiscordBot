import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from typing import Optional

logger = setup_logger()

class EmbedManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @app_commands.command(name="embed", description="Create or edit an embed message")
    @app_commands.describe(
        title="Embed title",
        description="Embed description",
        color="Hex color code (e.g., #FF0000)",
        image="Image URL",
        thumbnail="Thumbnail URL",
        footer="Footer text"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def create_embed(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        color: Optional[str] = None,
        image: Optional[str] = None,
        thumbnail: Optional[str] = None,
        footer: Optional[str] = None
    ):
        await interaction.response.defer()
        
        try:
            # Convert hex color to discord.Color
            embed_color = discord.Color.default()
            if color:
                color = color.strip('#')
                embed_color = discord.Color.from_str(f'#{color}')

            # Create embed
            embed = discord.Embed(
                title=title,
                description=description,
                color=embed_color
            )

            if image:
                embed.set_image(url=image)
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            if footer:
                embed.set_footer(text=footer)

            # Store embed in database
            await self.db.embeds.insert_one({
                "guild_id": interaction.guild_id,
                "channel_id": interaction.channel_id,
                "author_id": interaction.user.id,
                "title": title,
                "description": description,
                "color": color,
                "image": image,
                "thumbnail": thumbnail,
                "footer": footer
            })

            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error creating embed: {str(e)}")
            await interaction.followup.send("An error occurred while creating the embed.")

    @app_commands.command(name="embedlist", description="List saved embeds")
    @app_commands.default_permissions(manage_messages=True)
    async def list_embeds(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            embeds = await self.db.embeds.find({
                "guild_id": interaction.guild_id
            }).to_list(length=10)

            if not embeds:
                await interaction.followup.send("No saved embeds found.")
                return

            embed_list = discord.Embed(
                title="Saved Embeds",
                color=discord.Color.blue()
            )

            for embed_data in embeds:
                embed_list.add_field(
                    name=embed_data["title"],
                    value=f"Created by: <@{embed_data['author_id']}>",
                    inline=False
                )

            await interaction.followup.send(embed=embed_list)
            
        except Exception as e:
            logger.error(f"Error listing embeds: {str(e)}")
            await interaction.followup.send("An error occurred while listing embeds.")

async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedManager(bot)) 