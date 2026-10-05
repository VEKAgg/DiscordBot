-- VEKA Discord Bot - Warnings use Discord snowflakes
-- Migration: 022_warnings_snowflake_ids.sql
-- Created: 2026-10-05
--
-- 008 declared warnings.user_id / moderator_id as INTEGER REFERENCES users(id), but the
-- moderation cog stores Discord IDs (snowflakes, > int4), so every /warn failed with
-- "value out of int32 range" (audit H-05). Convert both columns to BIGINT snowflakes.
-- Existing rows (if any) are mapped through users.id -> users.discord_id.
-- Idempotent: does nothing once the columns are already BIGINT.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'warnings'
          AND column_name = 'user_id' AND data_type = 'integer'
    ) THEN
        ALTER TABLE warnings ADD COLUMN user_snowflake BIGINT, ADD COLUMN moderator_snowflake BIGINT;

        UPDATE warnings w SET user_snowflake = u.discord_id::BIGINT
        FROM users u WHERE u.id = w.user_id AND u.discord_id ~ '^[0-9]{1,19}$';

        UPDATE warnings w SET moderator_snowflake = u.discord_id::BIGINT
        FROM users u WHERE u.id = w.moderator_id AND u.discord_id ~ '^[0-9]{1,19}$';

        -- CASCADE drops the FKs and the indexes on the old columns; indexes are recreated below.
        ALTER TABLE warnings DROP COLUMN user_id CASCADE, DROP COLUMN moderator_id CASCADE;
        ALTER TABLE warnings RENAME COLUMN user_snowflake TO user_id;
        ALTER TABLE warnings RENAME COLUMN moderator_snowflake TO moderator_id;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_warnings_user_id ON warnings(user_id);
CREATE INDEX IF NOT EXISTS idx_warnings_moderator_id ON warnings(moderator_id);
CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id, active);
CREATE INDEX IF NOT EXISTS idx_warnings_moderator ON warnings(moderator_id, created_at);
