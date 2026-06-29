import logging

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import RSS_FEEDS
from src.core.runtime_state import runtime_state
from src.services.rss_service import RSSService
from src.utils.embeds import error_embed, info_embed
from src.utils.safety import safe_background_task, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.feeds')


class Feeds(commands.Cog):
    @nextcord.slash_command(name='resource', description='Commands to browse community resources and RSS feeds')
    async def resource(self, interaction: nextcord.Interaction):
        pass

    def __init__(self, bot):
        self.bot = bot
        self.rss_service = RSSService(bot=bot)
        self.feed_update.start()

    def cog_unload(self):
        self.feed_update.cancel()

    @tasks.loop(minutes=15)
    @safe_background_task(name='feed_update')
    async def feed_update(self):
        """Periodically check for new feed entries and post updates"""
        if not runtime_state.db_available:
            logger.debug('Skipping feed update: database unavailable')
            return
        for category in RSS_FEEDS:
            # We fetch only the new entries, as deduplication is now persistent via DB
            entries = await self.rss_service.get_latest_new_entries(category, limit=3)
            if not entries:
                continue

            for guild in self.bot.guilds:
                channel = nextcord.utils.get(guild.text_channels, name=f'{category}-feed')
                if not channel:
                    continue

                for entry in entries:
                    embed = await self.create_feed_embed(entry, category)
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        logger.error('Failed to send feed to channel %s: %s', channel.name, e)

    @feed_update.before_loop
    async def before_feed_update(self):
        await self.bot.wait_until_ready()

    @resource.subcommand(name='sources', description='List available resource sources and categories')
    @safe_slash_command()
    async def feed_sources(self, interaction: nextcord.Interaction):
        categories = self.rss_service.get_available_categories()

        embed = await info_embed(
            title='Available Resource Categories',
            description='Here are the categories of feeds we track:',
            contributor_source=__name__,
            user=interaction.user,
        )

        for category in categories:
            feed_count = len(RSS_FEEDS[category])
            embed.add_field(
                name=category.replace('_', ' ').title(),
                value=f'{feed_count} feed source{"s" if feed_count != 1 else ""}',
                inline=True,
            )

        await safe_send(interaction, embed=embed)

    @resource.subcommand(name='latest', description='Show latest new entries from a category')
    @safe_slash_command()
    async def feed_latest(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(name='category', description='Category to fetch from', required=True),
    ):
        if category not in RSS_FEEDS:
            categories = ', '.join(RSS_FEEDS.keys())
            embed = await error_embed(
                'Invalid Category',
                f'Available categories: {categories}',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        # Just get some entries directly without marking them as deduplicated so users can view them repeatedly
        # We will bypass the `get_latest_new_entries` and just fetch
        entries = []
        for url in RSS_FEEDS[category]:
            feed_data = await self.rss_service.fetch_feed(url)
            if feed_data:
                entries.extend(feed_data['entries'])

        if not entries:
            embed = await info_embed(
                'No Entries Found',
                f'No entries found for category: {category}',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.followup.send(embed=embed)
            return

        entries = entries[:5]

        for idx, entry in enumerate(entries):
            embed = await self.create_feed_embed(entry, category)
            if idx == 0:
                await interaction.followup.send(embed=embed)
            else:
                await interaction.channel.send(embed=embed)

    async def create_feed_embed(self, entry: dict, category: str) -> nextcord.Embed:
        embed = await info_embed(
            title=entry['title'],
            description=entry['description'][:1000] + '...'
            if len(entry['description']) > 1000
            else entry['description'],
            contributor_source=__name__,
        )
        if entry.get('link') and entry['link'] != '#':
            embed.url = entry['link']

        embed.add_field(name='Category', value=category.replace('_', ' ').title(), inline=True)
        embed.add_field(name='Author', value=entry['author'], inline=True)
        embed.add_field(name='Published', value=entry['published'], inline=True)

        return embed


def setup(bot):
    bot.add_cog(Feeds(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.resources.feeds')
