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

    @nextcord.slash_command(name="feed", description="RSS feed commands")
    async def feed(self, interaction: nextcord.Interaction):
        """RSS feed commands"""
        embed = nextcord.Embed(
            title="RSS Feed Commands",
            description="Use these commands to interact with RSS feeds",
            color=nextcord.Color.blue()
        )
        embed.add_field(
            name="Available Commands",
            value="""
            `/feed list` - List available feed categories
            `/feed show <category>` - Show latest entries from a category
            `/feed search <query>` - Search across all feeds
            """,
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    @feed.subcommand(name="list", description="List available feed categories")
    async def feed_list(self, interaction: nextcord.Interaction):
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
            
        await interaction.response.send_message(embed=embed)

    @feed.subcommand(name="show", description="Show latest entries from a category")
    async def feed_show(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            name="category",
            description="The category of the feed to show",
            required=True,
            choices=[{"name": cat.replace('_', ' ').title(), "value": cat} for cat in RSS_FEEDS.keys()]
        ),
        limit: int = nextcord.SlashOption(
            name="limit",
            description="The number of entries to show (default: 5)",
            required=False,
            default=5,
            min_value=1,
            max_value=10
        )
    ):
        """Show latest entries from a category"""
        if category not in RSS_FEEDS:
            categories = ", ".join(RSS_FEEDS.keys())
            await interaction.response.send_message(f"❌ Invalid category. Available categories: {categories}", ephemeral=True)
            return

        try:
            entries = await self.rss_service.get_latest_entries(category, limit=limit)
            
            if not entries:
                await interaction.response.send_message(f"No entries found for category: {category}", ephemeral=True)
                return

            # Send the first embed as the initial response, then use followup for the rest
            if entries:
                first_embed = self.create_feed_embed(entries[0], category)
                await interaction.response.send_message(embed=first_embed)
                for entry in entries[1:]:
                    embed = self.create_feed_embed(entry, category)
                    await interaction.followup.send(embed=embed)
            else:
                await interaction.response.send_message(f"No entries found for category: {category}", ephemeral=True)


        except Exception as e:
            logger.error(f"Error showing feed entries: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while fetching feed entries.", ephemeral=True)

    @feed.subcommand(name="search", description="Search across all feeds")
    async def feed_search(
        self,
        interaction: nextcord.Interaction,
        query: str = nextcord.SlashOption(
            name="query",
            description="The search query",
            required=True
        )
    ):
        """Search across all feeds"""
        try:
            results = await self.rss_service.search_feeds(query)
            
            if not results:
                await interaction.response.send_message(f"No results found for query: {query}", ephemeral=True)
                return

            # Send the first embed as the initial response, then use followup for the rest
            if results:
                first_embed = self.create_feed_embed(results[0], "Search Results")
                await interaction.response.send_message(embed=first_embed)
                for entry in results[1:5]:  # Limit to 5 results
                    embed = self.create_feed_embed(entry, "Search Results")
                    await interaction.followup.send(embed=embed)
            else:
                await interaction.response.send_message(f"No results found for query: {query}", ephemeral=True)


        except Exception as e:
            logger.error(f"Error searching feeds: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while searching feeds.", ephemeral=True)

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
    if bot is not None:
        bot.add_cog(Feeds(bot))
        logging.getLogger('VEKA').info("Feeds cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Feeds cog setup") 