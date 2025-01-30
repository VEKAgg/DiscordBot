import nextcord
from nextcord.ext import commands

class InviteTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invites = {}

    async def get_invites(self):
        for guild in self.bot.guilds:
            try:
                self.invites[guild.id] = await guild.invites()
            except nextcord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        await self.get_invites()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        invites_before = self.invites.get(member.guild.id, [])
        invites_after = await member.guild.invites()
        
        for invite in invites_before:
            if invite.uses < next((i.uses for i in invites_after if i.code == invite.code), 0):
                # Update database
                await self.bot.db.invites.update_one(
                    {"_id": invite.inviter.id},
                    {"$inc": {"count": 1}},
                    upsert=True
                )
                break
        
        self.invites[member.guild.id] = invites_after

def setup(bot):
    bot.add_cog(InviteTracker(bot))
