-- 042: Presence tracking = server opt-in + member OPT-IN (owner decision 2026-11-21: EU GDPR baseline,
--      see the VEKA "Bot Terms and Privacy" page and DPIA-1).
--  * users.presence_opt_in now means "this member agreed to activity tracking" and defaults to FALSE.
--    Members who never made a choice were tracked under the old opt-out rule without consent: they are
--    switched off, and the presence-derived data recorded about them (games, coding apps, streaming) is
--    erased. Message/voice counts and XP are unaffected (legitimate interest, see LIA-1).
--  * presence_opt_in_changed_at is set for them so batches collected before this change are dropped.
--  * bot_guild_departures remembers when the bot left a server; nightly maintenance deletes that
--    server's data 30 days later unless the bot was added back.
-- Idempotent.

ALTER TABLE users ALTER COLUMN presence_opt_in SET DEFAULT FALSE;

UPDATE users SET presence_opt_in = FALSE, presence_opt_in_changed_at = NOW()
WHERE presence_opt_in AND presence_opt_in_changed_at IS NULL;

DELETE FROM user_active_activities a
WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.discord_id = a.user_id AND u.presence_opt_in);

DELETE FROM user_activity_details d
WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.discord_id = d.user_id AND u.presence_opt_in);

UPDATE user_activity_daily d SET gaming_minutes = 0, streaming_minutes = 0, coding_minutes = 0
WHERE (d.gaming_minutes > 0 OR d.streaming_minutes > 0 OR d.coding_minutes > 0)
  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.discord_id = d.user_id::text AND u.presence_opt_in);

UPDATE users SET total_gaming_minutes = 0, total_streaming_minutes = 0, total_coding_minutes = 0
WHERE NOT presence_opt_in
  AND (total_gaming_minutes > 0 OR total_streaming_minutes > 0 OR total_coding_minutes > 0);

CREATE TABLE IF NOT EXISTS bot_guild_departures (
    guild_id BIGINT PRIMARY KEY,
    left_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
