"""
External Server Info Commands — owner-only in external servers.
Provides /memberinfo and /serverinfo for server intelligence.
"""

import logging
from datetime import UTC, datetime

import nextcord
from nextcord.ext import commands

from src.utils.embeds import info_embed
from src.utils.guild_gate import owner_in_external_only
from src.utils.safety import safe_send, safe_slash_command

logger = logging.getLogger('VEKA.external.info')


class ExternalInfo(commands.Cog):
    """Owner-only info commands for external servers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @nextcord.slash_command(name='memberinfo', description='Show detailed info about a member')
    @owner_in_external_only()
    @safe_slash_command()
    async def memberinfo(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member = nextcord.SlashOption(description='Member to inspect'),
    ):
        """Show detailed member information."""
        user = member
        joined = user.joined_at
        created = user.created_at

        # Format dates
        joined_text = 'Unknown'
        joined_age = ''
        if joined:
            if joined.tzinfo is None:
                joined = joined.replace(tzinfo=UTC)
            joined_text = joined.strftime('%Y-%m-%d %H:%M UTC')
            delta = datetime.now(UTC) - joined
            joined_age = f'{delta.days} days ago'

        created_text = 'Unknown'
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            created_text = created.strftime('%Y-%m-%d %H:%M UTC')

        # Roles
        roles = [r.mention for r in user.roles if r != user.guild.default_role]
        roles_text = ', '.join(roles) if roles else 'None'
        top_role = user.top_role.mention if user.top_role != user.guild.default_role else 'None'

        description = (
            f'**User**: {user.mention}\n'
            f'**ID**: `{user.id}`\n'
            f'**Display Name**: {user.display_name}\n'
            f'**Joined**: {joined_text} ({joined_age})\n'
            f'**Account Created**: {created_text}\n'
            f'**Top Role**: {top_role}\n'
            f'**Roles** ({len(roles)}): {roles_text}\n'
            f'**Bot**: {"Yes" if user.bot else "No"}'
        )

        embed = await info_embed(
            title=f'Member Info: {user.display_name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )

        if user.avatar:
            embed.set_thumbnail(url=user.avatar.url)

        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='serverinfo', description='Show detailed info about this server')
    @owner_in_external_only()
    @safe_slash_command()
    async def serverinfo(self, interaction: nextcord.Interaction):
        """Show detailed server information."""
        guild = interaction.guild
        if not guild:
            embed = await info_embed(
                title='Error',
                description='This command can only be used in a server.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        # Counts
        text_channels = len([c for c in guild.text_channels])
        voice_channels = len([c for c in guild.voice_channels])
        categories = len(guild.categories)
        total_members = guild.member_count
        online_members = sum(1 for m in guild.members if m.status != nextcord.Status.offline)

        # Boost info
        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0

        # Owner
        owner = guild.owner
        owner_text = owner.mention if owner else 'Unknown'

        # Created
        created = guild.created_at
        created_text = 'Unknown'
        created_age = ''
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            created_text = created.strftime('%Y-%m-%d %H:%M UTC')
            delta = datetime.now(UTC) - created
            created_age = f'{delta.days} days ago'

        description = (
            f'**Name**: {guild.name}\n'
            f'**ID**: `{guild.id}`\n'
            f'**Owner**: {owner_text}\n'
            f'**Members**: {total_members} (Online: {online_members})\n'
            f'**Channels**: {text_channels + voice_channels} (Text: {text_channels}, Voice: {voice_channels}, Categories: {categories})\n'
            f'**Roles**: {len(guild.roles)}\n'
            f'**Boost Level**: Level {boost_level} ({boost_count} boosts)\n'
            f'**Created**: {created_text} ({created_age})'
        )

        embed = await info_embed(
            title=f'Server Info: {guild.name}',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(ExternalInfo(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.external.info')
    return True
