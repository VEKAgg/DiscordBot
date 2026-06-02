import feedparser
import aiohttp
import asyncio
import json
from datetime import datetime, timedelta
import logging
from bs4 import BeautifulSoup
from src.config.config import RSS_FEEDS, RATE_LIMITS, CACHE_TTL
from src.database.database import db
from typing import Dict, List, Optional

logger = logging.getLogger('VEKA.rss')


class RSSService:
    def __init__(self):
        self.last_fetch: Dict[str, datetime] = {}

    async def _get_cached(self, url: str) -> Optional[Dict]:
        row = await db.fetch_one(
            "SELECT data FROM rss_cache WHERE feed_url = $1 AND expires_at > NOW()",
            url
        )
        return row['data'] if row else None

    async def _set_cache(self, url: str, data: Dict) -> None:
        ttl = CACHE_TTL.get('rss_feed', 3600)
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        await db.execute(
            """
            INSERT INTO rss_cache (feed_url, data, cached_at, expires_at)
            VALUES ($1, $2, NOW(), $3)
            ON CONFLICT (feed_url)
            DO UPDATE SET data = EXCLUDED.data, cached_at = NOW(), expires_at = EXCLUDED.expires_at
            """,
            url, json.dumps(data), expires_at
        )

    async def fetch_feed(self, url: str) -> Optional[Dict]:
        try:
            cached = await self._get_cached(url)
            if cached:
                return cached if isinstance(cached, dict) else json.loads(cached)

            min_interval = 60 / RATE_LIMITS.get('rss_fetch', 1)
            if url in self.last_fetch:
                elapsed = (datetime.utcnow() - self.last_fetch[url]).total_seconds()
                if elapsed < min_interval:
                    await asyncio.sleep(min_interval - elapsed)

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    content = await response.text()

            feed = feedparser.parse(content)
            entries = []
            for entry in feed.entries[:10]:
                soup = BeautifulSoup(entry.get('description', ''), 'html.parser')
                text = soup.get_text()
                entries.append({
                    'title': entry.get('title', 'No title'),
                    'link': entry.get('link', '#'),
                    'description': text[:500] + '...' if len(text) > 500 else text,
                    'published': entry.get('published', 'No date'),
                    'author': entry.get('author', 'Unknown'),
                })

            feed_data = {'title': feed.feed.get('title', 'Unknown Feed'), 'entries': entries}
            await self._set_cache(url, feed_data)
            self.last_fetch[url] = datetime.utcnow()
            return feed_data

        except Exception as e:
            logger.error(f'Error fetching RSS feed {url}: {e}')
            return None

    async def get_category_feeds(self, category: str) -> List[Dict]:
        if category not in RSS_FEEDS:
            return []
        feeds = []
        for url in RSS_FEEDS[category]:
            data = await self.fetch_feed(url)
            if data:
                feeds.append(data)
        return feeds

    async def get_latest_entries(self, category: str, limit: int = 5) -> List[Dict]:
        feeds = await self.get_category_feeds(category)
        all_entries = [e for f in feeds for e in f['entries']]
        try:
            all_entries.sort(
                key=lambda x: datetime.strptime(x['published'], '%a, %d %b %Y %H:%M:%S %z'),
                reverse=True
            )
        except (ValueError, TypeError):
            pass
        return all_entries[:limit]

    async def search_feeds(self, query: str, category: Optional[str] = None) -> List[Dict]:
        if category:
            feeds = await self.get_category_feeds(category)
        else:
            feeds = []
            for cat in RSS_FEEDS:
                feeds.extend(await self.get_category_feeds(cat))

        q = query.lower()
        results = [
            e for f in feeds for e in f['entries']
            if q in e['title'].lower() or q in e['description'].lower()
        ]
        return results[:10]

    def get_available_categories(self) -> List[str]:
        return list(RSS_FEEDS.keys())
