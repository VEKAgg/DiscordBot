-- VEKA Discord Bot - Support Schema
-- Migration: 005_guild_and_rss_schema.sql
-- Created: 2026-06-02

-- Drop rss_cache if it exists from the incompatible 005_community_additions.sql schema
DROP TABLE IF EXISTS rss_cache;

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

CREATE INDEX idx_guild_config_guild_id ON guild_config(guild_id);

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

CREATE INDEX idx_rss_cache_feed_url ON rss_cache(feed_url);
CREATE INDEX idx_rss_cache_entry_id ON rss_cache(entry_id);

-- Lightweight migration tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT NOW()
);
