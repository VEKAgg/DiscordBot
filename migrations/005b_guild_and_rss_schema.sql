-- VEKA Discord Bot - Support Schema
-- Migration: 005b_guild_and_rss_schema.sql (renamed from 005_guild_and_rss_schema.sql to avoid collision with 005_community_additions.sql)
-- Created: 2026-06-02

-- Drop rss_cache only if it still has the incompatible 005_community_additions.sql shape
-- (feed_url PK + JSONB data, no entry_id). Never drop a populated dedupe table (audit C-03).
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'rss_cache' AND column_name = 'data')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'rss_cache' AND column_name = 'entry_id') THEN
        DROP TABLE rss_cache;
    END IF;
END $$;

-- Add image_url column to marketplace_listings (missing from 004_marketplace_schema.sql)
ALTER TABLE marketplace_listings ADD COLUMN IF NOT EXISTS image_url TEXT;

-- Guild / server configuration
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id VARCHAR(20) PRIMARY KEY,
    prefix VARCHAR(10) DEFAULT '!',
    welcome_channel_id VARCHAR(20),
    mod_role_id VARCHAR(20),
    notification_channel_id VARCHAR(20),
    timezone VARCHAR(50),
    settings JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guild_config_guild_id ON guild_config(guild_id);

-- RSS cache and deduplication
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

-- Lightweight migration tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT NOW()
);
