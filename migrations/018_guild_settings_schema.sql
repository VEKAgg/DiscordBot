-- VEKA Discord Bot - Multi-Guild Settings Schema
-- Migration: 018_guild_settings_schema.sql
-- Per-server channel and role configurations.

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT PRIMARY KEY,
    log_channel_id BIGINT,
    staff_channel_id BIGINT,
    alert_channel_id BIGINT,
    public_commands_channel_id BIGINT,
    welcome_channel_id BIGINT,
    radio_channel_id BIGINT,
    leaderboard_channel_id BIGINT,
    muted_role_id BIGINT,
    honeypot_channel_ids BIGINT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guild_settings_guild_id ON guild_settings(guild_id);

-- Seed backward-compatibility row for the primary guild with legacy hardcoded channel IDs.
-- ON CONFLICT ensures this is safe to re-run if the migration was partially applied.
INSERT INTO guild_settings (guild_id, log_channel_id, staff_channel_id, public_commands_channel_id, leaderboard_channel_id)
VALUES (1088553066334273537, 1329192112410857563, 1091908318324334704, 1385610318889222226, 1332399327100010569)
ON CONFLICT (guild_id) DO NOTHING;
