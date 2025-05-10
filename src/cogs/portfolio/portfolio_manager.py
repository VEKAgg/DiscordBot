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
                title="💼 Portfolio Commands",
                description="Showcase your projects and view others' work!",
                color=nextcord.Color.orange()
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
            await ctx.send("📝 What's the title of your project?")
            title_msg = await self.bot.wait_for('message', check=check, timeout=60)
            title = title_msg.content

            await ctx.send("📋 Please provide a description of your project:")
            desc_msg = await self.bot.wait_for('message', check=check, timeout=120)
            description = desc_msg.content

            await ctx.send("🔗 Enter the project URL (optional, type 'skip' to skip):")
            url_msg = await self.bot.wait_for('message', check=check, timeout=60)
            url = None
            if url_msg.content.lower() != 'skip':
                if validators.url(url_msg.content):
                    url = url_msg.content
                else:
                    await ctx.send("⚠️ Invalid URL format. URL will not be saved.")

            await ctx.send("🏷️ Enter project tags separated by commas (e.g., Python, Web, API):")
            tags_msg = await self.bot.wait_for('message', check=check, timeout=60)
            tags = [tag.strip() for tag in tags_msg.content.split(',') if tag.strip()]

            # Create project
            project_id = f"proj-{int(datetime.utcnow().timestamp())}"
            project = {
                "id": project_id,
                "title": title,
                "description": description,
                "url": url,
                "tags": tags,
                "user_id": str(ctx.author.id),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }

            # Save to database
            await self.db.insert_one(project)

            # Confirmation
            embed = nextcord.Embed(
                title="✅ Project Added",
                description=f"Your project **{title}** has been added to your portfolio!",
                color=nextcord.Color.orange()
            )
            embed.add_field(name="Description", value=description[:100] + "..." if len(description) > 100 else description, inline=False)
            if url:
                embed.add_field(name="URL", value=url, inline=False)
            if tags:
                embed.add_field(name="Tags", value=", ".join(tags), inline=False)
            embed.add_field(name="Project ID", value=f"`{project_id}`", inline=False)
            embed.add_field(name="View Command", value=f"`!portfolio view {project_id}`", inline=False)
            
            await ctx.send(embed=embed)
            
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Project creation timed out. Please try again.")

    @portfolio.command(name="list")
    async def portfolio_list(self, ctx, member: nextcord.Member = None):
        """List projects in a user's portfolio"""
        target_user = member or ctx.author
        
        # Find projects for the user
        projects = await self.db.find({"user_id": str(target_user.id)}).to_list(length=None)
        
        if not projects:
            if target_user == ctx.author:
                await ctx.send("📂 You don't have any projects in your portfolio yet. Use `!portfolio add` to add one!")
            else:
                await ctx.send(f"📂 {target_user.display_name} doesn't have any projects in their portfolio yet.")
            return
            
        embed = nextcord.Embed(
            title=f"💼 {target_user.display_name}'s Portfolio",
            description=f"Found {len(projects)} projects",
            color=nextcord.Color.orange()
        )
        
        for project in sorted(projects, key=lambda p: p["created_at"], reverse=True):
            # Format the project entry
            created_at = project["created_at"].strftime("%Y-%m-%d")
            tags = ", ".join([f"`{tag}`" for tag in project["tags"]]) if project["tags"] else "No tags"
            
            embed.add_field(
                name=f"📁 {project['title']}",
                value=f"**ID:** `{project['id']}`\n"
                      f"**Created:** {created_at}\n"
                      f"**Tags:** {tags}\n"
                      f"**View:** `!portfolio view {project['id']}`",
                inline=False
            )
            
        embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url)
        await ctx.send(embed=embed)

    @portfolio.command(name="view")
    async def portfolio_view(self, ctx, project_id: str):
        """View details of a specific project"""
        project = await self.db.find_one({"id": project_id})
        
        if not project:
            await ctx.send("❌ Project not found. Check the ID and try again.")
            return
            
        # Get the project owner
        owner_id = int(project["user_id"])
        owner = ctx.guild.get_member(owner_id) or await self.bot.fetch_user(owner_id)
        owner_name = owner.display_name if owner else "Unknown User"
        
        embed = nextcord.Embed(
            title=f"📂 {project['title']}",
            description=project["description"],
            color=nextcord.Color.orange()
        )
        
        if project.get("url"):
            embed.add_field(name="🔗 Project URL", value=project["url"], inline=False)
            
        if project.get("tags"):
            embed.add_field(name="🏷️ Tags", value=", ".join([f"`{tag}`" for tag in project["tags"]]), inline=False)
            
        created_at = project["created_at"].strftime("%Y-%m-%d")
        updated_at = project["updated_at"].strftime("%Y-%m-%d")
        
        embed.add_field(name="📅 Created", value=created_at, inline=True)
        embed.add_field(name="🔄 Updated", value=updated_at, inline=True)
        embed.add_field(name="👤 Owner", value=owner_name, inline=True)
        
        if owner and owner.avatar:
            embed.set_thumbnail(url=owner.avatar.url)
            
        await ctx.send(embed=embed)

    @portfolio.command(name="search")
    async def portfolio_search(self, ctx, *, query: str):
        """Search for projects by title, description, or tags"""
        # Create a case-insensitive search query
        search_query = {
            "$or": [
                {"title": {"$regex": query, "$options": "i"}},
                {"description": {"$regex": query, "$options": "i"}},
                {"tags": {"$regex": query, "$options": "i"}}
            ]
        }
        
        projects = await self.db.find(search_query).to_list(length=None)
        
        if not projects:
            await ctx.send(f"🔍 No projects found matching '{query}'.")
            return
            
        embed = nextcord.Embed(
            title="🔍 Search Results",
            description=f"Found {len(projects)} projects matching '{query}'",
            color=nextcord.Color.orange()
        )
        
        for project in projects[:10]:  # Limit to 10 results
            # Get the project owner
            owner_id = int(project["user_id"])
            owner = ctx.guild.get_member(owner_id) or await self.bot.fetch_user(owner_id)
            owner_name = owner.display_name if owner else "Unknown User"
            
            # Format the project entry
            tags = ", ".join([f"`{tag}`" for tag in project["tags"]]) if project["tags"] else "No tags"
            
            embed.add_field(
                name=f"📁 {project['title']}",
                value=f"**Owner:** {owner_name}\n"
                      f"**Description:** {project['description'][:100]}...\n"
                      f"**Tags:** {tags}\n"
                      f"**View:** `!portfolio view {project['id']}`",
                inline=False
            )
            
        if len(projects) > 10:
            embed.set_footer(text=f"Showing 10 of {len(projects)} results. Refine your search for more specific results.")
            
        await ctx.send(embed=embed)

def setup(bot):
    """Setup the PortfolioManager cog"""
    if bot is not None:
        bot.add_cog(PortfolioManager(bot))
        logging.getLogger('VEKA').info("Loaded cog: src.cogs.portfolio.portfolio_manager")
    else:
        logging.getLogger('VEKA').error("Bot is None in PortfolioManager cog setup")
