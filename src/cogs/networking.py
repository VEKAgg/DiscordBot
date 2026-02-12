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

    @commands.command(
        name="profile",
        description="Set up or view your professional profile"
    )
    async def profile(self, ctx, member: nextcord.Member = None):
        """View your or someone else's professional profile"""
        target = member or ctx.author
        
        profile = await self.profiles.find_one({"user_id": str(target.id)})
        
        if not profile:
            if target == ctx.author:
                embed = nextcord.Embed(
                    title="Profile Not Found",
                    description="You haven't set up your profile yet! Use `!setupprofile` to create one.",
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
        
        await ctx.send(embed=embed)

    @commands.command(
        name="setupprofile",
        description="Set up your professional profile"
    )
    async def setupprofile(self, ctx):
        """Interactive profile setup command"""
        try:
            # Check if profile exists
            existing_profile = await self.profiles.find_one({"user_id": str(ctx.author.id)})
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            # Start profile setup
            embed = nextcord.Embed(
                title="Professional Profile Setup",
                description="Let's set up your professional profile! I'll ask you a few questions.\n"
                          "Type 'skip' to skip any question.\n"
                          "Type 'cancel' to cancel the setup.",
                color=nextcord.Color.blue()
            )
            await ctx.send(embed=embed)

            # Questions and their corresponding database fields
            questions = {
                "What is your professional title? (e.g., 'Software Engineer', 'Product Manager')": "title",
                "What are your key skills? (comma-separated)": "skills",
                "Briefly describe your experience:": "experience",
                "What opportunities are you looking for? (e.g., 'Remote Python Developer position')": "looking_for"
            }

            profile_data = {"user_id": str(ctx.author.id)}

            for question, field in questions.items():
                await ctx.send(question)
                
                try:
                    response = await self.bot.wait_for('message', check=check, timeout=300.0)
                    
                    if response.content.lower() == 'cancel':
                        await ctx.send("Profile setup cancelled.")
                        return
                    
                    if response.content.lower() != 'skip':
                        profile_data[field] = response.content
                        
                except TimeoutError:
                    await ctx.send("Profile setup timed out. Please try again.")
                    return

            profile_data["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

            # Update or insert profile
            await self.profiles.update_one(
                {"user_id": str(ctx.author.id)},
                {"$set": profile_data},
                upsert=True
            )

            embed = nextcord.Embed(
                title="Profile Setup Complete!",
                description="Your professional profile has been updated. Use `!profile` to view it!",
                color=nextcord.Color.green()
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in setupprofile: {str(e)}")
            await ctx.send("An error occurred while setting up your profile. Please try again later.")

    @commands.command(
        name="connect",
        description="Send a connection request to another member"
    )
    async def connect(self, ctx, member: nextcord.Member, *, message: str = None):
        """Send a connection request to another member"""
        if member == ctx.author:
            await ctx.send("You can't connect with yourself!")
            return

        try:
            # Check if connection already exists
            existing_connection = await self.connections.find_one({
                "$or": [
                    {"user1_id": str(ctx.author.id), "user2_id": str(member.id)},
                    {"user1_id": str(member.id), "user2_id": str(ctx.author.id)}
                ]
            })

            if existing_connection:
                await ctx.send("You're already connected with this member!")
                return

            # Create connection request
            connection_data = {
                "user1_id": str(ctx.author.id),
                "user2_id": str(member.id),
                "status": "pending",
                "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "message": message or "Would like to connect with you!"
            }

            await self.connection_requests.insert_one(connection_data)

            # Send notification to the target member
            embed = nextcord.Embed(
                title="New Connection Request!",
                description=f"{ctx.author.mention} would like to connect with you!",
                color=nextcord.Color.blue()
            )
            if message:
                embed.add_field(name="Message", value=message)
            embed.add_field(
                name="How to respond",
                value="Use `!accept @user` to accept or `!decline @user` to decline",
                inline=False
            )

            await member.send(embed=embed)
            await ctx.send(f"Connection request sent to {member.mention}!")

        except Exception as e:
            logger.error(f"Error in connect: {str(e)}")
            await ctx.send("An error occurred while sending the connection request. Please try again later.")

    @commands.command(
        name="accept",
        description="Accept a connection request from another member"
    )
    async def accept(self, ctx, member: nextcord.Member):
        """Accept a connection request from another member"""
        try:
            # Find pending request from this member
            request = await self.connection_requests.find_one({
                "user1_id": str(member.id),
                "user2_id": str(ctx.author.id),
                "status": "pending"
            })

            if not request:
                await ctx.send(f"No pending connection request from {member.mention}.")
                return

            # Update request status
            await self.connection_requests.update_one(
                {"_id": request["_id"]},
                {"$set": {"status": "accepted"}}
            )

            # Create connection
            connection_data = {
                "user1_id": str(ctx.author.id),
                "user2_id": str(member.id),
                "connected_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            await self.connections.insert_one(connection_data)

            # Notify both users
            embed = nextcord.Embed(
                title="Connection Accepted!",
                description=f"You are now connected with {member.mention}!",
                color=nextcord.Color.green()
            )
            await ctx.send(embed=embed)

            # Notify the requester
            try:
                user_embed = nextcord.Embed(
                    title="Connection Request Accepted!",
                    description=f"{ctx.author.mention} has accepted your connection request!",
                    color=nextcord.Color.green()
                )
                await member.send(embed=user_embed)
            except:
                pass

        except Exception as e:
            logger.error(f"Error in accept: {str(e)}")
            await ctx.send("An error occurred while accepting the connection request.")

    @commands.command(
        name="decline",
        description="Decline a connection request from another member"
    )
    async def decline(self, ctx, member: nextcord.Member):
        """Decline a connection request from another member"""
        try:
            # Find pending request from this member
            request = await self.connection_requests.find_one({
                "user1_id": str(member.id),
                "user2_id": str(ctx.author.id),
                "status": "pending"
            })

            if not request:
                await ctx.send(f"No pending connection request from {member.mention}.")
                return

            # Update request status
            await self.connection_requests.update_one(
                {"_id": request["_id"]},
                {"$set": {"status": "declined"}}
            )

            embed = nextcord.Embed(
                title="Connection Request Declined",
                description=f"You have declined the connection request from {member.mention}.",
                color=nextcord.Color.red()
            )
            await ctx.send(embed=embed)

            # Notify the requester
            try:
                user_embed = nextcord.Embed(
                    title="Connection Request Declined",
                    description=f"{ctx.author.mention} has declined your connection request.",
                    color=nextcord.Color.red()
                )
                await member.send(embed=user_embed)
            except:
                pass

        except Exception as e:
            logger.error(f"Error in decline: {str(e)}")
            await ctx.send("An error occurred while declining the connection request.")

    @commands.command(
        name="connections",
        description="View your connections"
    )
    async def connections_cmd(self, ctx):
        """View your connections"""
        try:
            # Find all connections for this user
            user_id = str(ctx.author.id)
            cursor = self.connections.find({
                "$or": [
                    {"user1_id": user_id},
                    {"user2_id": user_id}
                ]
            })
            user_connections = await cursor.to_list(length=None)

            if not user_connections:
                await ctx.send("You don't have any connections yet. Use `!connect @user` to connect with someone!")
                return

            embed = nextcord.Embed(
                title="Your Connections",
                description=f"You have {len(user_connections)} connection(s)",
                color=nextcord.Color.blue()
            )

            for conn in user_connections:
                # Get the other user's ID
                other_id = conn["user2_id"] if conn["user1_id"] == user_id else conn["user1_id"]
                other_user = ctx.guild.get_member(int(other_id))
                
                if other_user:
                    embed.add_field(
                        name=other_user.display_name,
                        value=f"Connected since: {conn.get('connected_at', 'Unknown')}",
                        inline=False
                    )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in connections: {str(e)}")
            await ctx.send("An error occurred while fetching your connections.")

def setup(bot):
    """Setup the Networking cog"""
    if bot is not None:
        bot.add_cog(Networking(bot))
        logging.getLogger('VEKA').info("Networking cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Networking cog setup")
