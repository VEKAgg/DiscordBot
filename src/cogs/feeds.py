import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import aiohttp
import asyncio
import feedparser
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import hashlib
import re

logger = logging.getLogger('VEKA.feeds')

class Feeds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.feeds = self.db.feeds
        self.feed_items = self.db.feed_items
        self.feed_subscriptions = self.db.feed_subscriptions
        self.feed_categories = {
            "tech": ["programming", "software", "technology", "development"],
            "career": ["jobs", "career", "professional", "workplace"],
            "industry": ["business", "startup", "enterprise", "innovation"]
        }
        self.update_feeds.start()

    def cog_unload(self):
        self.update_feeds.cancel()

    @tasks.loop(minutes=30)
    async def update_feeds(self):
        """Update all registered feeds"""
        try:
            async for feed in self.feeds.find({"active": True}):
                try:
                    await self.fetch_feed(feed)
                except Exception as e:
                    logger.error(f"Error updating feed {feed['url']}: {str(e)}")
                await asyncio.sleep(1)  # Rate limiting

        except Exception as e:
            logger.error(f"Error in feed update task: {str(e)}")

    async def fetch_feed(self, feed: Dict):
        """Fetch and process a single feed"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(feed["url"]) as response:
                    if response.status == 200:
                        content = await response.text()
                        parsed = feedparser.parse(content)

                        for entry in parsed.entries:
                            # Generate unique ID for entry
                            entry_id = hashlib.md5(
                                f"{feed['url']}{entry.get('id', entry.get('link', ''))}"
                                .encode()
                            ).hexdigest()

                            # Check if already exists
                            existing = await self.feed_items.find_one({"entry_id": entry_id})
                            if existing:
                                continue

                            # Clean and extract content
                            content = entry.get('content', [{'value': ''}])[0]['value']
                            if not content:
                                content = entry.get('summary', '')

                            soup = BeautifulSoup(content, 'html.parser')
                            clean_content = soup.get_text()

                            # Categorize content
                            categories = self.categorize_content(
                                f"{entry.get('title', '')} {clean_content}"
                            )

                            # Store new entry
                            item = {
                                "entry_id": entry_id,
                                "feed_id": str(feed["_id"]),
                                "title": entry.get('title'),
                                "link": entry.get('link'),
                                "author": entry.get('author'),
                                "content": clean_content[:1000],  # Truncate long content
                                "categories": categories,
                                "published": datetime(*entry.get('published_parsed')[:6])
                                if entry.get('published_parsed')
                                else datetime.utcnow(),
                                "created_at": datetime.utcnow()
                            }

                            await self.feed_items.insert_one(item)
                            await self.notify_subscribers(item)

        except Exception as e:
            logger.error(f"Error fetching feed: {str(e)}")
            raise

    def categorize_content(self, text: str) -> List[str]:
        """Categorize content based on keywords"""
        text = text.lower()
        categories = []

        for category, keywords in self.feed_categories.items():
            if any(keyword in text for keyword in keywords):
                categories.append(category)

        return categories

    async def notify_subscribers(self, item: Dict):
        """Notify subscribers of new content"""
        try:
            # Get feed info
            feed = await self.feeds.find_one({"_id": item["feed_id"]})
            if not feed:
                return

            # Get subscribers interested in these categories
            subscribers = await self.feed_subscriptions.find({
                "feed_id": str(feed["_id"]),
                "categories": {"$in": item["categories"]}
            }).to_list(length=None)

            embed = nextcord.Embed(
                title=item["title"],
                url=item["link"],
                description=item["content"][:200] + "...",
                color=nextcord.Color.blue(),
                timestamp=item["published"]
            )

            if item["author"]:
                embed.set_author(name=item["author"])

            embed.set_footer(text=f"Source: {feed['name']}")

            # Notify each subscriber
            for sub in subscribers:
                try:
                    user = self.bot.get_user(int(sub["user_id"]))
                    if user:
                        await user.send(embed=embed)
                except nextcord.Forbidden:
                    continue

        except Exception as e:
            logger.error(f"Error notifying subscribers: {str(e)}")

    @commands.group(invoke_without_command=True)
    async def feeds(self, ctx):
        """RSS feed management commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="📰 Feed Commands",
                description="Manage your content feeds",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!feeds list` - List available feeds
                `!feeds subscribe <feed> [categories]` - Subscribe to a feed
                `!feeds unsubscribe <feed>` - Unsubscribe from a feed
                `!feeds categories` - List available categories
                `!feeds digest` - Get your daily content digest
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @feeds.command(name="list")
    async def feeds_list(self, ctx):
        """List available feeds"""
        feeds = await self.feeds.find({"active": True}).to_list(length=None)
        if not feeds:
            await ctx.send("No feeds available!")
            return

        embed = nextcord.Embed(
            title="📚 Available Feeds",
            color=nextcord.Color.blue()
        )

        for feed in feeds:
            # Get subscriber count
            sub_count = await self.feed_subscriptions.count_documents({
                "feed_id": str(feed["_id"])
            })

            # Get user's subscription status
            user_sub = await self.feed_subscriptions.find_one({
                "feed_id": str(feed["_id"]),
                "user_id": str(ctx.author.id)
            })

            status = "✅ Subscribed" if user_sub else "❌ Not subscribed"
            categories = ", ".join(feed.get("categories", []))

            embed.add_field(
                name=feed["name"],
                value=f"""
                {feed["description"]}
                Categories: {categories}
                Subscribers: {sub_count}
                Status: {status}
                """,
                inline=False
            )

        await ctx.send(embed=embed)

    @feeds.command(name="subscribe")
    async def feeds_subscribe(self, ctx, feed_name: str, *categories):
        """Subscribe to a feed"""
        feed = await self.feeds.find_one({
            "name": feed_name,
            "active": True
        })

        if not feed:
            await ctx.send(f"❌ Feed not found: {feed_name}")
            return

        # Validate categories
        valid_categories = []
        for category in categories:
            if category in self.feed_categories:
                valid_categories.append(category)

        # Use all categories if none specified
        if not valid_categories:
            valid_categories = list(self.feed_categories.keys())

        # Create or update subscription
        await self.feed_subscriptions.update_one(
            {
                "user_id": str(ctx.author.id),
                "feed_id": str(feed["_id"])
            },
            {
                "$set": {
                    "categories": valid_categories,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )

        embed = nextcord.Embed(
            title="✅ Feed Subscribed",
            description=f"You've subscribed to: {feed['name']}",
            color=nextcord.Color.green()
        )
        embed.add_field(
            name="Categories",
            value=", ".join(valid_categories),
            inline=False
        )
        await ctx.send(embed=embed)

    @feeds.command(name="unsubscribe")
    async def feeds_unsubscribe(self, ctx, feed_name: str):
        """Unsubscribe from a feed"""
        feed = await self.feeds.find_one({"name": feed_name})
        if not feed:
            await ctx.send(f"❌ Feed not found: {feed_name}")
            return

        result = await self.feed_subscriptions.delete_one({
            "user_id": str(ctx.author.id),
            "feed_id": str(feed["_id"])
        })

        if result.deleted_count > 0:
            await ctx.send(f"✅ Unsubscribed from: {feed['name']}")
        else:
            await ctx.send(f"You weren't subscribed to: {feed['name']}")

    @feeds.command(name="categories")
    async def feeds_categories(self, ctx):
        """List available content categories"""
        embed = nextcord.Embed(
            title="📑 Content Categories",
            color=nextcord.Color.blue()
        )

        for category, keywords in self.feed_categories.items():
            embed.add_field(
                name=category.title(),
                value=f"Keywords: {', '.join(keywords)}",
                inline=False
            )

        await ctx.send(embed=embed)

    @feeds.command(name="digest")
    async def feeds_digest(self, ctx):
        """Get your daily content digest"""
        try:
            # Get user's subscriptions
            subscriptions = await self.feed_subscriptions.find({
                "user_id": str(ctx.author.id)
            }).to_list(length=None)

            if not subscriptions:
                await ctx.send("You're not subscribed to any feeds!")
                return

            # Get recent items from subscribed feeds
            day_ago = datetime.utcnow() - timedelta(days=1)
            items = await self.feed_items.find({
                "feed_id": {"$in": [str(s["feed_id"]) for s in subscriptions]},
                "published": {"$gte": day_ago}
            }).sort("published", -1).to_list(length=None)

            if not items:
                await ctx.send("No new content in your feeds today!")
                return

            # Group items by category
            categorized = {}
            for item in items:
                for category in item["categories"]:
                    if category not in categorized:
                        categorized[category] = []
                    categorized[category].append(item)

            # Create digest embed
            embed = nextcord.Embed(
                title="📰 Your Daily Digest",
                description="Here's what's new in your feeds:",
                color=nextcord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            for category, items in categorized.items():
                # Show top 3 items per category
                content = "\n\n".join([
                    f"[{item['title']}]({item['link']})"
                    for item in items[:3]
                ])
                if items:
                    embed.add_field(
                        name=f"{category.title()} ({len(items)} new items)",
                        value=content,
                        inline=False
                    )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error generating digest: {str(e)}")
            await ctx.send("❌ Error generating your digest. Please try again later.")

def setup(bot):
    """Setup the Feeds cog"""
    bot.add_cog(Feeds(bot))
    logger.info("Feeds cog loaded successfully")