-- VEKA Discord Bot - Fix schema inconsistencies
-- Migration: 008_fix_schema_inconsistencies.sql
-- Fixes two issues:
--   1. rss_cache had the wrong schema (005_community_additions.sql created a JSONB
--      version, but 005_guild_and_rss_schema.sql's entry-level schema was never
--      applied because the table already existed). Code expects entry_id columns.
--   2. marketplace_listings is missing the image_url column that the code uses.

-- Replace rss_cache with the intended entry-level schema
DROP TABLE IF EXISTS rss_cache;

CREATE TABLE IF NOT EXISTS rss_cache (
    id SERIAL PRIMARY KEY,
    feed_url VARCHAR(500) NOT NULL,
    entry_id VARCHAR(500) NOT NULL,
    title VARCHAR(500),
    link VARCHAR(500),
    summary TEXT,
    author VARCHAR(255),
    published_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(feed_url, entry_id)
);

CREATE INDEX IF NOT EXISTS idx_rss_cache_feed_url ON rss_cache(feed_url);
CREATE INDEX IF NOT EXISTS idx_rss_cache_entry_id ON rss_cache(entry_id);

-- Add missing image_url column to marketplace_listings
ALTER TABLE marketplace_listings ADD COLUMN IF NOT EXISTS image_url TEXT;
