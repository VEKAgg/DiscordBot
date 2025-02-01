from nextcord.ext import commands
import logging
from typing import Optional

class BaseExtension(commands.Cog):
    """Base class for all extensions"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self.logger = logging.getLogger(f'extensions.{self.__class__.__name__.lower()}')
        self.logger.info(f"{self.__class__.__name__} extension initialized")

    async def cog_load(self) -> None:
        """Called when the extension is loaded"""
        pass

    async def cog_unload(self) -> None:
        """Called when the extension is unloaded"""
        pass

    async def cog_check(self, ctx) -> bool:
        """Global check for all commands in this extension"""
        return True

    async def cog_command_error(self, ctx, error: Exception) -> None:
        """Global error handler for all commands in this extension"""
        self.logger.exception(f"Error in {ctx.command}", exc_info=error) 