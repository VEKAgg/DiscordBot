import logging
from datetime import UTC, datetime

import nextcord
from nextcord.ext import commands

from src.config.config import ENVIRONMENT
from src.core.runtime_state import runtime_state
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_command, safe_send, safe_slash_command, staff_only
from src.utils.security.rbac import require_founder, require_staff

logger = logging.getLogger('VEKA.admin.health')


def _get_system_stats() -> dict:
    """Get CPU, memory, and thread stats via psutil."""
    try:
        import psutil

        process = psutil.Process()
        mem = process.memory_info()
        cpu_count = psutil.cpu_count()
        return {
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'cpu_count': cpu_count or 0,
            'mem_used_mb': round(mem.rss / 1024 / 1024, 1),
            'mem_percent': round(process.memory_percent(), 1),
            'threads': process.num_threads(),
        }
    except ImportError:
        return {'cpu_percent': 0, 'cpu_count': 0, 'mem_used_mb': 0, 'mem_percent': 0, 'threads': 0}


class Health(commands.Cog):
    @nextcord.slash_command(name='admin', description='Staff and admin commands')
    @safe_slash_command()
    async def admin(self, interaction: nextcord.Interaction):
        pass

    def __init__(self, bot):
        self.bot = bot

    def _is_degraded(self) -> bool:
        return not runtime_state.db_available or bool(runtime_state.failed_cogs)

    def _feature_state(self, prefix: str, enabled_flag: bool | None = None) -> str:
        if any(ext.startswith(prefix) for ext in runtime_state.failed_cogs):
            return 'Degraded'
        if enabled_flag is False:
            return 'Disabled'
        if any(ext.startswith(prefix) for ext in runtime_state.loaded_cogs):
            return 'Enabled'
        return 'Disabled'

    def _resolve_extension(self, name: str) -> str | None:
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
        uptime = datetime.now(UTC) - runtime_state.startup_time

        user = target.author if hasattr(target, 'author') else target.user if hasattr(target, 'user') else None
        embed = await info_embed(
            title='VEKA Bot Health',
            description='Current runtime status and system history.',
            contributor_source=__name__,
            user=user,
            guild=getattr(target, 'guild', None),
        )

        # Current status
        embed.add_field(name='Status', value=status, inline=True)
        embed.add_field(name='Database', value=db_status, inline=True)
        embed.add_field(name='Latency', value=f'{round(self.bot.latency * 1000)}ms', inline=True)

        # Runtime
        embed.add_field(name='Uptime', value=str(uptime).split('.')[0], inline=False)
        embed.add_field(name='Version', value=runtime_state.version, inline=True)
        embed.add_field(name='Environment', value=ENVIRONMENT, inline=True)

        # Cog health
        embed.add_field(name='Loaded Cogs', value=str(len(runtime_state.loaded_cogs)), inline=True)
        embed.add_field(name='Failed Cogs', value=str(len(runtime_state.failed_cogs)), inline=True)
        degraded = ', '.join(runtime_state.degraded_features) or 'None'
        embed.add_field(name='Degraded Features', value=degraded, inline=False)

        # Error history
        last_error = runtime_state.last_db_error or 'None recorded'
        embed.add_field(name='Last DB Error', value=last_error, inline=False)

        if runtime_state.last_recovery_time:
            recov = runtime_state.last_recovery_time.strftime('%Y-%m-%d %H:%M:%S UTC')
            embed.add_field(name='Last Recovery', value=recov, inline=True)

        # Export status
        export_active = runtime_state.alert_state_cache.get('export_active', False)
        export_progress = runtime_state.alert_state_cache.get('export_progress', '')
        if export_active:
            embed.add_field(name='Active Export', value=export_progress or 'Running', inline=False)

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
        uptime = datetime.now(UTC) - runtime_state.startup_time
        embed = await info_embed(
            title='VEKA Bot Info',
            description='Runtime and environment details for the VEKA bot.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )

        status = 'Degraded' if self._is_degraded() else 'Healthy'
        embed.add_field(name='Status', value=status, inline=True)
        embed.add_field(name='Latency', value=f'{round(self.bot.latency * 1000)}ms', inline=True)

        stats = _get_system_stats()
        embed.add_field(name='CPU Load', value=f'{stats["cpu_percent"]}%', inline=True)
        embed.add_field(name='CPU Cores', value=str(stats['cpu_count']), inline=True)
        embed.add_field(name='Memory', value=f'{stats["mem_used_mb"]}MB ({stats["mem_percent"]}%)', inline=True)

        embed.add_field(name='Uptime', value=str(uptime).split('.')[0], inline=False)
        embed.add_field(name='Loaded Cogs', value=str(len(runtime_state.loaded_cogs)), inline=True)
        embed.add_field(name='Environment', value=ENVIRONMENT, inline=True)

        export_active = runtime_state.alert_state_cache.get('export_active', False)
        export_progress = runtime_state.alert_state_cache.get('export_progress', '')
        if export_active:
            embed.add_field(name='Active Export', value=export_progress or 'Running', inline=False)

        await safe_send(interaction, embed=embed, ephemeral=True)

    @admin.subcommand(name='featurestatus', description='Show enabled, disabled, and degraded feature status')
    @staff_only()
    @safe_slash_command()
    async def featurestatus(self, interaction: nextcord.Interaction):
        feature_status = {
            'Profiles/Networking': self._feature_state('src.cogs.networking'),
            'Marketplace': self._feature_state('src.cogs.marketplace'),
            'Resources/RSS': self._feature_state('src.cogs.resources.feeds'),
            'Database': 'Available' if runtime_state.db_available else 'Unavailable',
        }

        embed = await info_embed(
            title='VEKA Feature Status',
            description='Enabled, disabled, and degraded bot features.',
            contributor_source=__name__,
            user=interaction.user,
        )
        for name, value in feature_status.items():
            embed.add_field(name=name, value=value, inline=False)

        await safe_send(interaction, embed=embed, ephemeral=True)

    @admin.subcommand(name='startupchecks', description='Show results of initial boot checks')
    @staff_only()
    @safe_slash_command()
    async def startupchecks(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Startup Checks',
            description='Results from the system boot sequence.',
            contributor_source=__name__,
            user=interaction.user,
        )

        if not runtime_state.startup_check_results:
            embed.description = 'No startup checks were recorded.'
        else:
            for check in runtime_state.startup_check_results:
                icon = 'PASS' if check['status'] == 'PASS' else 'WARN' if check['status'] == 'WARN' else 'FAIL'
                embed.add_field(
                    name=f'[{icon}] {check["name"]}', value=f'`{check["status"]}`: {check["message"]}', inline=False
                )

        await safe_send(interaction, embed=embed, ephemeral=True)

    @admin.subcommand(name='reloadcog', description='Reload a bot cog extension')
    @staff_only()
    @safe_slash_command()
    async def reloadcog(self, interaction: nextcord.Interaction, cog_name: str):
        extension = self._resolve_extension(cog_name)
        if not extension:
            embed = await error_embed(
                title='Reload Failed',
                description=(
                    'Could not resolve the cog name. Use a full extension path '
                    'or a short cog name like `health`, `basic`, `networking`, `marketplace`, or `feeds`.'
                ),
                contributor_source=__name__,
                user=interaction.user,
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

            embed = await success_embed(
                title='Reload Successful',
                description=f'Extension `{extension}` reloaded successfully.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as exc:
            logger.error('Reload cog failed: %s', exc, exc_info=True)
            embed = await error_embed(
                title='Reload Failed',
                description=f'Unable to reload `{extension}`: {exc}',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== WRAPPER SUBCOMMANDS (from other cogs) ====================

    @admin.subcommand(name='pingsquad', description='Ping notification squad (Staff+)')
    @require_staff()
    @safe_slash_command()
    async def mp_pingsquad(self, interaction: nextcord.Interaction, message: str = 'Time to bump the server!'):
        cog = self.bot.get_cog('Notifications')
        if cog:
            await cog.ping_squad_slash(interaction, message)

    @admin.subcommand(name='panic', description='Toggle server lockdown (Founder only)')
    @require_founder()
    @safe_slash_command()
    async def mp_panic(self, interaction: nextcord.Interaction):
        cog = self.bot.get_cog('Moderation')
        if cog:
            await cog.panic_slash(interaction)

    @admin.subcommand(name='lockdown', description='Toggle server lockdown (Founder only)')
    @require_founder()
    @safe_slash_command()
    async def mp_lockdown(self, interaction: nextcord.Interaction):
        cog = self.bot.get_cog('Moderation')
        if cog:
            await cog.lockdown_slash(interaction)

    @admin.subcommand(name='broadcast', description='Send announcement to a channel (Founder only)')
    @require_founder()
    @safe_slash_command()
    async def mp_broadcast(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel,
        message: str,
    ):
        cog = self.bot.get_cog('Notifications')
        if cog:
            await cog.broadcast_slash(interaction, channel, message)


def setup(bot):
    bot.add_cog(Health(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.health')
