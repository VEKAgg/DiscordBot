import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('VEKA.moderation')

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: nextcord.Member, *, reason=None):
        """Kick a member from the server"""
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ You can't kick someone with a higher or equal role!")
            return

        try:
            await member.kick(reason=reason)
            embed = nextcord.Embed(
                title="Member Kicked",
                description=f"👢 {member.mention} has been kicked by {ctx.author.mention}",
                color=nextcord.Color.orange()
            )
            if reason:
                embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} kicked {member} for reason: {reason}")
        except Exception as e:
            logger.error(f"Error kicking member: {str(e)}")
            await ctx.send("❌ Failed to kick member. Please check my permissions.")

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: nextcord.Member, *, reason=None):
        """Ban a member from the server"""
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ You can't ban someone with a higher or equal role!")
            return

        try:
            await member.ban(reason=reason, delete_message_days=1)
            embed = nextcord.Embed(
                title="Member Banned",
                description=f"🔨 {member.mention} has been banned by {ctx.author.mention}",
                color=nextcord.Color.red()
            )
            if reason:
                embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} banned {member} for reason: {reason}")
        except Exception as e:
            logger.error(f"Error banning member: {str(e)}")
            await ctx.send("❌ Failed to ban member. Please check my permissions.")

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, *, member_id: int):
        """Unban a member using their ID"""
        try:
            banned_users = [entry async for entry in ctx.guild.bans()]
            member_to_unban = None
            
            for ban_entry in banned_users:
                if ban_entry.user.id == member_id:
                    member_to_unban = ban_entry.user
                    break

            if member_to_unban is None:
                await ctx.send("❌ This user is not banned!")
                return

            await ctx.guild.unban(member_to_unban)
            embed = nextcord.Embed(
                title="Member Unbanned",
                description=f"✨ {member_to_unban.mention} has been unbanned by {ctx.author.mention}",
                color=nextcord.Color.green()
            )
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} unbanned {member_to_unban}")
        except Exception as e:
            logger.error(f"Error unbanning member: {str(e)}")
            await ctx.send("❌ Failed to unban member. Please check my permissions.")

    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: nextcord.Member, duration: str = "1h", *, reason=None):
        """Timeout (mute) a member for a specified duration"""
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ You can't mute someone with a higher or equal role!")
            return

        # Parse duration
        try:
            unit = duration[-1].lower()
            amount = int(duration[:-1])
            
            if unit == "s":
                delta = timedelta(seconds=amount)
            elif unit == "m":
                delta = timedelta(minutes=amount)
            elif unit == "h":
                delta = timedelta(hours=amount)
            elif unit == "d":
                delta = timedelta(days=amount)
            else:
                await ctx.send("❌ Invalid duration format! Use s/m/h/d (e.g., 30s, 5m, 1h, 1d)")
                return
                
            if delta > timedelta(days=28):  # Discord's maximum timeout duration
                delta = timedelta(days=28)
                
        except ValueError:
            await ctx.send("❌ Invalid duration format! Use s/m/h/d (e.g., 30s, 5m, 1h, 1d)")
            return

        try:
            await member.timeout(delta, reason=reason)
            embed = nextcord.Embed(
                title="Member Muted",
                description=f"🔇 {member.mention} has been muted by {ctx.author.mention}",
                color=nextcord.Color.orange()
            )
            embed.add_field(name="Duration", value=duration)
            if reason:
                embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} muted {member} for {duration} with reason: {reason}")
        except Exception as e:
            logger.error(f"Error muting member: {str(e)}")
            await ctx.send("❌ Failed to mute member. Please check my permissions.")

    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: nextcord.Member):
        """Remove timeout (unmute) from a member"""
        try:
            await member.timeout(None)
            embed = nextcord.Embed(
                title="Member Unmuted",
                description=f"🔊 {member.mention} has been unmuted by {ctx.author.mention}",
                color=nextcord.Color.green()
            )
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} unmuted {member}")
        except Exception as e:
            logger.error(f"Error unmuting member: {str(e)}")
            await ctx.send("❌ Failed to unmute member. Please check my permissions.")

    @commands.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int):
        """Clear a specified number of messages from the channel"""
        if amount < 1 or amount > 100:
            await ctx.send("❌ Please specify a number between 1 and 100!")
            return

        try:
            deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to include command message
            embed = nextcord.Embed(
                title="Messages Cleared",
                description=f"🧹 Deleted {len(deleted) - 1} messages",
                color=nextcord.Color.blue()
            )
            message = await ctx.send(embed=embed)
            await message.delete(delay=5)  # Delete the confirmation after 5 seconds
            logger.info(f"{ctx.author} cleared {len(deleted) - 1} messages in {ctx.channel}")
        except Exception as e:
            logger.error(f"Error clearing messages: {str(e)}")
            await ctx.send("❌ Failed to clear messages. Please check my permissions.")

async def setup(bot):
    """Setup the Moderation cog"""
    if bot is not None:
        await bot.add_cog(Moderation(bot))
        logging.getLogger('VEKA').info("Moderation cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Moderation cog setup")
