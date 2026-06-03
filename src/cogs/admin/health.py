import logging
from datetime import datetime
from typing import Optional

import nextcord
from nextcord.ext import commands

from src.config.config import ENVIRONMENT, FEATURES
from src.core.runtime_state import runtime_state
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import admin_only, safe_command, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.admin.health')

class Health(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_degraded(self) -> bool:
        return not runtime_state.db_available or bool(runtime_state.failed_cogs)

    def _feature_state(self, prefix: str, enabled_flag: Optional[bool] = None) -> str:
        if any(ext.startswith(prefix) for ext in runtime_state.failed_cogs):
            return 'Degraded'
        if enabled_flag is False:
            return 'Disabled'
        if any(ext.startswith(prefix) for ext in runtime_state.loaded_cogs):
            return 'Enabled'
        return 'Disabled'

    def _resolve_extension(self, name: str) -> Optional[str]:
        candidates = set(runtime_state.loaded_cogs) | set(runtime_state.failed_cogs)
        if name in candidates:
            return name
        for ext in candidates:
            if ext.endswith(name) or ext.split('.')[-1] == name:
                return ext
        if name.startswith('src.cogs.'):
            return name
        return None

    async def send_health_status(self, target):
        status = 'Degraded' if self._is_degraded() else 'Healthy'
        db_status = 'Available' if runtime_state.db_available else 'Unavailable'
        uptime = datetime.utcnow() - runtime_state.startup_time

        embed = info_embed(
            title='VEKA Bot Health',
            description='Current runtime and infrastructure status for VEKA.',
            contributor_source=__name__,
            include_repo_link=True,
        )
        embed.add_field(name='Status', value=status, inline=False)
        embed.add_field(name='Uptime', value=str(uptime).split('.')[0], inline=False)
        embed.add_field(name='Database', value=db_status, inline=True)
        embed.add_field(name='Loaded Cogs', value=str(len(runtime_state.loaded_cogs)), inline=True)
        embed.add_field(name='Failed Cogs', value=str(len(runtime_state.failed_cogs)), inline=True)
        embed.add_field(name='Degraded Features', value=', '.join(runtime_state.degraded_features) or 'None', inline=False)
        embed.add_field(name='Bot Latency', value=f'{round(self.bot.latency * 1000)}ms', inline=True)
        embed.add_field(name='Version', value=runtime_state.version, inline=True)
        embed.add_field(name='Commit', value=runtime_state.commit, inline=True)
        embed.add_field(name='Branch', value=runtime_state.branch or 'unknown', inline=True)
        embed.add_field(name='Environment', value=ENVIRONMENT, inline=True)

        try:
            if isinstance(target, nextcord.Interaction):
                await safe_send(target, embed=embed, ephemeral=True)
            else:
                await target.send(embed=embed)
        except Exception as exc:
            logger.error('Health command failed: %s', exc, exc_info=True)
            if isinstance(target, nextcord.Interaction):
                await safe_send(target, content='Unable to send health status.', ephemeral=True)
            else:
                await target.send('Unable to send health status.')

    @commands.command(name='health')
    @safe_command()
    async def health_command(self, ctx):
        await self.send_health_status(ctx)

    @nextcord.slash_command(name='health', description='Show current bot health status')
    @safe_slash_command()
    async def health(self, interaction: nextcord.Interaction):
        await self.send_health_status(interaction)

    @nextcord.slash_command(name='botinfo', description='Show bot information and runtime data')
    @safe_slash_command()
    async def botinfo(self, interaction: nextcord.Interaction):
        uptime = datetime.utcnow() - runtime_state.startup_time
        embed = info_embed(
            title='VEKA Bot Info',
            description='Basic runtime and environment details for the VEKA bot.',
            contributor_source=__name__,
            include_repo_link=True,
        )
        embed.add_field(name='Uptime', value=str(uptime).split('.')[0], inline=False)
        embed.add_field(name='Branch', value=runtime_state.branch or 'unknown', inline=True)
        embed.add_field(name='Commit', value=runtime_state.commit, inline=True)
        embed.add_field(name='Loaded Cogs', value=str(len(runtime_state.loaded_cogs)), inline=True)
        embed.add_field(name='Latency', value=f'{round(self.bot.latency * 1000)}ms', inline=True)
        embed.add_field(name='Environment', value=ENVIRONMENT, inline=True)
        embed.add_field(name='Status', value='Degraded' if self._is_degraded() else 'Healthy', inline=False)

        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='featurestatus', description='Show enabled, disabled, and degraded feature status')
    @admin_only()
    @safe_slash_command()
    async def featurestatus(self, interaction: nextcord.Interaction):
        feature_status = {
            'Profiles/Networking': self._feature_state('src.cogs.networking'),
            'Marketplace': self._feature_state('src.cogs.marketplace'),
            'Resources/RSS': self._feature_state('src.cogs.resources.feeds', enabled_flag=FEATURES.get('rss_feeds', True)),
            'Database': 'Available' if runtime_state.db_available else 'Unavailable',
        }

        embed = info_embed(
            title='VEKA Feature Status',
            description='Enabled, disabled, and degraded bot features.',
            contributor_source=__name__,
            include_repo_link=True,
        )
        for name, value in feature_status.items():
            embed.add_field(name=name, value=value, inline=False)

        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='reloadcog', description='Reload a bot cog extension')
    @admin_only()
    @safe_slash_command()
    async def reloadcog(self, interaction: nextcord.Interaction, cog_name: str):
        extension = self._resolve_extension(cog_name)
        if not extension:
            embed = error_embed(
                title='Reload Failed',
                description=(
                    'Could not resolve the cog name. Use a full extension path '
                    'or a short cog name like `health`, `basic`, `networking`, `marketplace`, or `feeds`.'
                ),
                contributor_source=__name__,
                include_repo_link=True,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        try:
            if extension in self.bot.extensions:
                self.bot.reload_extension(extension)
            else:
                self.bot.load_extension(extension)

            if extension in runtime_state.failed_cogs:
                runtime_state.failed_cogs.remove(extension)
            if extension not in runtime_state.loaded_cogs:
                runtime_state.loaded_cogs.append(extension)
            if extension in runtime_state.degraded_features:
                runtime_state.degraded_features.remove(extension)

            embed = success_embed(
                title='Reload Successful',
                description=f'Extension `{extension}` reloaded successfully.',
                contributor_source=__name__,
                include_repo_link=True,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as exc:
            logger.error('Reload cog failed: %s', exc, exc_info=True)
            embed = error_embed(
                title='Reload Failed',
                description=f'Unable to reload `{extension}`: {exc}',
                contributor_source=__name__,
                include_repo_link=True,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Health(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.health')
