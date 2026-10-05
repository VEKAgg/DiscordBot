-- Phase 5: Community, Marketplace, Directory & Utilities
-- Adds marketplace enhancements, dynamic RSS feeds, server stats, profile/directory support,
-- mentorship matches, and welcome system configuration.

-- ============================================================
-- 1. Marketplace Listing Enhancements
-- ============================================================
ALTER TABLE marketplace_listings
    ADD COLUMN IF NOT EXISTS last_bumped_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS is_expired BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_marketplace_active_listings
    ON marketplace_listings(status, is_expired, last_bumped_at DESC);

-- ============================================================
-- 2. Dynamic RSS Feeds & Deduplication
-- ============================================================
CREATE TABLE IF NOT EXISTS feed_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    feed_url TEXT NOT NULL,
    feed_name VARCHAR(64) NOT NULL,
    poll_interval_minutes INT DEFAULT 30,
    last_polled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(guild_id, feed_url)
);

CREATE TABLE IF NOT EXISTS feed_seen_items (
    id BIGSERIAL PRIMARY KEY,
    feed_url TEXT NOT NULL,
    item_guid TEXT NOT NULL,
    seen_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(feed_url, item_guid)
);

CREATE INDEX IF NOT EXISTS idx_feed_seen_lookup ON feed_seen_items(feed_url, item_guid);

-- Seed default RSS feeds for the main guild (if not already present).
-- Channel IDs will be configured by staff via /feed add.
INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name, poll_interval_minutes)
VALUES
    (1088553066334273537, 0, 'https://feeds.feedburner.com/TechCrunch',            'TechCrunch',            30),
    (1088553066334273537, 0, 'https://www.wired.com/feed/rss',                     'Wired RSS',             30),
    (1088553066334273537, 0, 'https://www.theverge.com/rss/index.xml',             'The Verge',             30),
    (1088553066334273537, 0, 'https://stackoverflow.com/jobs/feed',                'SO Jobs',               60),
    (1088553066334273537, 0, 'https://remoteok.io/remote-jobs.rss',               'RemoteOK',              60),
    (1088553066334273537, 0, 'https://weworkremotely.com/categories/remote-programming-jobs.rss', 'WeWorkRemotely', 60),
    (1088553066334273537, 0, 'https://dev.to/feed',                                'Dev.to',                30),
    (1088553066334273537, 0, 'https://medium.com/feed/tag/programming',            'Medium Programming',    30),
    (1088553066334273537, 0, 'https://blog.github.com/all.atom',                   'GitHub Blog',           60)
ON CONFLICT (guild_id, feed_url) DO NOTHING;

-- ============================================================
-- 3. Server Stats Daily Tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS server_stats_daily (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    stat_date DATE NOT NULL DEFAULT CURRENT_DATE,
    total_members INT NOT NULL,
    joins INT DEFAULT 0,
    leaves INT DEFAULT 0,
    max_online INT DEFAULT 0,
    boost_level INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(guild_id, stat_date)
);

-- ============================================================
-- 4. Profile Enhancements
-- ============================================================
-- Convert existing TEXT skills column to TEXT[] (comma-separated → array)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'profiles' AND column_name = 'skills'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE profiles ALTER COLUMN skills TYPE TEXT[] USING string_to_array(skills, ',');
        ALTER TABLE profiles ALTER COLUMN skills SET DEFAULT '{}';
    END IF;
EXCEPTION WHEN undefined_table THEN NULL;
END $$;

ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS timezone VARCHAR(64);

-- ============================================================
-- 5. Mentorship Matches (layered on top of existing mentorships)
-- ============================================================
CREATE TABLE IF NOT EXISTS mentorship_matches (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    mentor_id BIGINT NOT NULL,
    mentee_id BIGINT NOT NULL,
    category VARCHAR(64) NOT NULL,
    status VARCHAR(32) DEFAULT 'active',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    outcome TEXT,
    last_checkin_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 6. Guild Settings: Welcome System
-- ============================================================
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS welcome_message_template TEXT DEFAULT 'Welcome {user} to {server}!',
    ADD COLUMN IF NOT EXISTS welcome_card_enabled BOOLEAN DEFAULT TRUE;
