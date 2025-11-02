from functools import wraps
from typing import Callable, Any, Optional, List
import nextcord
from nextcord.ext import commands

def add_slash_command(
    name: str,
    description: str,
    guild_ids: Optional[List[int]] = None,
    default_permissions: Optional[nextcord.Permissions] = None
) -> Callable:
    """
    Decorator to add slash command functionality to existing commands
    
    Args:
        name (str): Name of the slash command
        description (str): Description shown in Discord
        guild_ids (List[int], optional): List of guild IDs to register command to. Defaults to None (global).
        default_permissions (nextcord.Permissions, optional): Default permissions required. Defaults to None.
    """
    def decorator(func: Callable) -> Callable:
        @nextcord.slash_command(
            name=name,
            description=description,
            guild_ids=guild_ids,
            default_member_permissions=default_permissions
        )
        @wraps(func)
        async def wrapper(self, interaction: nextcord.Interaction, *args, **kwargs):
            try:
                # Convert interaction to context for backward compatibility
                ctx = await self.bot.get_context(interaction)
                await func(self, ctx, *args, **kwargs)
            except Exception as e:
                # Handle errors gracefully
                error_embed = nextcord.Embed(
                    title="❌ Error",
                    description=f"An error occurred while executing this command:\n```{str(e)}```",
                    color=nextcord.Color.red()
                )
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=error_embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
        return wrapper
    return decorator

def slash_option(
    name: str,
    description: str,
    required: bool = True,
    opt_type: Any = str,
    choices: Optional[List[Any]] = None,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None
) -> Callable:
    """
    Decorator to add options to slash commands
    
    Args:
        name (str): Option name
        description (str): Option description
        required (bool, optional): Whether the option is required. Defaults to True.
        opt_type (Any, optional): Option type. Defaults to str.
        choices (List[Any], optional): List of choices. Defaults to None.
        min_value (int, optional): Minimum value for int/float. Defaults to None.
        max_value (int, optional): Maximum value for int/float. Defaults to None.
    """
    return nextcord.slash_option(
        name=name,
        description=description,
        required=required,
        opt_type=opt_type,
        choices=choices,
        min_value=min_value,
        max_value=max_value
    )