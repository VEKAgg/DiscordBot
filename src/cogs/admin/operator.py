"""Platform-scope (bot-wide) controls for VEKA's operators.

Operators are the Discord Developer Portal team (see ``src/services/operators.py``); these commands
let them manage bot-wide settings without environment variables or a redeploy.
"""

import nextcord
from nextcord.ext import commands

from src.services.bot_settings_service import bot_settings_service
from src.services.operators import operators
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.logger import get_logger
from src.utils.safety import bot_operator_only, safe_send, safe_slash_command
from src.utils.security import audit_log

logger = get_logger('VEKA.admin.operator')


def _missing_send_permissions(channel: nextcord.abc.GuildChannel) -> list[str]:
    """Permissions the bot lacks to post alerts in ``channel`` (empty = usable)."""
    me = channel.guild.me
    if me is None:
        return ['view_channel']
    perms = channel.permissions_for(me)
    needed = {
        'view_channel': perms.view_channel,
        'send_messages': perms.send_messages,
        'embed_links': perms.embed_links,
    }
    return [name for name, ok in needed.items() if not ok]


class Operator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @nextcord.slash_command(
        name='operator',
        description='Bot-wide controls for VEKA operators',
        contexts=[nextcord.InteractionContextType.guild],
    )
    async def operator(self, interaction: nextcord.Interaction):
        pass

    @operator.subcommand(name='alerts', description='Show or set the channel for bot-wide operational alerts')
    @bot_operator_only()
    @safe_slash_command(requires_db=True)
    async def alerts(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel | None = nextcord.SlashOption(
            description='Channel for alerts (leave empty to show the current one)', required=False, default=None
        ),
    ):
        if channel is None:
            current = await bot_settings_service.get_operator_alert_channel_id()
            embed = await info_embed(
                title='Operator alerts',
                description=(
                    f'Alerts go to <#{current}>.' if current else 'No alert channel is set. Alerts are not delivered.'
                ),
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        missing = _missing_send_permissions(channel)
        if missing:
            embed = await error_embed(
                title='Channel not usable',
                description=f'The bot needs {", ".join(missing)} in {channel.mention}.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await bot_settings_service.set_operator_alert_channel_id(channel.id, updated_by=interaction.user.id)
        await audit_log.record(
            user_id=str(interaction.user.id),
            action='operator_alert_channel_set',
            details={'channel_id': str(channel.id)},
            guild_id=str(interaction.guild.id) if interaction.guild else None,
        )
        embed = await success_embed(
            title='Operator alerts',
            description=f'Bot-wide alerts now go to {channel.mention}.',
            contributor_source=__name__,
            user=interaction.user,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @operator.subcommand(name='alerts-clear', description='Stop delivering bot-wide operational alerts')
    @bot_operator_only()
    @safe_slash_command(requires_db=True)
    async def alerts_clear(self, interaction: nextcord.Interaction):
        await bot_settings_service.clear_operator_alert_channel_id()
        await audit_log.record(
            user_id=str(interaction.user.id),
            action='operator_alert_channel_cleared',
            details={},
            guild_id=str(interaction.guild.id) if interaction.guild else None,
        )
        embed = await success_embed(
            title='Operator alerts',
            description='The alert channel was cleared. Alerts are not delivered until one is set.',
            contributor_source=__name__,
            user=interaction.user,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @operator.subcommand(name='refresh', description='Re-read the operator list from the Discord Developer Portal team')
    @bot_operator_only()
    @safe_slash_command()
    async def refresh(self, interaction: nextcord.Interaction):
        ok = await operators.refresh()
        count = len(operators.ids)
        if ok:
            embed = await success_embed(
                title='Operators refreshed',
                description=f'{count} operator{"s" if count != 1 else ""} from the Developer Portal team.',
                contributor_source=__name__,
                user=interaction.user,
            )
        else:
            embed = await error_embed(
                title='Refresh failed',
                description=f'Discord did not answer; keeping the last known list ({count}).',
                contributor_source=__name__,
                user=interaction.user,
            )
        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Operator(bot))
