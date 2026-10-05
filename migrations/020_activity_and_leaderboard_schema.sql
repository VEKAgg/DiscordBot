-- VEKA Discord Bot - Activity, XP & Leaderboard Schema
-- Migration: 020_activity_and_leaderboard_schema.sql
-- Daily activity rollup, streak tracking, and leaderboard snapshots.

-- ============================================================
-- Daily Activity Rollup Table
-- ============================================================

CREATE TABLE IF NOT EXISTS user_activity_daily (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    activity_date DATE NOT NULL DEFAULT CURRENT_DATE,
    xp_earned INT NOT NULL DEFAULT 0,
    messages INT NOT NULL DEFAULT 0,
    voice_minutes INT NOT NULL DEFAULT 0,
    gaming_minutes INT NOT NULL DEFAULT 0,
    streaming_minutes INT NOT NULL DEFAULT 0,
    coding_minutes INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, guild_id, activity_date)
);

CREATE INDEX IF NOT EXISTS idx_activity_daily_lookup
ON user_activity_daily(guild_id, user_id, activity_date);

-- ============================================================
-- Streak Tracking (extend users table)
-- ============================================================

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS current_streak INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS longest_streak INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_streak_date DATE;

-- ============================================================
-- Leaderboard Snapshots Table
-- ============================================================

CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    season_month VARCHAR(7) NOT NULL, -- Format: YYYY-MM
    category VARCHAR(32) NOT NULL,    -- 'xp', 'voice', 'chat', 'gaming', 'streaming', 'coding'
    user_id BIGINT NOT NULL,
    rank INT NOT NULL,
    score BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leaderboard_snapshots
ON leaderboard_snapshots(guild_id, season_month, category);
