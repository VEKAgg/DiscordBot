import nextcord
from nextcord.ext import commands
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger('VEKA.security')

class Security(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.honeypot_channel_id = 1429137232417263716
        self.db = bot.mongo
        self.security_logs = self.db.security_logs
        self.redis = bot.redis

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Monitor messages for honeypot channel violations"""
        if message.author.bot:
            return

        try:
            if message.channel.id == self.honeypot_channel_id:
                # Log the violation
                await self.security_logs.insert_one({
                    "user_id": str(message.author.id),
                    "username": str(message.author),
                    "guild_id": str(message.guild.id),
                    "content": message.content,
                    "timestamp": datetime.utcnow(),
                    "action": "honeypot_triggered"
                })

                # Delete user's recent messages
                for channel in message.guild.text_channels:
                    try:
                        await channel.purge(
                            limit=100,
                            check=lambda m: m.author.id == message.author.id
                        )
                    except nextcord.Forbidden:
                        continue

                # Create mute role if it doesn't exist
                mute_role = nextcord.utils.get(message.guild.roles, name="Muted")
                if not mute_role:
                    try:
                        mute_role = await message.guild.create_role(
                            name="Muted",
                            reason="Auto-created for honeypot violations"
                        )
                        # Set permissions for all channels
                        for channel in message.guild.channels:
                            await channel.set_permissions(mute_role, send_messages=False)
                    except nextcord.Forbidden:
                        logger.error("Failed to create mute role - missing permissions")
                        return

                # Apply mute
                try:
                    await message.author.add_roles(
                        mute_role,
                        reason="Honeypot channel violation"
                    )
                except nextcord.Forbidden:
                    logger.error(f"Failed to mute user {message.author.id} - missing permissions")

                # Add to Redis blacklist
                await self.redis.set(
                    f"blacklist:user:{message.author.id}",
                    {
                        "reason": "Honeypot violation",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )

                # Notify admins
                log_channel = nextcord.utils.get(message.guild.channels, name="mod-logs")
                if log_channel:
                    embed = nextcord.Embed(
                        title="🚨 Honeypot Violation",
                        description="A user has been muted for posting in the honeypot channel",
                        color=nextcord.Color.red()
                    )
                    embed.add_field(
                        name="User",
                        value=f"{message.author.mention} ({message.author.id})",
                        inline=False
                    )
                    embed.add_field(
                        name="Message Content",
                        value=message.content[:1024] or "No content",
                        inline=False
                    )
                    embed.timestamp = datetime.utcnow()
                    await log_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in honeypot handler: {str(e)}")
            
    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        """Check if joining member is blacklisted"""
        if await self.redis.get(f"blacklist:user:{member.id}"):
            try:
                # Re-apply mute role
                mute_role = nextcord.utils.get(member.guild.roles, name="Muted")
                if mute_role:
                    await member.add_roles(mute_role, reason="Auto-mute from blacklist")
            except nextcord.Forbidden:
                logger.error(f"Failed to re-mute blacklisted user {member.id}")

def setup(bot):
    """Setup the Security cog"""
    bot.add_cog(Security(bot))
    logger.info("Security cog loaded successfully")