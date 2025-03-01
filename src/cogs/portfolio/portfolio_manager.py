import asyncio
import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime
from typing import Dict, List, Optional
import json
import aiohttp
import validators

logger = logging.getLogger('VEKA.portfolio')

class PortfolioManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db.portfolios

    @commands.group(name="portfolio", invoke_without_command=True)
    async def portfolio(self, ctx):
        """Portfolio management commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="Portfolio Commands",
                description="Showcase your projects and view others' work!",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!portfolio add` - Add a new project
                `!portfolio list [@user]` - List your or someone's projects
                `!portfolio view <project_id>` - View project details
                `!portfolio edit <project_id>` - Edit a project
                `!portfolio delete <project_id>` - Delete a project
                `!portfolio search <query>` - Search projects
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @portfolio.command(name="add")
    async def portfolio_add(self, ctx):
        """Add a new project to your portfolio"""
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            # Get project details
            await ctx.send("What's the title of your project?")
            title_msg = await self.bot.wait_for('message', check=check, timeout=60)
            title = title_msg.content

            await ctx.send("Provide a description of your project:")
            desc_msg = await self.bot.wait_for('message', check=check, timeout=300)
            description = desc_msg.content

            await ctx.send("What technologies/tools did you use? (comma-separated)")
            tech_msg = await self.bot.wait_for('message', check=check, timeout=60)
            technologies = [tech.strip() for tech in tech_msg.content.split(',')]

            await ctx.send("Enter the project URL (optional, type 'skip' to skip):")
            url_msg = await self.bot.wait_for('message', check=check, timeout=60)
            url = None if url_msg.content.lower() == 'skip' else url_msg.content

            if url and not validators.url(url):
                await ctx.send("❌ Invalid URL provided. Project will be created without a URL.")
                url = None

            # Create project
            project = {
                'user_id': str(ctx.author.id),
                'title': title,
                'description': description,
                'technologies': technologies,
                'url': url,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'likes': 0,
                'views': 0
            }

            result = await self.db.insert_one(project)
            project['_id'] = result.inserted_id

            # Create confirmation embed
            embed = nextcord.Embed(
                title="✅ Project Added Successfully!",
                description=f"**{title}** has been added to your portfolio.",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Technologies", value=', '.join(technologies), inline=False)
            if url:
                embed.add_field(name="URL", value=url, inline=False)
            embed.set_footer(text=f"Project ID: {result.inserted_id}")

            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("❌ Project creation timed out. Please try again.")

    @portfolio.command(name="list")
    async def portfolio_list(self, ctx, member: nextcord.Member = None):
        """List projects in a user's portfolio"""
        target = member or ctx.author
        
        projects = await self.db.find({'user_id': str(target.id)}).to_list(length=None)
        
        if not projects:
            if target == ctx.author:
                await ctx.send("You haven't added any projects yet! Use `!portfolio add` to add one.")
            else:
                await ctx.send(f"{target.display_name} hasn't added any projects yet.")
            return

        embed = nextcord.Embed(
            title=f"{target.display_name}'s Portfolio",
            description=f"Found {len(projects)} project(s)",
            color=nextcord.Color.blue()
        )

        for project in projects:
            embed.add_field(
                name=f"📁 {project['title']}",
                value=f"""
                {project['description'][:100]}...
                🔧 {', '.join(project['technologies'][:3])}
                ❤️ {project['likes']} likes | 👀 {project['views']} views
                ID: {project['_id']}
                """,
                inline=False
            )

        await ctx.send(embed=embed)

    @portfolio.command(name="view")
    async def portfolio_view(self, ctx, project_id: str):
        """View detailed information about a project"""
        try:
            project = await self.db.find_one({'_id': project_id})
            if not project:
                await ctx.send("❌ Project not found.")
                return

            # Increment view count
            await self.db.update_one(
                {'_id': project_id},
                {'$inc': {'views': 1}}
            )

            # Get project owner
            owner = await self.bot.fetch_user(int(project['user_id']))
            owner_name = owner.display_name if owner else "Unknown User"

            embed = nextcord.Embed(
                title=project['title'],
                description=project['description'],
                color=nextcord.Color.blue()
            )
            embed.set_author(name=f"Project by {owner_name}")
            embed.add_field(name="Technologies", value=', '.join(project['technologies']), inline=False)
            if project.get('url'):
                embed.add_field(name="Project URL", value=project['url'], inline=False)
            embed.add_field(name="Stats", value=f"❤️ {project['likes']} likes | 👀 {project['views']} views")
            embed.set_footer(text=f"Created: {project['created_at'].strftime('%Y-%m-%d')}")

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error viewing project: {str(e)}")
            await ctx.send("❌ An error occurred while viewing the project.")

    @portfolio.command(name="search")
    async def portfolio_search(self, ctx, *, query: str):
        """Search for projects by title, description, or technologies"""
        try:
            # Create text index if it doesn't exist
            await self.db.create_index([
                ('title', 'text'),
                ('description', 'text'),
                ('technologies', 'text')
            ])

            # Perform search
            projects = await self.db.find(
                {'$text': {'$search': query}},
                {'score': {'$meta': 'textScore'}}
            ).sort([('score', {'$meta': 'textScore'})]).limit(5).to_list(length=None)

            if not projects:
                await ctx.send("No projects found matching your search.")
                return

            embed = nextcord.Embed(
                title="🔍 Search Results",
                description=f"Found {len(projects)} project(s) matching '{query}'",
                color=nextcord.Color.blue()
            )

            for project in projects:
                owner = await self.bot.fetch_user(int(project['user_id']))
                owner_name = owner.display_name if owner else "Unknown User"
                
                embed.add_field(
                    name=f"📁 {project['title']}",
                    value=f"""
                    By: {owner_name}
                    {project['description'][:100]}...
                    🔧 {', '.join(project['technologies'][:3])}
                    ID: {project['_id']}
                    """,
                    inline=False
                )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error searching projects: {str(e)}")
            await ctx.send("❌ An error occurred while searching projects.")

async def setup(bot):
    """Setup the PortfolioManager cog"""
    if bot is not None:
        await bot.add_cog(PortfolioManager(bot))
        logging.getLogger('VEKA').info("PortfolioManager cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in PortfolioManager cog setup")
