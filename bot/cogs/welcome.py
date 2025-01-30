import nextcord
from nextcord.ext import commands
from nextcord import Embed

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.welcome_channel_id = 123456789  # Replace with your channel ID

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Store join date in MongoDB
        await self.bot.db.users.update_one(
            {"_id": member.id},
            {"$set": {
                "username": str(member),
                "joined_at": member.joined_at,
                "guild_id": member.guild.id
            }},
            upsert=True
        )

        # Send welcome message
        channel = self.bot.get_channel(self.welcome_channel_id)
        embed = Embed(
            title=f"Welcome {member.name}!",
            description=f"Thanks for joining {member.guild.name}!",
            color=nextcord.Color.green()
        )
        embed.set_thumbnail(url=member.avatar.url)
        await channel.send(embed=embed)

        # Send DM
        try:
            await member.send(
                f"Welcome to {member.guild.name}! Be sure to read the rules."
            )
        except nextcord.Forbidden:
            pass

def setup(bot):
    bot.add_cog(WelcomeCog(bot))
