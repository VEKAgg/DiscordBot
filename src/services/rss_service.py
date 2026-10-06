import logging

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from src.database.database import db
from src.utils.http import UnsafeURLError, fetch_public_url
from src.utils.safety import DatabaseUnavailableError, ExternalRequestError

logger = logging.getLogger('VEKA.rss')


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
            if not feed.get('version'):
                raise ExternalRequestError('Response is not a recognized RSS or Atom feed')
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

            return feed_data

        except UnsafeURLError as exc:
            logger.warning('Rejected RSS feed URL %r: %s', url[:200], exc)
            return None
        except Exception as exc:
            logger.error('Error fetching RSS feed %s: %s', url, exc, exc_info=True)
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
