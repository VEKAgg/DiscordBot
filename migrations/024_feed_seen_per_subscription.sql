-- VEKA Discord Bot - Per-subscription RSS dedupe
-- Migration: 024_feed_seen_per_subscription.sql
-- Created: 2026-10-05
--
-- Dedupe used rss_cache(feed_url, entry_id), shared by every guild: when guild A polled a feed
-- first, guild B subscribed to the same URL never received those entries (audit H-12).
-- Track seen items per subscription instead.

ALTER TABLE feed_seen_items
    ADD COLUMN IF NOT EXISTS subscription_id BIGINT REFERENCES feed_subscriptions(id) ON DELETE CASCADE;

ALTER TABLE feed_seen_items DROP CONSTRAINT IF EXISTS feed_seen_items_feed_url_item_guid_key;
DROP INDEX IF EXISTS idx_feed_seen_lookup;
CREATE UNIQUE INDEX IF NOT EXISTS idx_feed_seen_subscription_guid ON feed_seen_items(subscription_id, item_guid);

-- Seed from the old shared cache so existing subscriptions don't re-post old entries once.
INSERT INTO feed_seen_items (feed_url, item_guid, subscription_id)
SELECT s.feed_url, r.entry_id, s.id
FROM feed_subscriptions s
JOIN rss_cache r ON r.feed_url = s.feed_url
ON CONFLICT DO NOTHING;
