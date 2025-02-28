import feedparser
import aiohttp
import asyncio
from datetime import datetime, timedelta
import logging
from bs4 import BeautifulSoup
from src.config.config import RSS_FEEDS, RATE_LIMITS, CACHE_TTL
from typing import Dict, List, Optional
import json
import os
import aiofiles

logger = logging.getLogger('VEKA.rss')

class RSSService:
    def __init__(self):
        self.cache_dir = "data/cache/rss"
        self.cache: Dict[str, Dict] = {}
        self.last_fetch: Dict[str, datetime] = {}
        os.makedirs(self.cache_dir, exist_ok=True)

    async def fetch_feed(self, url: str) -> Optional[Dict]:
        """Fetch a single RSS feed with rate limiting and caching"""
        try:
            # Check cache
            cache_key = url.replace('/', '_').replace(':', '_')
            cache_file = f"{self.cache_dir}/{cache_key}.json"

            # Check if we have a recent cache
            if os.path.exists(cache_file):
                async with aiofiles.open(cache_file, 'r') as f:
                    cached_data = json.loads(await f.read())
                    cache_time = datetime.fromisoformat(cached_data['timestamp'])
                    if datetime.utcnow() - cache_time < timedelta(seconds=CACHE_TTL['rss_feed']):
                        return cached_data['data']

            # Respect rate limits
            if url in self.last_fetch:
                time_since_last = datetime.utcnow() - self.last_fetch[url]
                if time_since_last.seconds < (60 / RATE_LIMITS['rss_fetch']):
                    await asyncio.sleep(60 / RATE_LIMITS['rss_fetch'] - time_since_last.seconds)

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.text()
                        feed = feedparser.parse(content)
                        
                        # Process and clean the feed
                        processed_entries = []
                        for entry in feed.entries[:10]:  # Limit to 10 most recent entries
                            # Clean and extract text from HTML
                            soup = BeautifulSoup(entry.get('description', ''), 'html.parser')
                            clean_description = soup.get_text()[:500] + '...' if len(soup.get_text()) > 500 else soup.get_text()
                            
                            processed_entry = {
                                'title': entry.get('title', 'No title'),
                                'link': entry.get('link', '#'),
                                'description': clean_description,
                                'published': entry.get('published', 'No date'),
                                'author': entry.get('author', 'Unknown')
                            }
                            processed_entries.append(processed_entry)

                        feed_data = {
                            'title': feed.feed.get('title', 'Unknown Feed'),
                            'entries': processed_entries
                        }

                        # Cache the results
                        cache_data = {
                            'timestamp': datetime.utcnow().isoformat(),
                            'data': feed_data
                        }
                        async with aiofiles.open(cache_file, 'w') as f:
                            await f.write(json.dumps(cache_data))

                        self.last_fetch[url] = datetime.utcnow()
                        return feed_data

            return None
        except Exception as e:
            logger.error(f"Error fetching RSS feed {url}: {str(e)}")
            return None

    async def get_category_feeds(self, category: str) -> List[Dict]:
        """Get all feeds for a specific category"""
        if category not in RSS_FEEDS:
            return []

        feeds = []
        for url in RSS_FEEDS[category]:
            feed_data = await self.fetch_feed(url)
            if feed_data:
                feeds.append(feed_data)

        return feeds

    async def get_latest_entries(self, category: str, limit: int = 5) -> List[Dict]:
        """Get the latest entries from all feeds in a category"""
        feeds = await self.get_category_feeds(category)
        
        # Combine all entries
        all_entries = []
        for feed in feeds:
            all_entries.extend(feed['entries'])

        # Sort by date (if available) and limit
        try:
            all_entries.sort(key=lambda x: datetime.strptime(x['published'], '%a, %d %b %Y %H:%M:%S %z'), reverse=True)
        except:
            # If date parsing fails, keep the original order
            pass

        return all_entries[:limit]

    async def search_feeds(self, query: str, category: Optional[str] = None) -> List[Dict]:
        """Search for entries across all feeds or in a specific category"""
        if category:
            feeds = await self.get_category_feeds(category)
        else:
            feeds = []
            for category in RSS_FEEDS:
                category_feeds = await self.get_category_feeds(category)
                feeds.extend(category_feeds)

        # Search through entries
        results = []
        query = query.lower()
        for feed in feeds:
            for entry in feed['entries']:
                if (query in entry['title'].lower() or 
                    query in entry['description'].lower()):
                    results.append(entry)

        return results[:10]  # Limit to 10 results

    def get_available_categories(self) -> List[str]:
        """Get list of available RSS feed categories"""
        return list(RSS_FEEDS.keys()) 