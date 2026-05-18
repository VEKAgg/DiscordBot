import feedparser
import aiohttp
import asyncio
from datetime import datetime, timedelta
import logging
from bs4 import BeautifulSoup
from src.config.config import RSS_FEEDS, RATE_LIMITS, CACHE_TTL
from src.database.mongodb import rss_cache
from typing import Dict, List, Optional

logger = logging.getLogger('VEKA.rss')


class RSSService:
    def __init__(self):
        self.last_fetch: Dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_cached(self, url: str) -> Optional[Dict]:
        """Return cached feed data for *url* if it has not expired."""
        doc = await rss_cache.find_one({'feed_url': url})
        if doc and doc.get('data'):
            return doc['data']
        return None

    async def _set_cache(self, url: str, data: Dict) -> None:
        """Persist feed data in MongoDB; TTL index handles expiry."""
        ttl_seconds = CACHE_TTL.get('rss_feed', 3600)
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        await rss_cache.update_one(
            {'feed_url': url},
            {'$set': {
                'feed_url': url,
                'data': data,
                'cached_at': datetime.utcnow(),
                'expires_at': expires_at,
            }},
            upsert=True
        )

    async def _get_last_posted(self, url: str) -> Optional[str]:
        """Return the link of the last entry that was posted for *url*."""
        doc = await rss_cache.find_one({'feed_url': url})
        return doc.get('last_posted') if doc else None

    async def set_last_posted(self, url: str, entry_link: str) -> None:
        """Record the most recently posted entry link for *url*."""
        await rss_cache.update_one(
            {'feed_url': url},
            {'$set': {'last_posted': entry_link}},
            upsert=True
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_feed(self, url: str) -> Optional[Dict]:
        """Fetch a single RSS feed with rate limiting and MongoDB caching."""
        try:
            # Serve from MongoDB cache if still fresh
            cached = await self._get_cached(url)
            if cached:
                return cached

            # Respect rate limits
            if url in self.last_fetch:
                elapsed = (datetime.utcnow() - self.last_fetch[url]).total_seconds()
                min_interval = 60 / RATE_LIMITS['rss_fetch']
                if elapsed < min_interval:
                    await asyncio.sleep(min_interval - elapsed)

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        return None
                    content = await response.text()

            feed = feedparser.parse(content)
            processed_entries = []
            for entry in feed.entries[:10]:
                soup = BeautifulSoup(entry.get('description', ''), 'html.parser')
                text = soup.get_text()
                clean_description = text[:500] + '...' if len(text) > 500 else text
                processed_entries.append({
                    'title': entry.get('title', 'No title'),
                    'link': entry.get('link', '#'),
                    'description': clean_description,
                    'published': entry.get('published', 'No date'),
                    'author': entry.get('author', 'Unknown'),
                })

            feed_data = {
                'title': feed.feed.get('title', 'Unknown Feed'),
                'entries': processed_entries,
            }

            await self._set_cache(url, feed_data)
            self.last_fetch[url] = datetime.utcnow()
            return feed_data

        except Exception as e:
            logger.error(f'Error fetching RSS feed {url}: {e}')
            return None

    async def get_category_feeds(self, category: str) -> List[Dict]:
        """Get all feeds for a specific category."""
        if category not in RSS_FEEDS:
            return []
        feeds = []
        for url in RSS_FEEDS[category]:
            feed_data = await self.fetch_feed(url)
            if feed_data:
                feeds.append(feed_data)
        return feeds

    async def get_latest_entries(
        self, category: str, limit: int = 5, skip_seen: bool = False
    ) -> List[Dict]:
        """Get the latest entries from all feeds in a category.

        When *skip_seen* is True only entries whose link differs from the
        last-posted link for that feed URL are returned.
        """
        feeds_info = RSS_FEEDS.get(category, [])
        all_entries: List[Dict] = []

        for url in feeds_info:
            feed_data = await self.fetch_feed(url)
            if not feed_data:
                continue

            entries = feed_data['entries']
            if skip_seen:
                last_posted = await self._get_last_posted(url)
                entries = [e for e in entries if e['link'] != last_posted]

            all_entries.extend(entries)

        # Best-effort sort by published date
        try:
            all_entries.sort(
                key=lambda x: datetime.strptime(x['published'], '%a, %d %b %Y %H:%M:%S %z'),
                reverse=True,
            )
        except Exception:
            pass

        return all_entries[:limit]

    async def search_feeds(
        self, query: str, category: Optional[str] = None
    ) -> List[Dict]:
        """Search for entries across all feeds or in a specific category."""
        categories = [category] if category else list(RSS_FEEDS.keys())
        results: List[Dict] = []
        query_lower = query.lower()

        for cat in categories:
            feeds = await self.get_category_feeds(cat)
            for feed in feeds:
                for entry in feed['entries']:
                    if (
                        query_lower in entry['title'].lower()
                        or query_lower in entry['description'].lower()
                    ):
                        results.append(entry)

        return results[:10]

    def get_available_categories(self) -> List[str]:
        """Get list of available RSS feed categories."""
        return list(RSS_FEEDS.keys())
