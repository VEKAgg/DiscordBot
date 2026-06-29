import logging
from datetime import datetime

import nextcord
import validators
from nextcord.ext import commands

from src.database.database import db, get_or_create_user
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_send, safe_slash_command

logger = logging.getLogger('VEKA.portfolio')


class PortfolioManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==================== SLASH COMMANDS ====================

    @nextcord.slash_command(name='portfolio', description='Showcase your projects and view others work')
    async def portfolio(self, interaction: nextcord.Interaction):
        pass

    @portfolio.subcommand(name='add', description='Add a new project to your portfolio')
    @safe_slash_command(requires_db=True)
    async def portfolio_add_slash(
        self,
        interaction: nextcord.Interaction,
        title: str,
        description: str,
        url: str = '',
        tags: str = '',
    ):
        try:
            project_url = None
            if url:
                if validators.url(url):
                    project_url = url
                else:
                    embed = error_embed(
                        'Invalid URL', 'Invalid URL — project will be saved without a URL.', contributor_source=__name__
                    )
                    await safe_send(interaction, embed=embed, ephemeral=True)

            tag_list = [t.strip() for t in tags.split(',') if t.strip()] if tags else []

            project_id = f'proj-{int(datetime.utcnow().timestamp())}'
            user = await get_or_create_user(str(interaction.user.id))

            await db.execute(
                'INSERT INTO portfolios (id, user_id, title, description, url, tags) VALUES ($1, $2, $3, $4, $5, $6)',
                project_id,
                user['id'],
                title,
                description,
                project_url,
                tag_list,
            )

            embed = success_embed(
                title='Project Added',
                description=f'**{title}** has been added to your portfolio!',
                contributor_source=__name__,
            )
            if project_url:
                embed.add_field(name='URL', value=project_url, inline=False)
            if tag_list:
                embed.add_field(name='Tags', value=', '.join(tag_list), inline=False)
            embed.add_field(name='Project ID', value=f'`{project_id}`', inline=False)
            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Portfolio add error: {str(e)}')
            embed = error_embed('Add Error', 'An error occurred while adding the project.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @portfolio.subcommand(name='list', description='List projects for yourself or another member')
    @safe_slash_command(requires_db=True)
    async def portfolio_list_slash(self, interaction: nextcord.Interaction, member: nextcord.Member = None):
        target = member or interaction.user
        user = await get_or_create_user(str(target.id))
        rows = await db.fetch_many('SELECT * FROM portfolios WHERE user_id = $1 ORDER BY created_at DESC', user['id'])

        if not rows:
            msg = (
                "You don't have any projects yet. Use `/portfolio add` to add one!"
                if target == interaction.user
                else f'{target.display_name} has no projects yet.'
            )
            embed = info_embed(title='No Projects', description=msg, contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = info_embed(
            title=f"💼 {target.display_name}'s Portfolio",
            description=f'{len(rows)} projects',
            contributor_source=__name__,
        )
        for p in rows:
            tag_str = ', '.join([f'`{t}`' for t in (p['tags'] or [])]) or 'No tags'
            embed.add_field(
                name=f'📁 {p["title"]}',
                value=(
                    f'**ID:** `{p["id"]}`\n**Created:** {p["created_at"].strftime("%Y-%m-%d")}\n**Tags:** {tag_str}'
                ),
                inline=False,
            )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        await safe_send(interaction, embed=embed, ephemeral=True)

    @portfolio.subcommand(name='view', description='View project details')
    @safe_slash_command(requires_db=True)
    async def portfolio_view_slash(self, interaction: nextcord.Interaction, project_id: str):
        row = await db.fetch_one('SELECT * FROM portfolios WHERE id = $1', project_id)
        if not row:
            embed = error_embed('Not Found', 'Project not found.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        owner_row = await db.fetch_one('SELECT discord_id FROM users WHERE id = $1', row['user_id'])
        owner = interaction.guild.get_member(int(owner_row['discord_id'])) if owner_row else None
        owner_name = owner.display_name if owner else 'Unknown User'

        embed = info_embed(title=f'📁 {row["title"]}', description=row['description'], contributor_source=__name__)
        if row.get('url'):
            embed.add_field(name='🔗 URL', value=row['url'], inline=False)
        if row.get('tags'):
            embed.add_field(name='🏷️ Tags', value=', '.join([f'`{t}`' for t in row['tags']]), inline=False)
        embed.add_field(name='📅 Created', value=row['created_at'].strftime('%Y-%m-%d'), inline=True)
        embed.add_field(name='🔄 Updated', value=row['updated_at'].strftime('%Y-%m-%d'), inline=True)
        embed.add_field(name='👤 Owner', value=owner_name, inline=True)
        if owner and owner.avatar:
            embed.set_thumbnail(url=owner.avatar.url)
        await safe_send(interaction, embed=embed, ephemeral=True)

    @portfolio.subcommand(name='delete', description='Delete a project from your portfolio')
    @safe_slash_command(requires_db=True)
    async def portfolio_delete_slash(self, interaction: nextcord.Interaction, project_id: str):
        user = await get_or_create_user(str(interaction.user.id))
        result = await db.execute('DELETE FROM portfolios WHERE id = $1 AND user_id = $2', project_id, user['id'])
        if result == 'DELETE 1':
            embed = success_embed(
                title='Deleted', description=f'Project `{project_id}` deleted.', contributor_source=__name__
            )
        else:
            embed = error_embed('Not Found', 'Project not found or you do not own it.', contributor_source=__name__)
        await safe_send(interaction, embed=embed, ephemeral=True)

    @portfolio.subcommand(name='search', description='Search projects by title, description, or tags')
    @safe_slash_command(requires_db=True)
    async def portfolio_search_slash(self, interaction: nextcord.Interaction, query: str):
        rows = await db.fetch_many(
            """
            SELECT p.*, u.discord_id AS owner_discord_id
              FROM portfolios p
              JOIN users u ON u.id = p.user_id
             WHERE to_tsvector('english', p.title || ' ' || p.description) @@ plainto_tsquery('english', $1)
                OR $1 = ANY(p.tags)
             LIMIT 10
            """,
            query,
        )
        if not rows:
            embed = info_embed(
                title='No Results', description=f"No projects found matching '{query}'.", contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = info_embed(
            title='🔍 Search Results',
            description=f"{len(rows)} projects matching '{query}'",
            contributor_source=__name__,
        )
        for p in rows:
            owner = interaction.guild.get_member(int(p['owner_discord_id']))
            owner_name = owner.display_name if owner else 'Unknown User'
            tag_str = ', '.join([f'`{t}`' for t in (p['tags'] or [])]) or 'No tags'
            desc = p['description']
            embed.add_field(
                name=f'📁 {p["title"]}',
                value=(
                    f'**Owner:** {owner_name}\n'
                    f'**Description:** {desc[:100]}{"..." if len(desc) > 100 else ""}\n'
                    f'**Tags:** {tag_str}'
                ),
                inline=False,
            )
        await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== PREFIX COMMANDS ====================

    @commands.group(name='portfolio', invoke_without_command=True)
    async def portfolio_prefix(self, ctx):
        embed = info_embed(
            title='💼 Portfolio Commands',
            description="Showcase your projects and view others' work! Use `/portfolio` for the best experience.",
            contributor_source=__name__,
        )
        embed.add_field(
            name='Available Commands',
            inline=False,
            value=(
                '`!portfolio add` - Add a new project\n'
                '`!portfolio list [@user]` - List projects\n'
                '`!portfolio view <id>` - View project details\n'
                '`!portfolio delete <id>` - Delete your project\n'
                '`!portfolio search <query>` - Search projects'
            ),
        )
        await ctx.send(embed=embed)

    @portfolio_prefix.command(name='add')
    async def portfolio_add_prefix(self, ctx):
        try:

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            await ctx.send("📝 What's the title of your project?")
            title = (await self.bot.wait_for('message', check=check, timeout=60)).content

            await ctx.send('📋 Provide a description:')
            description = (await self.bot.wait_for('message', check=check, timeout=120)).content

            await ctx.send("🔗 Project URL? (type 'skip' to skip)")
            url_resp = (await self.bot.wait_for('message', check=check, timeout=60)).content
            url = None
            if url_resp.lower() != 'skip':
                if validators.url(url_resp):
                    url = url_resp
                else:
                    await ctx.send('⚠️ Invalid URL — project will be saved without a URL.')

            await ctx.send('🏷️ Tags (comma-separated, e.g. Python, Web, API):')
            tags_raw = (await self.bot.wait_for('message', check=check, timeout=60)).content
            tag_list = [t.strip() for t in tags_raw.split(',') if t.strip()]

            project_id = f'proj-{int(datetime.utcnow().timestamp())}'
            user = await get_or_create_user(str(ctx.author.id))

            await db.execute(
                'INSERT INTO portfolios (id, user_id, title, description, url, tags) VALUES ($1, $2, $3, $4, $5, $6)',
                project_id,
                user['id'],
                title,
                description,
                url,
                tag_list,
            )

            embed = nextcord.Embed(
                title='✅ Project Added',
                description=f'**{title}** has been added to your portfolio!',
                color=nextcord.Color.orange(),
            )
            if url:
                embed.add_field(name='URL', value=url, inline=False)
            if tag_list:
                embed.add_field(name='Tags', value=', '.join(tag_list), inline=False)
            embed.add_field(name='Project ID', value=f'`{project_id}`', inline=False)
            embed.add_field(name='View', value=f'`!portfolio view {project_id}`', inline=False)
            await ctx.send(embed=embed)

        except TimeoutError:
            await ctx.send('⏱️ Project creation timed out. Please try again.')

    @portfolio_prefix.command(name='list')
    async def portfolio_list_prefix(self, ctx, member: nextcord.Member = None):
        target = member or ctx.author
        user = await get_or_create_user(str(target.id))
        rows = await db.fetch_many('SELECT * FROM portfolios WHERE user_id = $1 ORDER BY created_at DESC', user['id'])

        if not rows:
            msg = (
                "You don't have any projects yet. Use `!portfolio add` to add one!"
                if target == ctx.author
                else f'{target.display_name} has no projects yet.'
            )
            await ctx.send(f'📂 {msg}')
            return

        embed = nextcord.Embed(
            title=f"💼 {target.display_name}'s Portfolio",
            description=f'{len(rows)} projects',
            color=nextcord.Color.orange(),
        )
        for p in rows:
            tags = ', '.join([f'`{t}`' for t in (p['tags'] or [])]) or 'No tags'
            embed.add_field(
                name=f'📁 {p["title"]}',
                value=(
                    f'**ID:** `{p["id"]}`\n'
                    f'**Created:** {p["created_at"].strftime("%Y-%m-%d")}\n'
                    f'**Tags:** {tags}\n'
                    f'**View:** `!portfolio view {p["id"]}`'
                ),
                inline=False,
            )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        await ctx.send(embed=embed)

    @portfolio_prefix.command(name='view')
    async def portfolio_view_prefix(self, ctx, project_id: str):
        row = await db.fetch_one('SELECT * FROM portfolios WHERE id = $1', project_id)
        if not row:
            await ctx.send('❌ Project not found.')
            return

        owner_row = await db.fetch_one('SELECT discord_id FROM users WHERE id = $1', row['user_id'])
        owner = ctx.guild.get_member(int(owner_row['discord_id'])) if owner_row else None
        owner_name = owner.display_name if owner else 'Unknown User'

        embed = nextcord.Embed(
            title=f'📂 {row["title"]}', description=row['description'], color=nextcord.Color.orange()
        )
        if row.get('url'):
            embed.add_field(name='🔗 URL', value=row['url'], inline=False)
        if row.get('tags'):
            embed.add_field(name='🏷️ Tags', value=', '.join([f'`{t}`' for t in row['tags']]), inline=False)
        embed.add_field(name='📅 Created', value=row['created_at'].strftime('%Y-%m-%d'), inline=True)
        embed.add_field(name='🔄 Updated', value=row['updated_at'].strftime('%Y-%m-%d'), inline=True)
        embed.add_field(name='👤 Owner', value=owner_name, inline=True)
        if owner and owner.avatar:
            embed.set_thumbnail(url=owner.avatar.url)
        await ctx.send(embed=embed)

    @portfolio_prefix.command(name='delete')
    async def portfolio_delete_prefix(self, ctx, project_id: str):
        user = await get_or_create_user(str(ctx.author.id))
        result = await db.execute('DELETE FROM portfolios WHERE id = $1 AND user_id = $2', project_id, user['id'])
        if result == 'DELETE 1':
            await ctx.send(f'✅ Project `{project_id}` deleted.')
        else:
            await ctx.send('❌ Project not found or you do not own it.')

    @portfolio_prefix.command(name='search')
    async def portfolio_search_prefix(self, ctx, *, query: str):
        rows = await db.fetch_many(
            """
            SELECT p.*, u.discord_id AS owner_discord_id
              FROM portfolios p
              JOIN users u ON u.id = p.user_id
             WHERE to_tsvector('english', p.title || ' ' || p.description) @@ plainto_tsquery('english', $1)
                OR $1 = ANY(p.tags)
             LIMIT 10
            """,
            query,
        )
        if not rows:
            await ctx.send(f"🔍 No projects found matching '{query}'.")
            return

        embed = nextcord.Embed(
            title='🔍 Search Results',
            description=f"{len(rows)} projects matching '{query}'",
            color=nextcord.Color.orange(),
        )
        for p in rows:
            owner = ctx.guild.get_member(int(p['owner_discord_id']))
            owner_name = owner.display_name if owner else 'Unknown User'
            tags = ', '.join([f'`{t}`' for t in (p['tags'] or [])]) or 'No tags'
            desc = p['description']
            embed.add_field(
                name=f'📁 {p["title"]}',
                value=(
                    f'**Owner:** {owner_name}\n'
                    f'**Description:** {desc[:100]}{"..." if len(desc) > 100 else ""}\n'
                    f'**Tags:** {tags}\n'
                    f'**View:** `!portfolio view {p["id"]}`'
                ),
                inline=False,
            )
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(PortfolioManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.portfolio.portfolio_manager')
