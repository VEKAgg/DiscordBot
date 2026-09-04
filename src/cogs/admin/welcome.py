"""Welcome System — greets new members with a visual card and configurable message."""

import logging

import aiohttp
import nextcord
from nextcord.ext import commands

from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import info_embed, success_embed
from src.utils.safety import safe_send, safe_slash_command

logger = logging.getLogger('VEKA.welcome')


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        """Greet a new member with a welcome card and message."""
        if member.bot:
            return

        try:
            settings = await guild_settings_service.get_settings(member.guild.id)
            if not settings.welcome_channel_id:
                return

            channel = member.guild.get_channel(settings.welcome_channel_id)
            if not channel or not isinstance(channel, nextcord.TextChannel):
                return

            # Render welcome template
            template = settings.welcome_message_template or 'Welcome {user} to {server}!'
            welcome_text = template.format(
                user=member.mention,
                server=member.guild.name,
                member_count=member.guild.member_count,
            )

            # Build embed
            embed = await info_embed(
                title=f'Welcome to {member.guild.name}!',
                description=welcome_text,
                user=member,
                contributor_source=__name__,
            )
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            embed.set_footer(text=f'Member #{member.guild.member_count}')

            # Generate welcome card if enabled
            if settings.welcome_card_enabled:
                avatar_bytes = await self._download_asset(
                    member.avatar.url if member.avatar else member.default_avatar.url
                )
                icon_bytes = None
                if member.guild.icon:
                    icon_bytes = await self._download_asset(member.guild.icon.url)

                from src.utils.card_generator import generate_welcome_card

                buffer = await generate_welcome_card(
                    username=member.display_name,
                    avatar_bytes=avatar_bytes,
                    server_name=member.guild.name,
                    member_count=member.guild.member_count,
                    server_icon_bytes=icon_bytes,
                )
                file = nextcord.File(fp=buffer, filename='welcome_card.png')
                embed.set_image(url='attachment://welcome_card.png')
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

        except Exception as e:
            logger.error('Failed to send welcome message for %s: %s', member, e, exc_info=True)

    async def _download_asset(self, url: str) -> bytes | None:
        """Download a Discord asset (avatar/icon) as bytes."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception:
            pass
        return None

    @nextcord.slash_command(name='welcome', description='Welcome system commands')
    @safe_slash_command()
    async def welcome_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Welcome Commands',
            description=('**Available subcommands:**\n\n• `/welcome test` — Preview the welcome card for yourself'),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @welcome_group.subcommand(name='test', description='Preview the welcome card for yourself')
    @safe_slash_command()
    async def welcome_test(self, interaction: nextcord.Interaction):
        """Generate and send a preview welcome card."""
        if not interaction.guild:
            embed = await info_embed(
                title='Server Only',
                description='This command can only be used in a server.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        settings = await guild_settings_service.get_settings(interaction.guild.id)

        template = settings.welcome_message_template or 'Welcome {user} to {server}!'
        welcome_text = template.format(
            user=interaction.user.mention,
            server=interaction.guild.name,
            member_count=interaction.guild.member_count,
        )

        embed = await success_embed(
            title=f'Welcome to {interaction.guild.name}!',
            description=welcome_text,
            user=interaction.user,
            contributor_source=__name__,
        )
        embed.set_thumbnail(
            url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url
        )
        embed.set_footer(text=f'Member #{interaction.guild.member_count}')

        avatar_bytes = await self._download_asset(
            interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url
        )
        icon_bytes = None
        if interaction.guild.icon:
            icon_bytes = await self._download_asset(interaction.guild.icon.url)

        from src.utils.card_generator import generate_welcome_card

        buffer = await generate_welcome_card(
            username=interaction.user.display_name,
            avatar_bytes=avatar_bytes,
            server_name=interaction.guild.name,
            member_count=interaction.guild.member_count,
            server_icon_bytes=icon_bytes,
        )
        file = nextcord.File(fp=buffer, filename='welcome_card.png')
        embed.set_image(url='attachment://welcome_card.png')
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Welcome(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.welcome')
