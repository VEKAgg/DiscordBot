-- VEKA Discord Bot - Community feature additions
-- Migration: 005_community_additions.sql
-- Adds last_daily_activity to users and rss_cache table.

-- Track per-user daily activity for gamification cooldown
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_daily_activity DATE;

-- profiles needs a unique constraint for ON CONFLICT upsert
ALTER TABLE profiles ADD CONSTRAINT profiles_user_id_unique UNIQUE (user_id);

-- RSS feed cache (replaces MongoDB TTL collection).
-- Rows are expired by filtering expires_at < NOW() in queries;
-- a periodic cleanup job can DELETE expired rows if needed.
CREATE TABLE IF NOT EXISTS rss_cache (
    feed_url  VARCHAR(500) PRIMARY KEY,
    data      JSONB        NOT NULL,
    cached_at TIMESTAMP    DEFAULT NOW(),
    expires_at TIMESTAMP   NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rss_cache_expires ON rss_cache(expires_at);
