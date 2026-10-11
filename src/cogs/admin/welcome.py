"""Welcome System — greets new members with a visual card and configurable message."""

import asyncio
import logging
import time
from collections import deque

import aiohttp
import nextcord
from nextcord.ext import commands

from src.core.lifecycle import spawn
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import info_embed, success_embed
from src.utils.http import get_session
from src.utils.outbound import DigestBuffer, outbound
from src.utils.safety import safe_send, safe_slash_command

logger = logging.getLogger('VEKA.welcome')

# Raid mode: more than RAID_JOIN_THRESHOLD joins within RAID_WINDOW_SECONDS switches a guild to one
# batched welcome per window (no cards), instead of a message + rendered card per member.
RAID_JOIN_THRESHOLD = 5
RAID_WINDOW_SECONDS = 60
_BATCH_MAX_MENTIONS = 30


def render_welcome(template: str, user_mention: str, guild: nextcord.Guild) -> str:
    """Substitute {user}/{server}/{member_count}. Plain replacement: str.format raised KeyError on unknown
    fields and allows attribute lookups in staff-written templates (audit L-10)."""
    values = {'user': user_mention, 'server': guild.name, 'member_count': guild.member_count}
    for key, value in values.items():
        template = template.replace('{' + key + '}', str(value))
    return template


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent_joins: dict[int, deque[float]] = {}
        self._batches: dict[int, DigestBuffer] = {}
        self._batch_tasks: set[asyncio.Task] = set()

    def cog_unload(self) -> None:
        for task in tuple(self._batch_tasks):
            task.cancel()
        self._batches.clear()

    def _is_raid(self, guild_id: int) -> bool:
        now = time.monotonic()
        joins = self._recent_joins.setdefault(guild_id, deque(maxlen=RAID_JOIN_THRESHOLD + 1))
        joins.append(now)
        while joins and now - joins[0] > RAID_WINDOW_SECONDS:
            joins.popleft()
        if not joins:
            self._recent_joins.pop(guild_id, None)
        return len(joins) > RAID_JOIN_THRESHOLD

    async def _flush_batch(self, guild: nextcord.Guild, channel: nextcord.TextChannel) -> None:
        await asyncio.sleep(RAID_WINDOW_SECONDS)
        batch = self._batches.pop(guild.id, None)
        from src.services.guild_modules_service import guild_modules_service

        if not await guild_modules_service.enabled(guild.id, 'welcome'):
            return
        if batch is None or batch.count == 0:
            return
        shown = batch.sample
        more = batch.count - len(shown)
        embed = await info_embed(
            title=f'Welcome to {guild.name}!',
            description=f'Welcome {", ".join(shown)}' + (f' and {more} others' if more else '') + '!',
            contributor_source=__name__,
        )
        await outbound.send(
            channel,
            kind='welcome_batch',
            guild_id=guild.id,
            embed=embed,
            allowed_mentions=nextcord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        """Greet a new member with a welcome card and message."""
        from src.services.guild_modules_service import guild_modules_service

        if member.bot or not await guild_modules_service.enabled(member.guild.id, 'welcome'):
            return

        try:
            settings = await guild_settings_service.get_settings(member.guild.id)
            if not settings.welcome_channel_id:
                return

            channel = member.guild.get_channel(settings.welcome_channel_id)
            if not channel or not isinstance(channel, nextcord.TextChannel):
                return

            if self._is_raid(member.guild.id) or member.guild.id in self._batches:
                first = member.guild.id not in self._batches
                self._batches.setdefault(member.guild.id, DigestBuffer(limit=_BATCH_MAX_MENTIONS)).add(member.mention)
                if first:
                    task = spawn(self._flush_batch(member.guild, channel), name=f'welcome:batch:{member.guild.id}')
                    if task is not None:
                        self._batch_tasks.add(task)
                        task.add_done_callback(self._batch_tasks.discard)
                return

            # Render welcome template
            template = settings.welcome_message_template or 'Welcome {user} to {server}!'
            welcome_text = render_welcome(template, member.mention, member.guild)

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
                    member_count=member.guild.member_count or 0,
                    server_icon_bytes=icon_bytes,
                )
                file = nextcord.File(fp=buffer, filename='welcome_card.png')
                embed.set_image(url='attachment://welcome_card.png')
                await outbound.send(channel, kind='welcome', guild_id=member.guild.id, embed=embed, file=file)
            else:
                await outbound.send(channel, kind='welcome', guild_id=member.guild.id, embed=embed)

        except Exception as e:
            logger.error('Failed to send welcome message for %s: %s', member, e, exc_info=True)

    async def _download_asset(self, url: str) -> bytes | None:
        """Download a Discord asset (avatar/icon) as bytes."""
        try:
            async with get_session().get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
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
        welcome_text = render_welcome(template, interaction.user.mention, interaction.guild)

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
            member_count=interaction.guild.member_count or 0,
            server_icon_bytes=icon_bytes,
        )
        file = nextcord.File(fp=buffer, filename='welcome_card.png')
        embed.set_image(url='attachment://welcome_card.png')
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Welcome(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.welcome')
