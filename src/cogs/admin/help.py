"""Community-neutral help, with separate local-manager and bot-operator capabilities."""

import logging
from types import SimpleNamespace

import nextcord
from nextcord.ext import commands

from src.config.config import BOT_OPERATOR_IDS
from src.services.guild_modules_service import guild_modules_service
from src.utils.embeds import info_embed
from src.utils.safety import _is_admin_user, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.admin.help')

_GROUPS = (
    ('networking', 'Profiles and connections', '/profile setup · /profile view · /connect request · /connect list'),
    (
        'marketplace',
        'Classifieds',
        '/marketplace post · /marketplace submit · /marketplace browse · /marketplace view · /marketplace mylistings · /marketplace search · /marketplace withdraw · /marketplace bump',
    ),
    ('feeds', 'Resources', '/resource sources · /resource latest'),
    (
        'mentorship',
        'Mentorship',
        '/mentor register · /mentor list · /mentor request · /mentor accept · /mentor complete',
    ),
    ('portfolio', 'Portfolio', '/portfolio add · /portfolio list · /portfolio view · /portfolio search'),
    ('leveling', 'Community activity', '/level · /leaderboard · /activity stats'),
)


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _build_help_embed(self, interaction=None, command: str | None = None) -> nextcord.Embed:
        user = (getattr(interaction, 'author', None) or getattr(interaction, 'user', None)) if interaction else None
        guild = getattr(interaction, 'guild', None)
        if command:
            name = command.lower().lstrip('!/')
            found = self.bot.get_command(name)
            if found is None:
                found = next((c for c in self.bot.get_all_application_commands() if c.name == name), None)
            description = getattr(found, 'description', None) or getattr(found, 'help', None)
            return await info_embed(
                title=f'Help: {name[:80]}',
                description=description or 'Use /commands for available commands.',
                contributor_source=__name__,
                user=user,
                guild=guild,
            )
        embed = await info_embed(
            title='VEKA Bot Help',
            description='Tools for this community. Feature availability is controlled by its server managers.',
            contributor_source=__name__,
            user=user,
            guild=guild,
        )
        embed.add_field(name='Getting started', value='/help · /commands · /ping · /privacy status', inline=False)
        if guild:
            for module, label, commands_text in _GROUPS:
                if await guild_modules_service.enabled(guild.id, module):
                    embed.add_field(name=label, value=commands_text, inline=False)
            permissions = getattr(user, 'guild_permissions', None)
            if _is_admin_user(user, guild) or (permissions and permissions.manage_guild):
                embed.add_field(
                    name='Server management',
                    value='/setup · /memberinfo · /serverinfo · dashboard at https://veka.gg/dashboard',
                    inline=False,
                )
                if _is_admin_user(user, guild):
                    embed.add_field(
                        name='Scoped export',
                        value='/exportchat exports only channels you can read in this server; /exportstop stops your export.',
                        inline=False,
                    )
        if user is not None and user.id in BOT_OPERATOR_IDS:
            embed.add_field(
                name='Bot operators',
                value='/admin reloadcog · !marketplace_queue · !marketplace_retry · !marketplace_sync',
                inline=False,
            )
        embed.set_footer(text='One network, many communities · veka.gg')
        return embed

    @commands.command(name='help')
    async def help_prefix(self, ctx, command: str | None = None):
        mini = SimpleNamespace(user=ctx.author, guild=ctx.guild)
        await safe_send(ctx, embed=await self._build_help_embed(mini, command))

    @nextcord.slash_command(name='help', description='Help for this community')
    @safe_slash_command()
    async def help_slash(self, interaction: nextcord.Interaction, command: str | None = None):
        await safe_send(interaction, embed=await self._build_help_embed(interaction, command), ephemeral=True)

    @nextcord.slash_command(name='commands', description='List available community commands')
    @safe_slash_command()
    async def commands_slash(self, interaction: nextcord.Interaction):
        await safe_send(interaction, embed=await self._build_help_embed(interaction), ephemeral=True)


def setup(bot):
    bot.add_cog(Help(bot))
