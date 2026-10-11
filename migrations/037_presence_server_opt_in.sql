-- 037: Presence tracking = server opt-in + member opt-out (owner decision 2026-10-11).
--  * guild_settings.presence_tracking_enabled: a server's admins turn game/coding/streaming tracking on
--    (dashboard or /setup option). Off by default.
--  * users.presence_opt_in now means "tracking allowed for this member" and defaults to TRUE; a member
--    who runs /privacy optout (or /privacy delete) is FALSE. presence_opt_in_changed_at stays the consent
--    generation used to drop batches collected before a change.
--  * Members who never made a choice become allowed; members who explicitly opted out stay out.
--  * Music/Spotify is never tracked.
-- Idempotent.

ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS presence_tracking_enabled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users ALTER COLUMN presence_opt_in SET DEFAULT TRUE;

UPDATE users SET presence_opt_in = TRUE
WHERE presence_opt_in = FALSE AND presence_opt_in_changed_at IS NULL;

-- Per-server versions of features that only ran in the main server (the bot is meant for many servers).
--  * Inactivity alerts: per server (on by default; they only post if the server has a log channel),
--    with per-server "already notified" markers instead of the global flags on users.
--  * Season announcements: one per server per month, remembered durably.
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS inactivity_alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS inactivity_notices (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    level VARCHAR(8) NOT NULL CHECK (level IN ('week', 'month')),
    notified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id, level)
);

CREATE TABLE IF NOT EXISTS season_announcements (
    guild_id BIGINT NOT NULL,
    season_month VARCHAR(7) NOT NULL,
    announced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, season_month)
);

CREATE INDEX IF NOT EXISTS idx_activity_daily_guild_user_date ON user_activity_daily (guild_id, user_id, activity_date DESC);
