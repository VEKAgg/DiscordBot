import nextcord
from nextcord.ext import commands, tasks
import logging
from src.services.rss_service import RSSService
from src.config.config import RSS_FEEDS
from typing import Optional

logger = logging.getLogger('VEKA.feeds')

class Feeds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rss_service = RSSService()
        self.feed_update.start()

    def cog_unload(self):
        self.feed_update.cancel()

    @tasks.loop(minutes=15)
    async def feed_update(self):
        """Periodically check for new feed entries and post updates"""
        try:
            for category in RSS_FEEDS:
                entries = await self.rss_service.get_latest_entries(category, limit=3)
                for guild in self.bot.guilds:
                    # Try to find an appropriate channel
                    channel = nextcord.utils.get(guild.text_channels, name=f"{category}-feed")
                    if not channel:
                        continue

                    for entry in entries:
                        embed = self.create_feed_embed(entry, category)
                        await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in feed update task: {str(e)}")

    @feed_update.before_loop
    async def before_feed_update(self):
        await self.bot.wait_until_ready()

    @commands.group(name="feed", invoke_without_command=True)
    async def feed(self, ctx):
        """RSS feed commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="RSS Feed Commands",
                description="Use these commands to interact with RSS feeds",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!feed list` - List available feed categories
                `!feed show <category>` - Show latest entries from a category
                `!feed search <query>` - Search across all feeds
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @feed.command(name="list")
    async def feed_list(self, ctx):
        """List available feed categories"""
        categories = self.rss_service.get_available_categories()
        
        embed = nextcord.Embed(
            title="Available Feed Categories",
            color=nextcord.Color.blue()
        )
        
        for category in categories:
            feed_count = len(RSS_FEEDS[category])
            embed.add_field(
                name=category.replace('_', ' ').title(),
                value=f"{feed_count} feed{'s' if feed_count != 1 else ''} available",
                inline=True
            )
            
        await ctx.send(embed=embed)

    @feed.command(name="show")
    async def feed_show(self, ctx, category: str, limit: int = 5):
        """Show latest entries from a category"""
        if category not in RSS_FEEDS:
            categories = ", ".join(RSS_FEEDS.keys())
            await ctx.send(f"❌ Invalid category. Available categories: {categories}")
            return

        try:
            entries = await self.rss_service.get_latest_entries(category, limit=limit)
            
            if not entries:
                await ctx.send(f"No entries found for category: {category}")
                return

            for entry in entries:
                embed = self.create_feed_embed(entry, category)
                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error showing feed entries: {str(e)}")
            await ctx.send("❌ An error occurred while fetching feed entries.")

    @feed.command(name="search")
    async def feed_search(self, ctx, *, query: str):
        """Search across all feeds"""
        try:
            results = await self.rss_service.search_feeds(query)
            
            if not results:
                await ctx.send(f"No results found for query: {query}")
                return

            for entry in results[:5]:  # Limit to 5 results
                embed = self.create_feed_embed(entry, "Search Results")
                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error searching feeds: {str(e)}")
            await ctx.send("❌ An error occurred while searching feeds.")

    def create_feed_embed(self, entry: dict, category: str) -> nextcord.Embed:
        """Create an embed for a feed entry"""
        embed = nextcord.Embed(
            title=entry['title'],
            url=entry['link'],
            description=entry['description'][:1000] + "..." if len(entry['description']) > 1000 else entry['description'],
            color=nextcord.Color.blue()
        )
        
        embed.add_field(name="Category", value=category.replace('_', ' ').title(), inline=True)
        embed.add_field(name="Author", value=entry['author'], inline=True)
        embed.add_field(name="Published", value=entry['published'], inline=True)
        
        return embed

def setup(bot):
    """Setup the Feeds cog"""
    bot.add_cog(Feeds(bot))
    return True 