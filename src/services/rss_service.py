import asyncio
import logging
from datetime import datetime

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from src.config.config import RSS_FEEDS
from src.database.database import db
from src.utils.safety import DatabaseUnavailableError, ExternalRequestError

logger = logging.getLogger('VEKA.rss')


class RSSService:
    def __init__(self, bot=None):
        self.bot = bot

    async def fetch_feed(self, url: str) -> dict | None:
        try:
            headers = {'User-Agent': 'VEKA-DiscordBot/1.0'}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        raise ExternalRequestError(f'HTTP Status: {response.status}')
                    content = await response.text()

            feed = feedparser.parse(content)
            processed_entries = []
            for entry in feed.entries[:10]:
                soup = BeautifulSoup(entry.get('description', ''), 'html.parser')
                text = soup.get_text()
                clean_description = text[:500] + '...' if len(text) > 500 else text

                entry_id = entry.get('id', entry.get('link', ''))
                if not entry_id:
                    continue

                processed_entries.append(
                    {
                        'entry_id': entry_id,
                        'title': entry.get('title', 'No title'),
                        'link': entry.get('link', '#'),
                        'description': clean_description,
                        'published': entry.get('published', 'No date'),
                        'author': entry.get('author', 'Unknown'),
                    }
                )

            feed_data = {
                'title': feed.feed.get('title', 'Unknown Feed'),
                'entries': processed_entries,
            }

            # Handle recovery
            from src.core.runtime_state import runtime_state

            fail_key = f'rss_fail_{url}'
            if runtime_state.alert_state_cache.get(fail_key, 0) > 0:
                runtime_state.alert_state_cache[fail_key] = 0
                if self.bot and hasattr(self.bot, 'notifier'):
                    self.bot.notifier.clear_cooldown(f'rss_alert_{url}')
                    asyncio.create_task(
                        self.bot.notifier.send_alert(
                            title='RSS Feed Recovered',
                            description=f'The RSS feed `{url}` is now responding correctly.',
                            severity='INFO',
                        )
                    )

            return feed_data

        except Exception as exc:
            logger.error('Error fetching RSS feed %s: %s', url, exc, exc_info=True)
            from src.core.runtime_state import runtime_state

            fail_key = f'rss_fail_{url}'
            fails = runtime_state.alert_state_cache.get(fail_key, 0) + 1
            runtime_state.alert_state_cache[fail_key] = fails

            if fails >= 3 and self.bot and hasattr(self.bot, 'notifier'):
                asyncio.create_task(
                    self.bot.notifier.send_alert(
                        title='RSS Feed Failing',
                        description=f'The RSS feed `{url}` has failed {fails} consecutive times.\n**Error:** {str(exc)[:500]}',
                        severity='WARN',
                        dedupe_key=f'rss_alert_{url}',
                        cooldown_minutes=120,
                    )
                )
            return None

    async def process_and_dedupe(self, url: str, entries: list[dict]) -> list[dict]:
        new_entries = []
        for entry in entries:
            try:
                exists = await db.fetch_one(
                    'SELECT 1 FROM rss_cache WHERE feed_url = $1 AND entry_id = $2', url, entry['entry_id']
                )
            except DatabaseUnavailableError:
                logger.warning('Database unavailable during feed dedup check, stopping feed processing')
                break
            except Exception as exc:
                logger.error('Failed to check RSS entry in db: %s', exc)
                continue
            if not exists:
                try:
                    await db.execute(
                        """INSERT INTO rss_cache
                           (feed_url, entry_id, title, link, summary, author)
                           VALUES ($1, $2, $3, $4, $5, $6)
                           ON CONFLICT DO NOTHING""",
                        url,
                        entry['entry_id'],
                        entry['title'][:500],
                        entry['link'][:500],
                        entry['description'],
                        entry['author'][:255],
                    )
                    new_entries.append(entry)
                except Exception as exc:
                    logger.error('Failed to insert RSS entry into db: %s', exc)
        return new_entries

    async def get_latest_new_entries(self, category: str, limit: int = 5) -> list[dict]:
        """Fetch feeds and return ONLY new entries (deduplicated via Postgres)."""
        feeds_info = RSS_FEEDS.get(category, [])
        all_new_entries: list[dict] = []

        for url in feeds_info:
            feed_data = await self.fetch_feed(url)
            if not feed_data:
                continue

            new_entries = await self.process_and_dedupe(url, feed_data['entries'])
            all_new_entries.extend(new_entries)

        try:
            all_new_entries.sort(
                key=lambda x: datetime.strptime(x['published'], '%a, %d %b %Y %H:%M:%S %z'),
                reverse=True,
            )
        except Exception:
            pass

        return all_new_entries[:limit]

    def get_available_categories(self) -> list[str]:
        return list(RSS_FEEDS.keys())
