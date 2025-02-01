import nextcord
from nextcord import Interaction, SlashOption
from nextcord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
import traceback
from typing import Optional, Literal
from datetime import datetime, timezone
import logging

# Get logger for this module
logger = logging.getLogger('nextcord.management.server')

class ServerManagement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        logger.info("ServerManagement cog initialized")

    role_management = nextcord.SlashCommandGroup(
        "role", 
        "Advanced role management commands",
        default_member_permissions=nextcord.Permissions(manage_roles=True)
    )

    async def cog_command_error(self, interaction: Interaction, error: Exception):
        """Global error handler for the cog"""
        if isinstance(error, commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You don't have permission to manage roles.", 
                ephemeral=True
            )
        elif isinstance(error, commands.BotMissingPermissions):
            await interaction.response.send_message(
                "❌ I don't have permission to manage roles.", 
                ephemeral=True
            )
        elif isinstance(error, nextcord.Forbidden):
            await interaction.response.send_message(
                "❌ I don't have permission to perform this action.", 
                ephemeral=True
            )
        else:
            logger.exception("Unhandled command error", exc_info=error)
            await interaction.response.send_message(
                "❌ An unexpected error occurred.", 
                ephemeral=True
            )

    @role_management.subcommand(name="mass", description="Mass role operations")
    async def mass_role(
        self,
        interaction: Interaction,
        action: Literal["add", "remove"],
        role: nextcord.Role,
        reason: Optional[str] = None
    ):
        await interaction.response.defer()
        
        try:
            await interaction.followup.send("⏳ Processing mass role update...")
            
            success = 0
            failed = 0
            for member in interaction.guild.members:
                try:
                    if action == "add" and role not in member.roles:
                        await member.add_roles(role, reason=reason)
                        success += 1
                    elif action == "remove" and role in member.roles:
                        await member.remove_roles(role, reason=reason)
                        success += 1
                except Exception:
                    failed += 1
            
            await interaction.followup.send(
                f"✅ Role {'added to' if action == 'add' else 'removed from'} "
                f"{success} members ({failed} failed)"
            )
            
            await self._log_role_action(interaction, "mass_" + action, role, reason=reason)
            
        except Exception as e:
            logger.exception("Error in mass role operation")
            await interaction.followup.send("❌ An error occurred during the operation.", ephemeral=True)

    @role_management.subcommand(name="position", description="Adjust role position")
    async def role_position(
        self,
        interaction: Interaction,
        role: nextcord.Role,
        target_role: nextcord.Role,
        position: Literal["above", "below"]
    ):
        await interaction.response.defer()
        
        try:
            positions = {r: r.position for r in interaction.guild.roles}
            
            if position == "above":
                positions[role] = positions[target_role] + 1
            else:
                positions[role] = positions[target_role] - 1
                
            await interaction.guild.edit_role_positions(positions)
            await interaction.followup.send(
                f"✅ Moved {role.mention} {position} {target_role.mention}"
            )
            
            await self._log_role_action(
                interaction, 
                f"move_{position}", 
                role, 
                target_role=target_role
            )
            
        except Exception as e:
            logger.exception("Error in role position adjustment")
            await interaction.followup.send("❌ Failed to adjust role position.", ephemeral=True)

    async def _log_role_action(
        self, 
        interaction: Interaction, 
        action: str, 
        role: nextcord.Role, 
        target_role: Optional[nextcord.Role] = None,
        reason: Optional[str] = None
    ):
        """Log role management actions to database with error handling"""
        try:
            await self.db.role_logs.insert_one({
                "guild_id": interaction.guild_id,
                "user_id": interaction.user.id,
                "action": action,
                "role_id": role.id,
                "target_role_id": target_role.id if target_role else None,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc)
            })
        except Exception as e:
            logger.exception("Failed to log role action", 
                           extra={"guild_id": interaction.guild_id, 
                                 "action": action,
                                 "role_id": role.id})

async def setup(bot: commands.Bot):
    if not isinstance(bot, commands.Bot):
        raise TypeError("This cog requires a commands.Bot instance")
        
    required_permissions = ["manage_roles", "manage_guild"]
    missing_permissions = [perm for perm in required_permissions 
                         if not getattr(bot.user.guild_permissions, perm, False)]
    
    if missing_permissions:
        logger.warning(f"Missing required permissions: {', '.join(missing_permissions)}")
        logger.warning("Some features may not work as expected")
    
    try:
        await bot.add_cog(ServerManagement(bot))
        logger.info("ServerManagement cog loaded successfully")
    except Exception as e:
        logger.exception("Failed to load ServerManagement cog")
        raise 