import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import aiohttp
from aiohttp import ClientError
import feedparser
import logging
from bs4 import BeautifulSoup

from src.config.config import CACHE_TTL, RATE_LIMITS, RSS_FEEDS

logger = logging.getLogger('VEKA.rss')


class RSSService:
    def __init__(self):
        self.last_fetch: Dict[str, datetime] = {}
        self.cache: Dict[str, Dict] = {}

    async def _get_cached(self, url: str) -> Optional[Dict]:
        ttl_seconds = CACHE_TTL.get('rss_feed', 3600)
        entry = self.cache.get(url)
        if not entry:
            return None

        fetched_at = entry.get('cached_at')
        if not fetched_at or (datetime.utcnow() - fetched_at).total_seconds() > ttl_seconds:
            self.cache.pop(url, None)
            return None

        return entry.get('data')

    async def _set_cache(self, url: str, data: Dict) -> None:
        self.cache[url] = {
            'cached_at': datetime.utcnow(),
            'data': data,
        }

    async def _get_last_posted(self, url: str) -> Optional[str]:
        entry = self.cache.get(url)
        return entry.get('last_posted') if entry else None

    async def set_last_posted(self, url: str, entry_link: str) -> None:
        self.cache.setdefault(url, {})['last_posted'] = entry_link

    async def fetch_feed(self, url: str) -> Optional[Dict]:
        try:
            cached = await self._get_cached(url)
            if cached:
                return cached

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

        except (asyncio.TimeoutError, ClientError) as exc:
            logger.warning('RSS fetch failed for %s: %s', url, exc, exc_info=True)
            return None
        except Exception as exc:
            logger.error('Error fetching RSS feed %s: %s', url, exc, exc_info=True)
            return None

    async def get_category_feeds(self, category: str) -> List[Dict]:
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

        try:
            all_entries.sort(
                key=lambda x: datetime.strptime(x['published'], '%a, %d %b %Y %H:%M:%S %z'),
                reverse=True,
            )
        except Exception:
            pass

        return all_entries[:limit]

    async def search_feeds(self, query: str, category: Optional[str] = None) -> List[Dict]:
        categories = [category] if category else list(RSS_FEEDS.keys())
        results: List[Dict] = []
        query_lower = query.lower()

        for cat in categories:
            feeds = await self.get_category_feeds(cat)
            for feed in feeds:
                for entry in feed['entries']:
                    if query_lower in entry['title'].lower() or query_lower in entry['description'].lower():
                        results.append(entry)

        return results[:10]

    def get_available_categories(self) -> List[str]:
        return list(RSS_FEEDS.keys())
