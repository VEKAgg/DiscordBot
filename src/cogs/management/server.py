import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
import traceback
from typing import Optional, Literal
from datetime import datetime, timezone

logger = setup_logger()

class ServerManagement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @app_commands.command(name="backup", description="Manage server backups")
    @app_commands.describe(action="Backup action to perform")
    @app_commands.choices(action=[
        app_commands.Choice(name="Create", value="create"),
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Restore", value="restore")
    ])
    @app_commands.default_permissions(administrator=True)
    async def backup(self, interaction: discord.Interaction, action: str):
        await interaction.response.defer()
        logger.info(f"Backup command executed by {interaction.user} in {interaction.guild.name} - Action: {action}")
        
        try:
            if action == "create":
                await self.create_backup(interaction)
                logger.info(f"Backup created for guild {interaction.guild_id}")
            elif action == "list":
                await self.list_backups(interaction)
                logger.info(f"Backup list retrieved for guild {interaction.guild_id}")
            elif action == "restore":
                await self.restore_backup(interaction)
                logger.info(f"Backup restored for guild {interaction.guild_id}")
                
        except discord.Forbidden as e:
            error_msg = f"Permission error in backup command: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await interaction.followup.send("❌ Bot lacks required permissions to manage backups.")
        except Exception as e:
            error_msg = f"Error in backup command: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await interaction.followup.send(f"❌ Failed to manage backups: `{str(e)}`")

    @app_commands.command(name="rolemgmt", description="Advanced role management")
    @app_commands.describe(
        action="Action to perform",
        role="Role to manage",
        target_role="Target role for hierarchy actions",
        reason="Reason for the action"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create Role", value="create"),
        app_commands.Choice(name="Delete Role", value="delete"),
        app_commands.Choice(name="Add to All", value="mass_add"),
        app_commands.Choice(name="Remove from All", value="mass_remove"),
        app_commands.Choice(name="Move Above", value="move_above"),
        app_commands.Choice(name="Move Below", value="move_below")
    ])
    @app_commands.default_permissions(manage_roles=True)
    async def rolemgmt(
        self, 
        interaction: discord.Interaction, 
        action: str,
        role: Optional[discord.Role] = None,
        target_role: Optional[discord.Role] = None,
        reason: Optional[str] = None
    ):
        await interaction.response.defer()
        
        try:
            if action == "create":
                new_role = await interaction.guild.create_role(
                    name=role.name if role else "New Role",
                    reason=reason or f"Created by {interaction.user}"
                )
                await interaction.followup.send(f"✅ Created role {new_role.mention}")
                
            elif action in ["mass_add", "mass_remove"]:
                if not role:
                    await interaction.followup.send("❌ Please specify a role!")
                    return
                    
                await interaction.followup.send("⏳ Processing mass role update...")
                
                success = 0
                failed = 0
                for member in interaction.guild.members:
                    try:
                        if action == "mass_add":
                            if role not in member.roles:
                                await member.add_roles(role, reason=reason)
                                success += 1
                        else:
                            if role in member.roles:
                                await member.remove_roles(role, reason=reason)
                                success += 1
                    except:
                        failed += 1
                        
                await interaction.followup.send(
                    f"✅ Role {'added to' if action == 'mass_add' else 'removed from'} "
                    f"{success} members ({failed} failed)"
                )
                
            elif action in ["move_above", "move_below"]:
                if not role or not target_role:
                    await interaction.followup.send("❌ Please specify both roles!")
                    return
                    
                positions = {r: r.position for r in interaction.guild.roles}
                
                if action == "move_above":
                    positions[role] = positions[target_role] + 1
                else:
                    positions[role] = positions[target_role] - 1
                    
                await interaction.guild.edit_role_positions(positions)
                await interaction.followup.send(
                    f"✅ Moved {role.mention} {'above' if action == 'move_above' else 'below'} {target_role.mention}"
                )
                
            # Log the action
            await self.db.role_logs.insert_one({
                "guild_id": interaction.guild_id,
                "user_id": interaction.user.id,
                "action": action,
                "role_id": role.id if role else None,
                "target_role_id": target_role.id if target_role else None,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc)
            })
            
        except discord.Forbidden as e:
            logger.error(f"Permission error in rolemgmt: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ Missing required permissions!")
        except Exception as e:
            logger.error(f"Error in rolemgmt: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send(f"❌ An error occurred: {str(e)}")

    @app_commands.command(name="audit", description="View audit logs")
    @app_commands.describe(
        action="Type of actions to view",
        user="Filter by user",
        limit="Number of entries to show (default: 10)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="All Actions", value="all"),
        app_commands.Choice(name="Member Updates", value="member"),
        app_commands.Choice(name="Role Changes", value="role"),
        app_commands.Choice(name="Channel Updates", value="channel"),
        app_commands.Choice(name="Message Deletions", value="message"),
        app_commands.Choice(name="Bans/Kicks", value="moderation")
    ])
    @app_commands.default_permissions(view_audit_log=True)
    async def audit(
        self, 
        interaction: discord.Interaction, 
        action: str = "all",
        user: Optional[discord.Member] = None,
        limit: Optional[int] = 10
    ):
        await interaction.response.defer()
        
        try:
            entries = []
            async for entry in interaction.guild.audit_logs(limit=limit):
                if action != "all":
                    if action == "member" and entry.action not in [
                        discord.AuditLogAction.member_update,
                        discord.AuditLogAction.member_role_update
                    ]:
                        continue
                    elif action == "role" and entry.action not in [
                        discord.AuditLogAction.role_create,
                        discord.AuditLogAction.role_update,
                        discord.AuditLogAction.role_delete
                    ]:
                        continue
                    # Add more action filters...
                
                if user and entry.user.id != user.id:
                    continue
                    
                entries.append(entry)
            
            if not entries:
                await interaction.followup.send("No matching audit log entries found.")
                return
                
            embed = discord.Embed(
                title="📋 Audit Log",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            for entry in entries[:10]:  # Show first 10 entries
                embed.add_field(
                    name=f"{entry.action.name} by {entry.user}",
                    value=f"Target: {entry.target}\n"
                          f"Reason: {entry.reason or 'No reason provided'}\n"
                          f"Time: {discord.utils.format_dt(entry.created_at, 'R')}",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except discord.Forbidden as e:
            logger.error(f"Permission error in audit: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ Missing required permissions!")
        except Exception as e:
            logger.error(f"Error in audit: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send(f"❌ An error occurred: {str(e)}")

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerManagement(bot)) 