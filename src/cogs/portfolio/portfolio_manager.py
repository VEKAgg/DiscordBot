import logging

import nextcord
from nextcord.ext import commands

from src.services import portfolio_service as portfolios
from src.utils.embed_limits import bounded_items, clip_text
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import ValidationError, safe_command, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.portfolio')


class PortfolioManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._pending_adds: set[tuple[int, int]] = set()

    @staticmethod
    def _actor(target):
        return target.user if isinstance(target, nextcord.Interaction) else target.author

    @staticmethod
    def _tags(tags, limit: int):
        return bounded_items([clip_text(tag, 40) for tag in tags if tag], limit) if tags else 'No tags'

    @staticmethod
    async def _defer(target):
        if isinstance(target, nextcord.Interaction) and not target.response.is_done():
            await target.response.defer(ephemeral=True)

    async def _help(self, target):
        embed = await info_embed(
            title='Portfolio Commands',
            description=(
                'Use `/portfolio` or `!portfolio`: **add**, **list**, **view**, **delete**, **search**.\n'
                'Five projects per page. Slash: `page` option. Prefix: `!portfolio list [@member] [page]` or '
                '`!portfolio search --page 2 query`.\n'
                'Projects remain globally discoverable, as before.'
            ),
            contributor_source=__name__,
            user=self._actor(target),
        )
        await safe_send(target, embed=embed, ephemeral=True)

    async def _add(self, target, title: str, description: str, url: str = '', tags: str = ''):
        await self._defer(target)
        row = await portfolios.add_project(self._actor(target).id, title, description, url, tags)
        embed = await success_embed(
            title='Project Added',
            description=f'**{row["title"]}** has been added to your portfolio!',
            contributor_source=__name__,
            user=self._actor(target),
        )
        if row['url']:
            embed.add_field(name='URL', value=row['url'], inline=False)
        if row['tags']:
            embed.add_field(name='Tags', value=', '.join(row['tags']), inline=False)
        embed.add_field(name='Project ID', value=f'`{row["id"]}`', inline=False)
        await safe_send(target, embed=embed, ephemeral=True)

    async def _show_page(self, target, rows, page: int, *, member=None, query: str | None = None):
        actor = self._actor(target)
        searching = query is not None
        name = clip_text(member.display_name, 100) if member else ''
        has_more = len(rows) > portfolios.PAGE_SIZE
        rows = rows[: portfolios.PAGE_SIZE]
        title = 'Search Results' if searching else f"{name}'s Portfolio"
        description = f'Page {page} · {len(rows)} project(s) on this page.'
        if searching:
            description += f'\nMatching: {clip_text(query, 200)}'
        if not rows:
            description += '\nNo projects on this page.'
        if has_more:
            if page < portfolios.MAX_PAGE:
                description += f'\nMore results: request page {page + 1}.'
            else:
                description += '\nPage limit reached; use a narrower search query.'
        embed = await info_embed(
            title=title,
            description=description,
            contributor_source=__name__,
            user=actor,
        )
        guild = target.guild
        for row in rows:
            tags = self._tags(row['tags'], 380)
            value = f'**ID:** `{clip_text(row["id"], 50)}`\n**Tags:** {tags}'
            if searching:
                owner = guild.get_member(int(row['owner_discord_id'])) if guild else None
                owner_name = clip_text(owner.display_name, 80) if owner else 'Unknown User'
                value += f'\n**Owner:** {owner_name}\n**Description:** {clip_text(row["description"], 200)}'
            else:
                created = row['created_at'].strftime('%Y-%m-%d') if row['created_at'] else 'Unknown'
                value += f'\n**Created:** {created}'
            embed.add_field(name=f'📁 {clip_text(row["title"], 200)}', value=clip_text(value, 850), inline=False)
        if member:
            embed.set_thumbnail(url=member.display_avatar.url)
        await safe_send(target, embed=embed, ephemeral=True)

    async def _list(self, target, member=None, page: int = 1):
        await self._defer(target)
        member = member or self._actor(target)
        rows = await portfolios.list_projects(member.id, page)
        await self._show_page(target, rows, page, member=member)

    async def _search(self, target, query: str, page: int = 1):
        await self._defer(target)
        rows = await portfolios.search_projects(query, page)
        await self._show_page(target, rows, page, query=query)

    async def _view(self, target, project_id: str):
        await self._defer(target)
        row = await portfolios.get_project(project_id)
        if not row:
            embed = await error_embed(
                'Not Found', 'Project not found.', contributor_source=__name__, user=self._actor(target)
            )
        else:
            owner = target.guild.get_member(int(row['owner_discord_id'])) if target.guild else None
            embed = await info_embed(
                title=f'📁 {clip_text(row["title"], 200)}',
                description=clip_text(row['description'], 3000) or 'No description provided.',
                contributor_source=__name__,
                user=self._actor(target),
            )
            if row.get('url'):
                embed.add_field(name='URL', value=clip_text(row['url'], 500), inline=False)
            if row.get('tags'):
                embed.add_field(
                    name='Tags',
                    value=self._tags(row['tags'], 450),
                    inline=False,
                )
            for label, key in [('Created', 'created_at'), ('Updated', 'updated_at')]:
                date = row[key].strftime('%Y-%m-%d') if row[key] else 'Unknown'
                embed.add_field(name=label, value=date, inline=True)
            embed.add_field(
                name='Owner', value=clip_text(owner.display_name, 80) if owner else 'Unknown User', inline=True
            )
        await safe_send(target, embed=embed, ephemeral=True)

    async def _delete(self, target, project_id: str):
        await self._defer(target)
        deleted = await portfolios.delete_project(self._actor(target).id, project_id)
        if deleted:
            embed = await success_embed(
                'Deleted', 'Project deleted.', contributor_source=__name__, user=self._actor(target)
            )
        else:
            embed = await error_embed(
                'Not Found',
                'Project not found or you do not own it.',
                contributor_source=__name__,
                user=self._actor(target),
            )
        await safe_send(target, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='portfolio', description='Showcase projects and view portfolios')
    async def portfolio(self, interaction: nextcord.Interaction):
        await self._help(interaction)

    @portfolio.subcommand(
        name='add', description='Add a project (title 200, description 3000 characters; up to 10 tags)'
    )
    @safe_slash_command(requires_db=True)
    async def portfolio_add_slash(
        self, interaction: nextcord.Interaction, title: str, description: str, url: str = '', tags: str = ''
    ):
        await self._add(interaction, title, description, url, tags)

    @portfolio.subcommand(name='list', description='List five projects per page')
    @safe_slash_command(requires_db=True)
    async def portfolio_list_slash(
        self, interaction: nextcord.Interaction, member: nextcord.Member = None, page: int = 1
    ):
        await self._list(interaction, member, page)

    @portfolio.subcommand(name='view', description='View project details')
    @safe_slash_command(requires_db=True)
    async def portfolio_view_slash(self, interaction: nextcord.Interaction, project_id: str):
        await self._view(interaction, project_id)

    @portfolio.subcommand(name='delete', description='Delete your project')
    @safe_slash_command(requires_db=True)
    async def portfolio_delete_slash(self, interaction: nextcord.Interaction, project_id: str):
        await self._delete(interaction, project_id)

    @portfolio.subcommand(name='search', description='Search projects, five per page')
    @safe_slash_command(requires_db=True)
    async def portfolio_search_slash(self, interaction: nextcord.Interaction, query: str, page: int = 1):
        await self._search(interaction, query, page)

    @commands.group(name='portfolio', invoke_without_command=True)
    async def portfolio_prefix(self, ctx):
        await self._help(ctx)

    @portfolio_prefix.command(name='add')
    @safe_command(requires_db=True)
    async def portfolio_add_prefix(self, ctx):
        key = (ctx.channel.id, ctx.author.id)
        if key in self._pending_adds:
            raise ValidationError('You already have a project creation prompt open in this channel.')
        self._pending_adds.add(key)
        try:

            def check(message):
                return message.author == ctx.author and message.channel == ctx.channel

            async def ask(prompt: str, timeout: int = 60):
                await safe_send(ctx, content=prompt)
                return (await self.bot.wait_for('message', check=check, timeout=timeout)).content

            title = await ask('Project title (up to 200 characters)?')
            description = await ask('Description (up to 3000 characters)?', 120)
            url = await ask("HTTP(S) project URL (up to 500 characters), or 'skip'?")
            tags = await ask('Up to 10 comma-separated tags (40 characters each)?')
            await self._add(ctx, title, description, '' if url.strip().lower() == 'skip' else url, tags)
        except TimeoutError:
            embed = await error_embed(
                'Timed Out',
                'Project creation timed out. Please try again.',
                contributor_source=__name__,
                user=ctx.author,
            )
            await safe_send(ctx, embed=embed)
        finally:
            self._pending_adds.discard(key)

    @portfolio_prefix.command(name='list')
    @safe_command(requires_db=True)
    async def portfolio_list_prefix(self, ctx, member: nextcord.Member | None = None, page: int = 1):
        await self._list(ctx, member, page)

    @portfolio_prefix.command(name='view')
    @safe_command(requires_db=True)
    async def portfolio_view_prefix(self, ctx, project_id: str):
        await self._view(ctx, project_id)

    @portfolio_prefix.command(name='delete')
    @safe_command(requires_db=True)
    async def portfolio_delete_prefix(self, ctx, project_id: str):
        await self._delete(ctx, project_id)

    @portfolio_prefix.command(name='search')
    @safe_command(requires_db=True)
    async def portfolio_search_prefix(self, ctx, *, query: str):
        page = 1
        if query.startswith('--page '):
            parts = query.split(maxsplit=2)
            if len(parts) != 3 or not parts[1].isdigit():
                raise ValidationError('Use `!portfolio search --page 2 your query`.')
            page, query = int(parts[1]), parts[2]
        await self._search(ctx, query, page)


def setup(bot):
    bot.add_cog(PortfolioManager(bot))
    logger.info('Loaded cog: src.cogs.portfolio.portfolio_manager')
