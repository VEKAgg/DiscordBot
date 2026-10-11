"""Privacy Cog — members control presence tracking and can delete their activity data.

Presence-derived tracking (games, coding apps, streaming) runs only in servers that enabled it, and stops
for a member who runs ``/privacy optout`` (``/privacy optin`` allows it again).
Message, voice and command counts (XP) are always recorded; ``/privacy delete``
erases all of a member's activity data and XP. Listening/Spotify is never tracked.
"""

from __future__ import annotations

import logging

import nextcord
from nextcord.ext import commands

from src.database.database import db
from src.services import privacy_service
from src.utils.embeds import info_embed, success_embed, veka_embed
from src.utils.safety import safe_command, safe_send, safe_slash_command
from src.utils.security import audit_log as audit_log  # Compatibility for existing test patches.

logger = logging.getLogger('VEKA.privacy')

WHAT_IS_TRACKED = (
    '**Always (needed for XP and levels):** message count, voice minutes, command count, streaks.\n'
    '**In servers that enabled activity tracking, unless you opt out:** games you play, coding apps, and '
    'streaming time (from your Discord activity), '
    'shown in `/most` and activity stats.\n'
    '**Never:** music/Spotify, message content, DMs.'
)


async def set_presence_opt_in(bot: commands.Bot, user_id: int, enabled: bool) -> None:
    changed_at = await privacy_service.set_presence_opt_in(user_id, enabled, database=db)
    rpg = bot.get_cog('RPGManager')
    if rpg is not None:
        rpg.set_opt_in(user_id, enabled, changed_at)  # type: ignore[attr-defined]


async def delete_activity_data(bot: commands.Bot, user_id: int) -> None:
    await privacy_service.delete_activity_data(user_id, database=db)
    rpg = bot.get_cog('RPGManager')
    if rpg is not None:
        rpg.set_opt_in(user_id, False)  # type: ignore[attr-defined]


class ConfirmDeleteView(nextcord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('This confirmation is not for you.', ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label='Delete my activity data', style=nextcord.ButtonStyle.danger)
    async def confirm(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.stop()
        await interaction.response.defer()  # the transaction can take longer than the 3 s deadline
        try:
            await delete_activity_data(self.bot, self.user_id)
            text = 'Your activity data and XP were deleted, and presence tracking is off.'
        except Exception:
            logger.error('Privacy deletion failed for %s', self.user_id, exc_info=True)
            text = 'Deletion failed; nothing was changed. Please try again later.'
        await interaction.edit_original_message(content=text, embed=None, view=None)

    @nextcord.ui.button(label='Cancel', style=nextcord.ButtonStyle.secondary)
    async def cancel(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.stop()
        await interaction.response.edit_message(content='Cancelled. Nothing was deleted.', embed=None, view=None)


class Privacy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _status_embed(self, user: nextcord.User | nextcord.Member | None) -> nextcord.Embed:
        stored = (
            await db.fetchval('SELECT presence_opt_in FROM users WHERE discord_id = $1', str(user.id)) if user else None
        )
        opted_in = stored is not False  # no row / never chose = allowed
        return await info_embed(
            title='Your privacy settings',
            description=(
                f'**Activity tracking:** {"allowed" if opted_in else "off (you opted out)"}\n\n{WHAT_IS_TRACKED}\n\n'
                '`/privacy optout` stops activity tracking for you; `/privacy optin` allows it again. '
                '`/privacy delete` erases your activity data and XP.'
            ),
            contributor_source=__name__,
        )

    async def _confirm_delete_embed(self) -> nextcord.Embed:
        return await veka_embed(
            title='Delete your activity data?',
            description=(
                'This permanently deletes your activity history (games, coding, streaming, daily stats, '
                'season placings) and resets your XP, level, streak and totals to zero. It cannot be undone.'
            ),
            contributor_source=__name__,
        )

    # ---------------------------------------------------------------- slash

    @nextcord.slash_command(name='privacy', description='Control what activity the bot tracks about you')
    @safe_slash_command(requires_db=True)
    async def privacy_group(self, interaction: nextcord.Interaction) -> None:
        await safe_send(interaction, embed=await self._status_embed(interaction.user), ephemeral=True)

    @privacy_group.subcommand(name='status', description='See what is tracked about you')
    @safe_slash_command(requires_db=True)
    async def privacy_status(self, interaction: nextcord.Interaction) -> None:
        await safe_send(interaction, embed=await self._status_embed(interaction.user), ephemeral=True)

    @privacy_group.subcommand(name='optin', description='Allow activity tracking for you again (after an opt-out)')
    @safe_slash_command(requires_db=True)
    async def privacy_optin(self, interaction: nextcord.Interaction) -> None:
        await set_presence_opt_in(self.bot, interaction.user.id, True)
        embed = await success_embed(
            'Activity tracking allowed',
            'In servers that enabled activity tracking, your games, coding apps and streaming time count again. '
            'Turn it off any time '
            'with `/privacy optout`.',
            contributor_source=__name__,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @privacy_group.subcommand(name='optout', description='Stop tracking your games, coding apps and streaming')
    @safe_slash_command(requires_db=True)
    async def privacy_optout(self, interaction: nextcord.Interaction) -> None:
        await set_presence_opt_in(self.bot, interaction.user.id, False)
        embed = await success_embed(
            'Activity tracking off',
            'Your games, coding apps and streaming time are no longer tracked or shown. '
            'Use `/privacy delete` to erase what was already recorded.',
            contributor_source=__name__,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @privacy_group.subcommand(name='delete', description='Delete your activity data and XP')
    @safe_slash_command(requires_db=True)
    async def privacy_delete(self, interaction: nextcord.Interaction) -> None:
        view = ConfirmDeleteView(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=await self._confirm_delete_embed(), view=view, ephemeral=True)

    # ---------------------------------------------------------------- prefix

    @commands.group(name='privacy', invoke_without_command=True)
    @safe_command(requires_db=True)
    async def privacy_prefix(self, ctx: commands.Context) -> None:
        await safe_send(ctx, embed=await self._status_embed(ctx.author))

    @privacy_prefix.command(name='status')
    @safe_command(requires_db=True)
    async def privacy_status_prefix(self, ctx: commands.Context) -> None:
        await safe_send(ctx, embed=await self._status_embed(ctx.author))

    @privacy_prefix.command(name='optin')
    @safe_command(requires_db=True)
    async def privacy_optin_prefix(self, ctx: commands.Context) -> None:
        await set_presence_opt_in(self.bot, ctx.author.id, True)
        await safe_send(ctx, '✅ Activity tracking is **allowed** for you again. `!privacy optout` turns it off.')

    @privacy_prefix.command(name='optout')
    @safe_command(requires_db=True)
    async def privacy_optout_prefix(self, ctx: commands.Context) -> None:
        await set_presence_opt_in(self.bot, ctx.author.id, False)
        await safe_send(ctx, '✅ Activity tracking is **off** for you.')

    @privacy_prefix.command(name='delete')
    @safe_command(requires_db=True)
    async def privacy_delete_prefix(self, ctx: commands.Context) -> None:
        view = ConfirmDeleteView(self.bot, ctx.author.id)
        await ctx.send(embed=await self._confirm_delete_embed(), view=view)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Privacy(bot))
    logger.info('Loaded cog: src.cogs.privacy')
