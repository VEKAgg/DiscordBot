"""
Server Setup Cog — interactive guild configuration for channels and roles.

Provides /setup and !setup commands to configure per-server channel/role
assignments stored in the guild_settings table.
"""

import logging

import nextcord
from nextcord.ext import commands

from src.services.guild_settings_policy import CHANNEL_SETTINGS, ROLE_SETTINGS, TOGGLE_SETTINGS
from src.services.guild_settings_policy import allowed_channel_types as _allowed_type_names
from src.services.guild_settings_policy import channel_type_error as _type_error_for
from src.services.guild_settings_service import GuildSettings, guild_settings_service
from src.utils.embeds import error_embed, info_embed, success_embed, veka_embed
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security import audit_log
from src.utils.security.rbac import require_staff

logger = logging.getLogger('VEKA.admin.setup')

ALL_SETTINGS = {**CHANNEL_SETTINGS, **ROLE_SETTINGS}


def allowed_channel_types(setting_key: str) -> tuple[nextcord.ChannelType, ...]:
    return tuple(getattr(nextcord.ChannelType, name) for name in _allowed_type_names(setting_key))


def channel_type_error(setting_key: str, channel: nextcord.abc.GuildChannel) -> str | None:
    """Return a user-facing error if ``channel`` can't be used for ``setting_key``."""
    return _type_error_for(setting_key, channel.type.name)


async def _audit_setting(guild_id: int, user_id: int, field_name: str, value: int | None) -> None:
    """Record a settings change (audit M-06). Never blocks the change itself."""
    try:
        await audit_log.record(
            user_id=str(user_id),
            action='guild_setting_changed',
            details={'field': field_name, 'value': str(value) if value is not None else None, 'source': 'discord'},
            guild_id=str(guild_id),
            severity='info',
        )
    except Exception:
        logger.warning('Failed to audit setting change %s in %s', field_name, guild_id, exc_info=True)


ROLE_SETTINGS = {
    'muted': ('Muted Role', 'muted_role_id', 'Role assigned to muted users'),
}


def _format_channel(guild: nextcord.Guild, channel_id: int | None) -> str:
    if channel_id is None:
        return '`Not set`'
    ch = guild.get_channel(channel_id)
    return ch.mention if ch else f'<#{channel_id}> (deleted?)'


def _format_role(guild: nextcord.Guild, role_id: int | None) -> str:
    if role_id is None:
        return '`Not set`'
    role = guild.get_role(role_id)
    return role.mention if role else f'<@&{role_id}> (deleted?)'


def _build_settings_embed(guild: nextcord.Guild, settings: GuildSettings) -> list[str]:
    return [
        f'**Log Channel**: {_format_channel(guild, settings.log_channel_id)}',
        f'**Staff Channel**: {_format_channel(guild, settings.staff_channel_id)}',
        f'**Alert Channel**: {_format_channel(guild, settings.alert_channel_id)}',
        f'**Commands Channel**: {_format_channel(guild, settings.public_commands_channel_id)}',
        f'**Welcome Channel**: {_format_channel(guild, settings.welcome_channel_id)}',
        f'**Radio Channel**: {_format_channel(guild, settings.radio_channel_id)}',
        f'**Leaderboard Channel**: {_format_channel(guild, settings.leaderboard_channel_id)}',
        f'**Marketplace Channel**: {_format_channel(guild, settings.marketplace_channel_id)}',
        f'**Muted Role**: {_format_role(guild, settings.muted_role_id)}',
        f'**Inactivity DMs**: {"On" if settings.inactivity_dm_enabled else "Off"}',
        f'**Welcome Cards**: {"On" if settings.welcome_card_enabled else "Off"}',
    ]


class Setup(commands.Cog):
    """Interactive server setup for guild-specific channel and role configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ============================================================
    # Slash commands
    # ============================================================

    @nextcord.slash_command(
        name='setup',
        description='Configure server-specific bot settings',
        contexts=[nextcord.InteractionContextType.guild],
    )
    async def setup_group(self, interaction: nextcord.Interaction):
        assert interaction.guild is not None  # /setup is guild-only (contexts=[guild])
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
    @require_staff()
    @safe_slash_command()
    async def setup_show(self, interaction: nextcord.Interaction):
        """Display all configured channels and roles."""
        assert interaction.guild is not None  # /setup is guild-only (contexts=[guild])
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
    @require_staff()
    @safe_slash_command()
    async def setup_set(
        self,
        interaction: nextcord.Interaction,
        setting_type: str = nextcord.SlashOption(
            description='Setting to configure',
            choices=list(ALL_SETTINGS.keys()),
        ),
        channel: nextcord.abc.GuildChannel | None = nextcord.SlashOption(
            description='Channel (for channel settings)',
            required=False,
            channel_types=[
                nextcord.ChannelType.text,
                nextcord.ChannelType.news,
                nextcord.ChannelType.forum,
                nextcord.ChannelType.voice,
                nextcord.ChannelType.stage_voice,
            ],
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

            type_error = channel_type_error(setting_type, channel)
            if type_error:
                embed = await error_embed(
                    title='Wrong Channel Type',
                    description=type_error,
                    contributor_source=__name__,
                    user=interaction.user,
                    guild=interaction.guild,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            field_name = CHANNEL_SETTINGS[setting_type][1]
            await guild_settings_service.update_settings(interaction.guild.id, **{field_name: channel.id})
            await _audit_setting(interaction.guild.id, interaction.user.id, field_name, channel.id)
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
            await _audit_setting(interaction.guild.id, interaction.user.id, field_name, role.id)
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
    @require_staff()
    @safe_slash_command()
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
        await _audit_setting(interaction.guild.id, interaction.user.id, field_name, None)
        embed = await success_embed(
            title='Setting Reset',
            description=f'**{label}** has been cleared. The bot will fall back to the default configuration.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @setup_group.subcommand(name='option', description='Turn an on/off server option on or off')
    @require_staff()
    @safe_slash_command(requires_db=True)
    async def setup_option(
        self,
        interaction: nextcord.Interaction,
        option: str = nextcord.SlashOption(description='Option', choices=list(TOGGLE_SETTINGS.keys())),
        enabled: bool = nextcord.SlashOption(description='On or off'),
    ):
        label, field_name, _ = TOGGLE_SETTINGS[option]
        await guild_settings_service.update_settings(interaction.guild.id, **{field_name: enabled})
        await _audit_setting(interaction.guild.id, interaction.user.id, field_name, int(enabled))
        embed = await success_embed(
            title='Setting Updated',
            description=f'**{label}** is now **{"on" if enabled else "off"}**.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @setup_group.subcommand(name='interactive', description='Configure channels and roles using interactive dropdowns')
    @require_staff()
    @safe_slash_command()
    async def setup_interactive(self, interaction: nextcord.Interaction):
        """Open an interactive UI to configure channels and roles via dropdowns."""
        assert interaction.guild is not None and isinstance(interaction.user, nextcord.Member)
        view = SetupView(interaction.guild, interaction.user)
        embed = await veka_embed(
            title='Interactive Server Setup',
            description=(
                '**Step 1:** Select a setting from the dropdown.\n'
                '**Step 2:** Pick the channel or role from the picker that appears (or press Reset).'
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
    @commands.guild_only()
    @require_staff()
    async def setup_prefix(self, ctx: commands.Context):
        """Show current server settings. Use !setup <subcommand> for more options."""
        assert ctx.guild is not None  # guild_only
        settings = await guild_settings_service.get_settings(ctx.guild.id)
        lines = _build_settings_embed(ctx.guild, settings)
        await safe_send(ctx, '\n'.join(['**Server Settings**\n'] + lines))

    @setup_prefix.command(name='show')
    @require_staff()
    async def setup_show_prefix(self, ctx: commands.Context):
        """Show all configured channels and roles."""
        assert ctx.guild is not None  # guild_only
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
                type_error = channel_type_error(setting_type, channel)
                if type_error:
                    await safe_send(ctx, f'\u274c {type_error}')
                    return
                field_name = CHANNEL_SETTINGS[setting_type][1]
                await guild_settings_service.update_settings(ctx.guild.id, **{field_name: channel.id})
                await _audit_setting(ctx.guild.id, ctx.author.id, field_name, channel.id)
                await safe_send(ctx, f'\u2705 **{CHANNEL_SETTINGS[setting_type][0]}** set to {channel.mention}')
                return
        elif setting_type in ROLE_SETTINGS:
            if ctx.message.role_mentions:
                role = ctx.message.role_mentions[0]
                field_name = ROLE_SETTINGS[setting_type][1]
                await guild_settings_service.update_settings(ctx.guild.id, **{field_name: role.id})
                await _audit_setting(ctx.guild.id, ctx.author.id, field_name, role.id)
                await safe_send(ctx, f'\u2705 **{ROLE_SETTINGS[setting_type][0]}** set to {role.mention}')
                return

        await safe_send(ctx, f'\u274c Could not resolve `{target}`. Use a channel or role mention.')

    @setup_prefix.command(name='option')
    @require_staff()
    async def setup_option_prefix(self, ctx: commands.Context, option: str, value: str):
        """Turn an option on or off. Usage: !setup option <inactivity_dms|welcome_cards> <on|off>"""
        if option not in TOGGLE_SETTINGS or value.lower() not in ('on', 'off'):
            names = ', '.join(TOGGLE_SETTINGS)
            await safe_send(ctx, f'\u274c Usage: `!setup option <{names}> <on|off>`')
            return
        label, field_name, _ = TOGGLE_SETTINGS[option]
        enabled = value.lower() == 'on'
        await guild_settings_service.update_settings(ctx.guild.id, **{field_name: enabled})
        await _audit_setting(ctx.guild.id, ctx.author.id, field_name, int(enabled))
        await safe_send(ctx, f'\u2705 **{label}** is now **{value.lower()}**.')

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
        await _audit_setting(ctx.guild.id, ctx.author.id, field_name, None)
        await safe_send(ctx, f'\u2705 **{label}** has been cleared.')


# ============================================================
# Interactive UI View
# ============================================================

SETTING_CHOICES = [nextcord.SelectOption(label=v[0], value=k, description=v[2]) for k, v in ALL_SETTINGS.items()]


class SetupView(nextcord.ui.View):
    """Interactive setup: pick a setting, then pick the channel/role with a native select (audit M-17).

    The previous flow asked users to mention the channel in chat, but nothing listened for it.
    """

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
        kind = 'role' if self.selected_setting in ROLE_SETTINGS else 'channel'

        embed = await info_embed(
            title=f'Configure: {setting_info[0]}',
            description=f'{setting_info[2]}\n\nPick the {kind} below, or press **Reset** to clear this setting.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        view = SetupValueView(self.guild, self.user, self.selected_setting)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class SetupValueView(nextcord.ui.View):
    """Second step: a ChannelSelect / RoleSelect for one setting, plus a Reset button."""

    def __init__(self, guild: nextcord.Guild, user: nextcord.Member, setting_key: str):
        super().__init__(timeout=300)
        self.guild = guild
        self.user = user
        self.setting_key = setting_key
        self.label, self.field_name, _ = ALL_SETTINGS[setting_key]

        picker: nextcord.ui.ChannelSelect | nextcord.ui.RoleSelect
        if setting_key in ROLE_SETTINGS:
            picker = nextcord.ui.RoleSelect(placeholder=f'Select the {self.label}...')
        else:
            channel_types = list(allowed_channel_types(setting_key))
            picker = nextcord.ui.ChannelSelect(placeholder=f'Select the {self.label}...', channel_types=channel_types)
        picker.callback = self._on_pick  # type: ignore[method-assign]
        self.picker = picker
        self.add_item(picker)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message('This setup panel is not for you.', ephemeral=True)
            return False
        return True

    async def _on_pick(self, interaction: nextcord.Interaction):
        values = self.picker.values
        chosen = (values.roles if isinstance(self.picker, nextcord.ui.RoleSelect) else values.channels) or []
        if not chosen:
            await interaction.response.send_message('Nothing selected.', ephemeral=True)
            return
        target = chosen[0]
        await guild_settings_service.update_settings(self.guild.id, **{self.field_name: target.id})
        await _audit_setting(self.guild.id, interaction.user.id, self.field_name, target.id)
        embed = await success_embed(
            title='Setting Updated',
            description=f'**{self.label}** set to {target.mention}',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @nextcord.ui.button(label='Reset', style=nextcord.ButtonStyle.secondary)
    async def reset_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await guild_settings_service.update_settings(self.guild.id, **{self.field_name: None})
        await _audit_setting(self.guild.id, interaction.user.id, self.field_name, None)
        embed = await success_embed(
            title='Setting Reset',
            description=f'**{self.label}** has been cleared. The bot will fall back to the default configuration.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


def setup(bot: commands.Bot):
    bot.add_cog(Setup(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.setup')
    return True
