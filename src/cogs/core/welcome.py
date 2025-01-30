import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
import traceback
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import aiohttp
import os

logger = setup_logger()

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.session = aiohttp.ClientSession()
        self.font_path = "assets/fonts/Roboto-Bold.ttf"

    async def create_welcome_image(self, member: discord.Member):
        try:
            # Download avatar
            async with self.session.get(str(member.display_avatar.url)) as resp:
                avatar_bytes = await resp.read()
            
            # Create base image
            base = Image.new('RGBA', (1100, 300), color=(0, 0, 0, 0))
            avatar = Image.open(BytesIO(avatar_bytes)).convert('RGBA')
            
            # Resize and paste avatar
            avatar = avatar.resize((200, 200))
            base.paste(avatar, (50, 50), avatar)
            
            # Add text
            draw = ImageDraw.Draw(base)
            font = ImageFont.truetype(self.font_path, 60)
            small_font = ImageFont.truetype(self.font_path, 40)
            
            draw.text((280, 100), f"Welcome {member.name}!", fill='white', font=font)
            draw.text((280, 180), f"to {member.guild.name}", fill='#888888', font=small_font)
            
            # Save to buffer
            buffer = BytesIO()
            base.save(buffer, 'PNG')
            buffer.seek(0)
            return buffer
            
        except Exception as e:
            logger.error(f"Error creating welcome image: {str(e)}\n{traceback.format_exc()}")
            return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            # Fetch welcome settings
            settings = await self.db.welcome_settings.find_one({"guild_id": member.guild.id})
            if not settings:
                return

            # Send welcome message in channel
            if "channel_id" in settings:
                channel = self.bot.get_channel(settings["channel_id"])
                if channel:
                    embed = discord.Embed(
                        title="Welcome to the server!",
                        description=settings.get("message", "Welcome {user} to {server}!").format(
                            user=member.mention,
                            server=member.guild.name
                        ),
                        color=discord.Color.green()
                    )
                    
                    # Add custom welcome image
                    if settings.get("use_image", True):
                        image_buffer = await self.create_welcome_image(member)
                        if image_buffer:
                            file = discord.File(fp=image_buffer, filename="welcome.png")
                            embed.set_image(url="attachment://welcome.png")
                            await channel.send(file=file, embed=embed)
                        else:
                            embed.set_thumbnail(url=member.display_avatar.url)
                            await channel.send(embed=embed)
                    else:
                        embed.set_thumbnail(url=member.display_avatar.url)
                        await channel.send(embed=embed)

            # Send welcome DM
            if settings.get("send_dm", False):
                try:
                    dm_embed = discord.Embed(
                        title=f"Welcome to {member.guild.name}!",
                        description=settings.get("dm_message", "Thanks for joining! Here's some information to get you started."),
                        color=discord.Color.blue()
                    )
                    
                    # Add server information
                    dm_embed.add_field(
                        name="📜 Rules",
                        value="Please read our rules in <#rules_channel>",
                        inline=False
                    )
                    
                    dm_embed.add_field(
                        name="🎮 Get Started",
                        value="• Get roles in <#roles_channel>\n• Introduce yourself in <#intro_channel>\n• Check out our channels!",
                        inline=False
                    )
                    
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    logger.warning(f"Could not send welcome DM to {member.name} - DMs closed")

            # Assign default role
            if "default_role_id" in settings:
                role = member.guild.get_role(settings["default_role_id"])
                if role:
                    await member.add_roles(role)
                    
        except Exception as e:
            logger.error(f"Error in welcome event: {str(e)}\n{traceback.format_exc()}")

    def cog_unload(self):
        # Cleanup
        if self.session:
            self.bot.loop.create_task(self.session.close())

    @app_commands.command(name="welcome", description="Configure welcome settings")
    @app_commands.describe(
        channel="Channel to send welcome messages",
        message="Custom welcome message (use {user} for mention, {server} for server name)",
        role="Default role to assign to new members"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_config(self, interaction: discord.Interaction, 
                           channel: discord.TextChannel = None,
                           message: str = None,
                           role: discord.Role = None):
        await interaction.response.defer()
        
        try:
            # Get current settings
            settings = await self.db.welcome_settings.find_one({"guild_id": interaction.guild_id}) or {}
            
            if not channel and not message and not role:
                # Display current settings
                embed = discord.Embed(
                    title="🎉 Welcome Settings",
                    color=discord.Color.blue()
                )
                
                current_channel = self.bot.get_channel(settings.get("channel_id", 0))
                current_role = interaction.guild.get_role(settings.get("default_role_id", 0))
                
                embed.add_field(
                    name="Welcome Channel",
                    value=f"#{current_channel.name}" if current_channel else "Not set",
                    inline=True
                )
                embed.add_field(
                    name="Default Role",
                    value=current_role.name if current_role else "Not set",
                    inline=True
                )
                embed.add_field(
                    name="Welcome Message",
                    value=settings.get("message", "Default welcome message"),
                    inline=False
                )
                
                await interaction.followup.send(embed=embed)
                return
            
            # Update settings
            update_data = {}
            if channel:
                update_data["channel_id"] = channel.id
            if message:
                update_data["message"] = message
            if role:
                update_data["default_role_id"] = role.id
            
            await self.db.welcome_settings.update_one(
                {"guild_id": interaction.guild_id},
                {"$set": update_data},
                upsert=True
            )
            
            await interaction.followup.send("✅ Welcome settings updated successfully!")
            logger.info(f"Welcome settings updated for guild {interaction.guild_id}")
            
        except Exception as e:
            error_msg = f"Error in welcome config: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await interaction.followup.send(f"❌ An error occurred: `{str(e)}`")

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot)) 