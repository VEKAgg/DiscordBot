-- VEKA Discord Bot - Moderation Upgrades Schema
-- Migration: 019_moderation_upgrades.sql
-- Extends warnings table with guild_id and active status, adds escalation thresholds to guild_settings.

-- ============================================================
-- Warnings table extensions
-- ============================================================

-- Add guild_id column (nullable initially, backfill, then enforce NOT NULL)
ALTER TABLE warnings ADD COLUMN IF NOT EXISTS guild_id BIGINT;

-- Backfill guild_id from the primary guild for any legacy rows
-- (legacy warnings were single-guild only)
UPDATE warnings SET guild_id = 1088553066334273537 WHERE guild_id IS NULL;

-- Enforce NOT NULL after backfill
ALTER TABLE warnings ALTER COLUMN guild_id SET NOT NULL;

-- Add active flag for soft-delete (clearing warnings)
ALTER TABLE warnings ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;

-- Convert created_at to TIMESTAMPTZ if still naive
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'warnings'
          AND column_name = 'created_at'
          AND udt_name = 'timestamp'
    ) THEN
        ALTER TABLE warnings ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC';
    END IF;
END $$;

-- Performance indexes for the warning queries
CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id, active);
CREATE INDEX IF NOT EXISTS idx_warnings_moderator ON warnings(moderator_id, created_at);

-- ============================================================
-- Guild settings escalation thresholds
-- ============================================================

ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS warn_mute_threshold INT DEFAULT 3,
    ADD COLUMN IF NOT EXISTS warn_ban_threshold INT DEFAULT 5,
    ADD COLUMN IF NOT EXISTS honeypot_cooldown_seconds INT DEFAULT 60;
