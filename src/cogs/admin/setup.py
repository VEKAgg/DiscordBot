"""
Server Setup Cog — interactive guild configuration for channels and roles.

Provides /setup and !setup commands to configure per-server channel/role
assignments stored in the guild_settings table.
"""

import logging

import nextcord
from nextcord.ext import commands

from src.services.guild_settings_service import GuildSettings, guild_settings_service
from src.utils.embeds import error_embed, info_embed, success_embed, veka_embed
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security.rbac import require_staff

logger = logging.getLogger('VEKA.admin.setup')

# Channel setting types: key -> (display_name, field_name, description)
CHANNEL_SETTINGS = {
    'log': ('Log Channel', 'log_channel_id', 'Moderation and audit log channel'),
    'staff': ('Staff Channel', 'staff_channel_id', 'Staff discussion channel'),
    'alert': ('Alert Channel', 'alert_channel_id', 'Bot operational alerts channel'),
    'commands': ('Commands Channel', 'public_commands_channel_id', 'Public bot commands channel'),
    'welcome': ('Welcome Channel', 'welcome_channel_id', 'New member welcome channel'),
    'radio': ('Radio Channel', 'radio_channel_id', 'Radio voice channel'),
    'leaderboard': ('Leaderboard Channel', 'leaderboard_channel_id', 'Auto-updating leaderboard channel'),
}

ROLE_SETTINGS = {
    'muted': ('Muted Role', 'muted_role_id', 'Role assigned to muted users'),
}

ALL_SETTINGS = {**CHANNEL_SETTINGS, **ROLE_SETTINGS}


def _format_channel(guild: nextcord.Guild, channel_id: int | None) -> str:
    if channel_id is None:
        return '`Not set`'
    ch = guild.get_channel(channel_id)
    return ch.mention if ch else f'<#{channel_id}> (deleted?)'


def _format_role(guild: nextcord.Guild, role_id: int | None) -> str:
    if role_id is None:
        return '`Not set`'
    role = guild.get_role(role_id)
    return role.mention if role else f'&{role_id} (deleted?)'


def _build_settings_embed(guild: nextcord.Guild, settings: GuildSettings) -> list[str]:
    return [
        f'**Log Channel**: {_format_channel(guild, settings.log_channel_id)}',
        f'**Staff Channel**: {_format_channel(guild, settings.staff_channel_id)}',
        f'**Alert Channel**: {_format_channel(guild, settings.alert_channel_id)}',
        f'**Commands Channel**: {_format_channel(guild, settings.public_commands_channel_id)}',
        f'**Welcome Channel**: {_format_channel(guild, settings.welcome_channel_id)}',
        f'**Radio Channel**: {_format_channel(guild, settings.radio_channel_id)}',
        f'**Leaderboard Channel**: {_format_channel(guild, settings.leaderboard_channel_id)}',
        f'**Muted Role**: {_format_role(guild, settings.muted_role_id)}',
    ]


class Setup(commands.Cog):
    """Interactive server setup for guild-specific channel and role configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ============================================================
    # Slash commands
    # ============================================================

    @nextcord.slash_command(name='setup', description='Configure server-specific bot settings')
    async def setup_group(self, interaction: nextcord.Interaction):
        settings = await guild_settings_service.get_settings(interaction.guild.id)
        lines = _build_settings_embed(interaction.guild, settings)
        embed = await veka_embed(
            title='Current Server Settings',
            description='\n'.join(lines),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @setup_group.subcommand(name='show', description='Show all configured channels and roles for this server')
    @safe_slash_command()
    @require_staff()
    async def setup_show(self, interaction: nextcord.Interaction):
        """Display all configured channels and roles."""
        settings = await guild_settings_service.get_settings(interaction.guild.id)
        lines = _build_settings_embed(interaction.guild, settings)
        embed = await veka_embed(
            title='Server Settings',
            description='\n'.join(lines),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @setup_group.subcommand(name='set', description='Set a channel or role for this server')
    @safe_slash_command()
    @require_staff()
    async def setup_set(
        self,
        interaction: nextcord.Interaction,
        setting_type: str = nextcord.SlashOption(
            description='Setting to configure',
            choices=list(ALL_SETTINGS.keys()),
        ),
        channel: nextcord.TextChannel | nextcord.VoiceChannel | None = nextcord.SlashOption(
            description='Channel (for channel settings)', required=False
        ),
        role: nextcord.Role | None = nextcord.SlashOption(description='Role (for role settings)', required=False),
    ):
        """Set a channel or role configuration."""
        if setting_type in CHANNEL_SETTINGS:
            if channel is None:
                embed = await error_embed(
                    title='Missing Channel',
                    description=f'Please provide a channel for the **{CHANNEL_SETTINGS[setting_type][0]}** setting.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            field_name = CHANNEL_SETTINGS[setting_type][1]
            await guild_settings_service.update_settings(interaction.guild.id, **{field_name: channel.id})
            embed = await success_embed(
                title='Setting Updated',
                description=f'**{CHANNEL_SETTINGS[setting_type][0]}** set to {channel.mention}',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
        elif setting_type in ROLE_SETTINGS:
            if role is None:
                embed = await error_embed(
                    title='Missing Role',
                    description=f'Please provide a role for the **{ROLE_SETTINGS[setting_type][0]}** setting.',
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            field_name = ROLE_SETTINGS[setting_type][1]
            await guild_settings_service.update_settings(interaction.guild.id, **{field_name: role.id})
            embed = await success_embed(
                title='Setting Updated',
                description=f'**{ROLE_SETTINGS[setting_type][0]}** set to {role.mention}',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
        else:
            embed = await error_embed(
                title='Unknown Setting',
                description=f'`{setting_type}` is not a valid setting type.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await safe_send(interaction, embed=embed, ephemeral=True)

    @setup_group.subcommand(name='reset', description='Clear a channel or role setting back to default')
    @safe_slash_command()
    @require_staff()
    async def setup_reset(
        self,
        interaction: nextcord.Interaction,
        setting_type: str = nextcord.SlashOption(
            description='Setting to reset',
            choices=list(ALL_SETTINGS.keys()),
        ),
    ):
        """Reset a setting to None (will fall back to config.py defaults)."""
        if setting_type in CHANNEL_SETTINGS:
            field_name = CHANNEL_SETTINGS[setting_type][1]
            label = CHANNEL_SETTINGS[setting_type][0]
        elif setting_type in ROLE_SETTINGS:
            field_name = ROLE_SETTINGS[setting_type][1]
            label = ROLE_SETTINGS[setting_type][0]
        else:
            embed = await error_embed(
                title='Unknown Setting',
                description=f'`{setting_type}` is not a valid setting type.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await guild_settings_service.update_settings(interaction.guild.id, **{field_name: None})
        embed = await success_embed(
            title='Setting Reset',
            description=f'**{label}** has been cleared. The bot will fall back to the default configuration.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @setup_group.subcommand(name='interactive', description='Configure channels and roles using interactive dropdowns')
    @safe_slash_command()
    @require_staff()
    async def setup_interactive(self, interaction: nextcord.Interaction):
        """Open an interactive UI to configure channels and roles via dropdowns."""
        view = SetupView(interaction.guild, interaction.user)
        embed = await veka_embed(
            title='Interactive Server Setup',
            description=(
                '**Step 1:** Select a setting from the dropdown.\n'
                '**Step 2:** Mention the channel or role in chat.\n\n'
                'The bot will detect your mention and apply the setting.'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ============================================================
    # Prefix commands
    # ============================================================

    @commands.group(name='setup', invoke_without_command=True)
    @require_staff()
    async def setup_prefix(self, ctx: commands.Context):
        """Show current server settings. Use !setup <subcommand> for more options."""
        settings = await guild_settings_service.get_settings(ctx.guild.id)
        lines = _build_settings_embed(ctx.guild, settings)
        await safe_send(ctx, '\n'.join(['**Server Settings**\n'] + lines))

    @setup_prefix.command(name='show')
    @require_staff()
    async def setup_show_prefix(self, ctx: commands.Context):
        """Show all configured channels and roles."""
        settings = await guild_settings_service.get_settings(ctx.guild.id)
        lines = _build_settings_embed(ctx.guild, settings)
        await safe_send(ctx, '\n'.join(['**Server Settings**\n'] + lines))

    @setup_prefix.command(name='set')
    @require_staff()
    async def setup_set_prefix(self, ctx: commands.Context, setting_type: str, *, target: str):
        """Set a channel or role. Usage: !setup set <type> <#channel or @role>"""
        if setting_type in CHANNEL_SETTINGS:
            if ctx.message.channel_mentions:
                channel = ctx.message.channel_mentions[0]
                field_name = CHANNEL_SETTINGS[setting_type][1]
                await guild_settings_service.update_settings(ctx.guild.id, **{field_name: channel.id})
                await safe_send(ctx, f'\u2705 **{CHANNEL_SETTINGS[setting_type][0]}** set to {channel.mention}')
                return
        elif setting_type in ROLE_SETTINGS:
            if ctx.message.role_mentions:
                role = ctx.message.role_mentions[0]
                field_name = ROLE_SETTINGS[setting_type][1]
                await guild_settings_service.update_settings(ctx.guild.id, **{field_name: role.id})
                await safe_send(ctx, f'\u2705 **{ROLE_SETTINGS[setting_type][0]}** set to {role.mention}')
                return

        await safe_send(ctx, f'\u274c Could not resolve `{target}`. Use a channel or role mention.')

    @setup_prefix.command(name='reset')
    @require_staff()
    async def setup_reset_prefix(self, ctx: commands.Context, setting_type: str):
        """Reset a setting to default. Usage: !setup reset <type>"""
        if setting_type in CHANNEL_SETTINGS:
            field_name = CHANNEL_SETTINGS[setting_type][1]
            label = CHANNEL_SETTINGS[setting_type][0]
        elif setting_type in ROLE_SETTINGS:
            field_name = ROLE_SETTINGS[setting_type][1]
            label = ROLE_SETTINGS[setting_type][0]
        else:
            await safe_send(ctx, f'\u274c `{setting_type}` is not a valid setting type.')
            return

        await guild_settings_service.update_settings(ctx.guild.id, **{field_name: None})
        await safe_send(ctx, f'\u2705 **{label}** has been cleared.')


# ============================================================
# Interactive UI View
# ============================================================

SETTING_CHOICES = [nextcord.SelectOption(label=v[0], value=k, description=v[2]) for k, v in ALL_SETTINGS.items()]


class SetupView(nextcord.ui.View):
    """Interactive view with a setting-type dropdown. User picks a setting, then mentions the channel/role in chat."""

    def __init__(self, guild: nextcord.Guild, user: nextcord.Member):
        super().__init__(timeout=300)
        self.guild = guild
        self.user = user
        self.selected_setting: str | None = None

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message('This setup panel is not for you.', ephemeral=True)
            return False
        return True

    @nextcord.ui.select(
        placeholder='Choose a setting to configure...',
        options=SETTING_CHOICES,
        min_values=1,
        max_values=1,
    )
    async def setting_select(self, select: nextcord.ui.Select, interaction: nextcord.Interaction):
        self.selected_setting = select.values[0]
        setting_info = ALL_SETTINGS[self.selected_setting]
        is_role = self.selected_setting in ROLE_SETTINGS
        kind = 'role' if is_role else 'channel'

        embed = await info_embed(
            title=f'Configure: {setting_info[0]}',
            description=(
                f'{setting_info[2]}\n\n'
                f'**Mention the {kind}** you want to use in chat, or type `reset` to clear this setting.'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Setup(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.setup')
    return True
