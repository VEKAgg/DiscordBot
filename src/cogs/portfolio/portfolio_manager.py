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

    @nextcord.slash_command(name="portfolio", description="Portfolio management commands")
    async def portfolio(self, interaction: nextcord.Interaction):
        """Portfolio management commands"""
        embed = nextcord.Embed(
            title="Portfolio Commands",
            description="Showcase your projects and view others' work!",
            color=nextcord.Color.blue()
        )
        embed.add_field(
            name="Available Commands",
            value="""
            `/portfolio add` - Add a new project
            `/portfolio list [@user]` - List your or someone's projects
            `/portfolio view <project_id>` - View project details
            `/portfolio edit <project_id>` - Edit a project
            `/portfolio delete <project_id>` - Delete a project
            `/portfolio search <query>` - Search projects
            """,
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @portfolio.subcommand(name="add", description="Add a new project to your portfolio")
    async def portfolio_add(self, interaction: nextcord.Interaction):
        """Add a new project to your portfolio"""
        try:
            def check(m):
                return m.author == interaction.user and m.channel == interaction.channel

            await interaction.response.send_message("Let's add a new project to your portfolio! I'll ask you a few questions.", ephemeral=True)

            # Get project details
            await interaction.followup.send("What's the title of your project?", ephemeral=True)
            title_msg = await self.bot.wait_for('message', check=check, timeout=60)
            title = title_msg.content

            await interaction.followup.send("Provide a description of your project:", ephemeral=True)
            desc_msg = await self.bot.wait_for('message', check=check, timeout=300)
            description = desc_msg.content

            await interaction.followup.send("What technologies/tools did you use? (comma-separated)", ephemeral=True)
            tech_msg = await self.bot.wait_for('message', check=check, timeout=60)
            technologies = [tech.strip() for tech in tech_msg.content.split(',')]

            await interaction.followup.send("Enter the project URL (optional, type 'skip' to skip):", ephemeral=True)
            url_msg = await self.bot.wait_for('message', check=check, timeout=60)
            url = None if url_msg.content.lower() == 'skip' else url_msg.content

            if url and not validators.url(url):
                await interaction.followup.send("❌ Invalid URL provided. Project will be created without a URL.", ephemeral=True)
                url = None

            # Create project
            project = {
                'user_id': str(interaction.user.id),
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

            await interaction.followup.send(embed=embed)

        except asyncio.TimeoutError:
            await interaction.followup.send("❌ Project creation timed out. Please try again.", ephemeral=True)

    @portfolio.subcommand(name="list", description="List projects in a user's portfolio")
    async def portfolio_list(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member = nextcord.SlashOption(
            name="member",
            description="The member whose portfolio to view (defaults to yourself)",
            required=False
        )
    ):
        """List projects in a user's portfolio"""
        target = member or interaction.user
        
        projects = await self.db.find({'user_id': str(target.id)}).to_list(length=None)
        
        if not projects:
            if target == interaction.user:
                await interaction.response.send_message("You haven't added any projects yet! Use `/portfolio add` to add one.", ephemeral=True)
            else:
                await interaction.response.send_message(f"{target.display_name} hasn't added any projects yet.", ephemeral=True)
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

        await interaction.response.send_message(embed=embed)

    @portfolio.subcommand(name="view", description="View detailed information about a project")
    async def portfolio_view(
        self,
        interaction: nextcord.Interaction,
        project_id: str = nextcord.SlashOption(
            name="project_id",
            description="The ID of the project to view",
            required=True
        )
    ):
        """View detailed information about a project"""
        try:
            project = await self.db.find_one({'_id': project_id})
            if not project:
                await interaction.response.send_message("❌ Project not found.", ephemeral=True)
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

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error viewing project: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while viewing the project.", ephemeral=True)

    @portfolio.subcommand(name="search", description="Search for projects by title, description, or technologies")
    async def portfolio_search(
        self,
        interaction: nextcord.Interaction,
        query: str = nextcord.SlashOption(
            name="query",
            description="The search query",
            required=True
        )
    ):
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
                await interaction.response.send_message("No projects found matching your search.", ephemeral=True)
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

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error searching projects: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while searching projects.", ephemeral=True)

def setup(bot):
    """Setup the PortfolioManager cog"""
    if bot is not None:
        bot.add_cog(PortfolioManager(bot))
        logging.getLogger('VEKA').info("PortfolioManager cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in PortfolioManager cog setup")
