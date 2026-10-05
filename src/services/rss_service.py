import asyncio
import logging
from datetime import datetime

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from src.config.config import RSS_FEEDS
from src.database.database import db
from src.utils.http import UnsafeURLError, fetch_public_url
from src.utils.safety import DatabaseUnavailableError, ExternalRequestError

logger = logging.getLogger('VEKA.rss')

_background_tasks: set[asyncio.Task] = set()


class RSSService:
    def __init__(self, bot=None):
        self.bot = bot

    async def fetch_feed(self, url: str) -> dict | None:
        try:
            headers = {'User-Agent': 'VEKA-DiscordBot/1.0'}
            # User-supplied URL: SSRF-guarded, size-capped fetch (audit H-04).
            status, content = await fetch_public_url(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10))
            if status != 200:
                raise ExternalRequestError(f'HTTP Status: {status}')

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
                    task = asyncio.create_task(
                        self.bot.notifier.send_alert(
                            title='RSS Feed Recovered',
                            description=f'The RSS feed `{url}` is now responding correctly.',
                            severity='INFO',
                        )
                    )
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)

            return feed_data

        except UnsafeURLError as exc:
            logger.warning('Rejected RSS feed URL %r: %s', url[:200], exc)
            return None
        except Exception as exc:
            logger.error('Error fetching RSS feed %s: %s', url, exc, exc_info=True)
            from src.core.runtime_state import runtime_state

            fail_key = f'rss_fail_{url}'
            fails = runtime_state.alert_state_cache.get(fail_key, 0) + 1
            runtime_state.alert_state_cache[fail_key] = fails

            if fails >= 3 and self.bot and hasattr(self.bot, 'notifier'):
                task = asyncio.create_task(
                    self.bot.notifier.send_alert(
                        title='RSS Feed Failing',
                        description=f'The RSS feed `{url}` has failed {fails} consecutive times.\n**Error:** {str(exc)[:500]}',
                        severity='WARN',
                        dedupe_key=f'rss_alert_{url}',
                        cooldown_minutes=120,
                    )
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            return None

    async def process_and_dedupe(
        self, url: str, entries: list[dict], subscription_id: int | None = None, *, mark_seen: bool = True
    ) -> list[dict]:
        """Return entries not seen before.

        With ``subscription_id`` (the feed poller), dedupe is per subscription so every guild
        subscribed to the same URL gets its own copy (audit H-12). Without it, the legacy
        URL-wide ``rss_cache`` is used. The poller uses ``mark_seen=False`` to preview
        unseen subscription entries, then records each one only after successful delivery.
        """
        if not mark_seen and subscription_id is None:
            raise ValueError('Preview dedupe requires a subscription ID')
        new_entries = []
        for entry in entries:
            try:
                if subscription_id is not None and not mark_seen:
                    exists = await db.fetchval(
                        'SELECT 1 FROM feed_seen_items WHERE subscription_id = $1 AND item_guid = $2',
                        subscription_id,
                        entry['entry_id'][:1000],
                    )
                    if exists is None:
                        new_entries.append(entry)
                    continue
                if subscription_id is not None:
                    inserted = await db.fetchval(
                        """INSERT INTO feed_seen_items (feed_url, item_guid, subscription_id)
                           VALUES ($1, $2, $3)
                           ON CONFLICT DO NOTHING
                           RETURNING id""",
                        url,
                        entry['entry_id'][:1000],
                        subscription_id,
                    )
                else:
                    inserted = await db.fetchval(
                        """INSERT INTO rss_cache (feed_url, entry_id, title, link, summary, author)
                           VALUES ($1, $2, $3, $4, $5, $6)
                           ON CONFLICT DO NOTHING
                           RETURNING id""",
                        url[:500],
                        entry['entry_id'][:500],
                        entry['title'][:500],
                        entry['link'][:500],
                        entry['description'],
                        entry['author'][:255],
                    )
            except DatabaseUnavailableError:
                logger.warning('Database unavailable during feed dedup, stopping feed processing')
                break
            except Exception as exc:
                logger.error('Failed to record RSS entry: %s', exc)
                continue
            if inserted is not None:
                new_entries.append(entry)
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
                key=lambda x: self._parse_entry_date(x['published']),
                reverse=True,
            )
        except Exception:
            pass

        return all_new_entries[:limit]

    def get_available_categories(self) -> list[str]:
        return list(RSS_FEEDS.keys())

    @staticmethod
    def _parse_entry_date(date_str: str) -> datetime:
        """Parse an RSS entry date string, supporting RFC 2822 and ISO 8601 formats."""
        from email.utils import parsedate_to_datetime

        # Try RFC 2822 first (most RSS feeds)
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            pass
        # Try ISO 8601
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except Exception:
            pass
        # Fallback: return epoch so sorting still works (oldest first)
        return datetime.min.replace(tzinfo=None)
