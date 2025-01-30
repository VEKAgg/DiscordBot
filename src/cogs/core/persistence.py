class Persistence(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.message_cache = {}
        self.voice_sessions = {}
        self.activity_history = {}

    async def store_member_data(self, member: discord.Member):
        """Store comprehensive member data"""
        try:
            current_activity = member.activity.name if member.activity else None
            voice_state = {
                "channel_id": member.voice.channel.id if member.voice else None,
                "self_mute": member.voice.self_mute if member.voice else False,
                "self_deaf": member.voice.self_deaf if member.voice else False
            }

            await self.db.member_persistence.update_one(
                {"guild_id": member.guild.id, "user_id": member.id},
                {
                    "$set": {
                        "roles": [role.id for role in member.roles if role.name != "@everyone"],
                        "nickname": member.nick,
                        "left_at": datetime.utcnow(),
                        "voice_state": voice_state,
                        "current_activity": current_activity,
                        "custom_status": str(member.activity) if member.activity else None
                    },
                    "$push": {
                        "nickname_history": {
                            "nickname": member.nick,
                            "changed_at": datetime.utcnow()
                        }
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error storing member data: {str(e)}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.store_member_data(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Track member updates"""
        try:
            updates = {}
            
            # Track nickname changes
            if before.nick != after.nick:
                updates["nickname_history"] = {
                    "old": before.nick,
                    "new": after.nick,
                    "changed_at": datetime.utcnow()
                }

            # Track role changes
            old_roles = set(before.roles)
            new_roles = set(after.roles)
            if old_roles != new_roles:
                added = [role.id for role in new_roles - old_roles]
                removed = [role.id for role in old_roles - new_roles]
                updates["role_history"] = {
                    "added": added,
                    "removed": removed,
                    "changed_at": datetime.utcnow()
                }

            if updates:
                await self.db.member_history.update_one(
                    {"guild_id": after.guild.id, "user_id": after.id},
                    {"$push": updates},
                    upsert=True
                )

        except Exception as e:
            logger.error(f"Error tracking member update: {str(e)}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Track voice state changes"""
        try:
            if before.channel != after.channel:
                if after.channel:
                    self.voice_sessions[member.id] = {
                        "channel_id": after.channel.id,
                        "joined_at": datetime.utcnow(),
                        "muted": after.self_mute,
                        "deafened": after.self_deaf
                    }
                elif member.id in self.voice_sessions:
                    session = self.voice_sessions.pop(member.id)
                    duration = datetime.utcnow() - session["joined_at"]
                    
                    await self.db.voice_history.update_one(
                        {"guild_id": member.guild.id, "user_id": member.id},
                        {
                            "$push": {
                                "sessions": {
                                    "channel_id": session["channel_id"],
                                    "duration": duration.total_seconds(),
                                    "muted": session["muted"],
                                    "deafened": session["deafened"],
                                    "date": session["joined_at"]
                                }
                            },
                            "$inc": {"total_time": duration.total_seconds()}
                        },
                        upsert=True
                    )

        except Exception as e:
            logger.error(f"Error tracking voice state: {str(e)}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Restore member data when they rejoin"""
        try:
            data = await self.db.member_persistence.find_one(
                {"guild_id": member.guild.id, "user_id": member.id}
            )
            
            if data:
                # Restore roles
                roles = [member.guild.get_role(role_id) for role_id in data.get("roles", [])]
                roles = [role for role in roles if role]  # Filter out None/deleted roles
                if roles:
                    await member.add_roles(*roles, reason="Restoring persistent roles")

                # Restore nickname
                if data.get("nickname"):
                    await member.edit(nick=data["nickname"])
        except Exception as e:
            logger.error(f"Error restoring member data: {str(e)}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Cache last messages"""
        if message.author.bot:
            return

        if message.author.id not in self.message_cache:
            self.message_cache[message.author.id] = []
        
        self.message_cache[message.author.id].append({
            "content": message.content,
            "timestamp": message.created_at,
            "channel": message.channel.id
        })
        
        # Keep only last 10 messages
        self.message_cache[message.author.id] = self.message_cache[message.author.id][-10:]

    @app_commands.command(name="lastmessages", description="View user's last messages")
    @app_commands.default_permissions(administrator=True)
    async def lastmessages(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        
        try:
            messages = self.message_cache.get(member.id, [])
            
            if not messages:
                await interaction.followup.send("No recent messages found for this user.")
                return

            embed = discord.Embed(
                title=f"Last Messages - {member.display_name}",
                color=member.color
            )

            for msg in reversed(messages):
                channel = interaction.guild.get_channel(msg["channel"])
                embed.add_field(
                    name=f"In #{channel.name} at {discord.utils.format_dt(msg['timestamp'])}",
                    value=msg["content"][:1024] or "[No content/embed/attachment]",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in lastmessages command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching messages.")

    @app_commands.command(name="history", description="View user history")
    @app_commands.default_permissions(administrator=True)
    async def history(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        
        try:
            history = await self.db.member_history.find_one(
                {"guild_id": interaction.guild.id, "user_id": member.id}
            )
            
            if not history:
                await interaction.followup.send("No history found for this user.")
                return

            embed = discord.Embed(
                title=f"History for {member.display_name}",
                color=member.color
            )

            # Nickname history
            if "nickname_history" in history:
                recent_nicks = history["nickname_history"][-5:]  # Last 5 nicknames
                nick_value = "\n".join(
                    f"• {nick['new']} ({discord.utils.format_dt(nick['changed_at'], 'R')})"
                    for nick in recent_nicks
                )
                embed.add_field(name="Recent Nicknames", value=nick_value or "No changes", inline=False)

            # Role history
            if "role_history" in history:
                recent_roles = history["role_history"][-5:]  # Last 5 role changes
                role_value = "\n".join(
                    f"• Added: {len(change['added'])} | Removed: {len(change['removed'])} ({discord.utils.format_dt(change['changed_at'], 'R')})"
                    for change in recent_roles
                )
                embed.add_field(name="Recent Role Changes", value=role_value or "No changes", inline=False)

            # Voice activity
            voice_stats = await self.db.voice_history.find_one(
                {"guild_id": interaction.guild.id, "user_id": member.id}
            )
            if voice_stats:
                total_hours = voice_stats.get("total_time", 0) / 3600
                embed.add_field(
                    name="Voice Activity",
                    value=f"Total Time: {total_hours:.1f} hours",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in history command: {str(e)}")
            await interaction.followup.send("❌ An error occurred while fetching history.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Persistence(bot)) 