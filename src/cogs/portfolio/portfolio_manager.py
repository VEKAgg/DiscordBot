import logging
from datetime import datetime

import nextcord
import validators
from nextcord.ext import commands

from src.database.database import db, get_or_create_user

logger = logging.getLogger('VEKA.portfolio')


class PortfolioManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='portfolio', invoke_without_command=True)
    async def portfolio(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title='💼 Portfolio Commands',
                description="Showcase your projects and view others' work!",
                color=nextcord.Color.orange(),
            )
            embed.add_field(
                name='Available Commands',
                inline=False,
                value=(
                    '`!portfolio add` - Add a new project\n'
                    '`!portfolio list [@user]` - List projects\n'
                    '`!portfolio view <id>` - View project details\n'
                    '`!portfolio delete <id>` - Delete your project\n'
                    '`!portfolio search <query>` - Search projects\n'
                ),
            )
            await ctx.send(embed=embed)

    @portfolio.command(name='add')
    async def portfolio_add(self, ctx):
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
            tags = [t.strip() for t in tags_raw.split(',') if t.strip()]

            project_id = f'proj-{int(datetime.utcnow().timestamp())}'
            user = await get_or_create_user(str(ctx.author.id))

            await db.execute(
                """
                INSERT INTO portfolios (id, user_id, title, description, url, tags)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                project_id,
                user['id'],
                title,
                description,
                url,
                tags,
            )

            embed = nextcord.Embed(
                title='✅ Project Added',
                description=f'**{title}** has been added to your portfolio!',
                color=nextcord.Color.orange(),
            )
            if url:
                embed.add_field(name='URL', value=url, inline=False)
            if tags:
                embed.add_field(name='Tags', value=', '.join(tags), inline=False)
            embed.add_field(name='Project ID', value=f'`{project_id}`', inline=False)
            embed.add_field(name='View', value=f'`!portfolio view {project_id}`', inline=False)
            await ctx.send(embed=embed)

        except TimeoutError:
            await ctx.send('⏱️ Project creation timed out. Please try again.')

    @portfolio.command(name='list')
    async def portfolio_list(self, ctx, member: nextcord.Member = None):
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

    @portfolio.command(name='view')
    async def portfolio_view(self, ctx, project_id: str):
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

    @portfolio.command(name='delete')
    async def portfolio_delete(self, ctx, project_id: str):
        user = await get_or_create_user(str(ctx.author.id))
        result = await db.execute('DELETE FROM portfolios WHERE id = $1 AND user_id = $2', project_id, user['id'])
        if result == 'DELETE 1':
            await ctx.send(f'✅ Project `{project_id}` deleted.')
        else:
            await ctx.send('❌ Project not found or you do not own it.')

    @portfolio.command(name='search')
    async def portfolio_search(self, ctx, *, query: str):
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
