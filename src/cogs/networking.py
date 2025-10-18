import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime
from src.database.mongodb import users, get_or_create_user

logger = logging.getLogger('VEKA.networking')

class Networking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.profiles = bot.mongo.profiles
        self.connections = bot.mongo.connections
        self.connection_requests = bot.mongo.connection_requests

    @nextcord.slash_command(
        name="profile",
        description="Set up or view your professional profile"
    )
    async def profile_slash(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member = nextcord.SlashOption(
            name="member",
            description="The member whose profile to view (defaults to yourself)",
            required=False
        )
    ):
        """View your or someone else's professional profile"""
        target = member or interaction.user
        
        profile = await self.profiles.find_one({"user_id": str(target.id)})
        
        if not profile:
            if target == interaction.user:
                embed = nextcord.Embed(
                    title="Profile Not Found",
                    description="You haven't set up your profile yet! Use `/setupprofile` to create one.",
                    color=nextcord.Color.orange()
                )
            else:
                embed = nextcord.Embed(
                    title="Profile Not Found",
                    description=f"{target.display_name} hasn't set up their profile yet.",
                    color=nextcord.Color.orange()
                )
        else:
            embed = nextcord.Embed(
                title=f"{target.display_name}'s Professional Profile",
                color=nextcord.Color.blue()
            )
            embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
            
            fields = {
                "Title": profile.get("title", "Not set"),
                "Skills": profile.get("skills", "Not set"),
                "Experience": profile.get("experience", "Not set"),
                "Looking For": profile.get("looking_for", "Not set")
            }
            
            for name, value in fields.items():
                embed.add_field(name=name, value=value, inline=False)
            
            embed.set_footer(text=f"Profile last updated: {profile.get('last_updated', 'Never')}")
        
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(
        name="setupprofile",
        description="Set up your professional profile"
    )
    async def setupprofile_slash(self, interaction: nextcord.Interaction):
        """Interactive profile setup command"""
        try:
            # Check if profile exists
            existing_profile = await self.profiles.find_one({"user_id": str(interaction.user.id)})
            
            def check(m):
                return m.author == interaction.user and m.channel == interaction.channel

            # Start profile setup
            embed = nextcord.Embed(
                title="Professional Profile Setup",
                description="Let's set up your professional profile! I'll ask you a few questions.\n"
                          "Type 'skip' to skip any question.\n"
                          "Type 'cancel' to cancel the setup.",
                color=nextcord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True) # Send initial response ephemerally

            # Questions and their corresponding database fields
            questions = {
                "What is your professional title? (e.g., 'Software Engineer', 'Product Manager')": "title",
                "What are your key skills? (comma-separated)": "skills",
                "Briefly describe your experience:": "experience",
                "What opportunities are you looking for? (e.g., 'Remote Python Developer position')": "looking_for"
            }

            profile_data = {"user_id": str(interaction.user.id)}

            for question, field in questions.items():
                await interaction.followup.send(question, ephemeral=True) # Use followup for subsequent questions
                
                try:
                    response = await self.bot.wait_for('message', check=check, timeout=300.0)
                    
                    if response.content.lower() == 'cancel':
                        await interaction.followup.send("Profile setup cancelled.", ephemeral=True)
                        return
                    
                    if response.content.lower() != 'skip':
                        profile_data[field] = response.content
                        
                except TimeoutError:
                    await interaction.followup.send("Profile setup timed out. Please try again.", ephemeral=True)
                    return

            profile_data["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

            # Update or insert profile
            await self.profiles.update_one(
                {"user_id": str(interaction.user.id)},
                {"$set": profile_data},
                upsert=True
            )

            embed = nextcord.Embed(
                title="Profile Setup Complete!",
                description="Your professional profile has been updated. Use `/profile` to view it!",
                color=nextcord.Color.green()
            )
            await interaction.followup.send(embed=embed) # Final confirmation can be public or ephemeral
            
        except Exception as e:
            logger.error(f"Error in setupprofile: {str(e)}")
            await interaction.followup.send("An error occurred while setting up your profile. Please try again later.", ephemeral=True)

    @nextcord.slash_command(
        name="connect",
        description="Send a connection request to another member"
    )
    async def connect_slash(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member = nextcord.SlashOption(
            name="member",
            description="The member you want to connect with",
            required=True
        ),
        message: str = nextcord.SlashOption(
            name="message",
            description="An optional message to send with the request",
            required=False
        )
    ):
        """Send a connection request to another member"""
        if member == interaction.user:
            await interaction.response.send_message("You can't connect with yourself!", ephemeral=True)
            return

        try:
            # Check if connection already exists
            existing_connection = await self.connections.find_one({
                "$or": [
                    {"user1_id": str(interaction.user.id), "user2_id": str(member.id)},
                    {"user1_id": str(member.id), "user2_id": str(interaction.user.id)}
                ]
            })

            if existing_connection:
                await interaction.response.send_message("You're already connected with this member!", ephemeral=True)
                return

            # Create connection request
            connection_data = {
                "user1_id": str(interaction.user.id),
                "user2_id": str(member.id),
                "status": "pending",
                "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "message": message or "Would like to connect with you!"
            }

            await self.db.connection_requests.insert_one(connection_data)

            # Send notification to the target member
            embed = nextcord.Embed(
                title="New Connection Request!",
                description=f"{interaction.user.mention} would like to connect with you!",
                color=nextcord.Color.blue()
            )
            if message:
                embed.add_field(name="Message", value=message)
            embed.add_field(
                name="How to respond",
                value="Use `/accept @user` to accept or `/decline @user` to decline",
                inline=False
            )

            await member.send(embed=embed)
            await interaction.response.send_message(f"Connection request sent to {member.mention}!")

        except Exception as e:
            logger.error(f"Error in connect: {str(e)}")
            await interaction.response.send_message("An error occurred while sending the connection request. Please try again later.", ephemeral=True)

def setup(bot):
    """Setup the Networking cog"""
    if bot is not None:
        bot.add_cog(Networking(bot))
        logging.getLogger('VEKA').info("Networking cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Networking cog setup")
