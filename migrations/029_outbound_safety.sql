-- 029: Outbound-message safety.
--  * Mass-unban apology DMs become opt-in per job (they were sent to every unbanned user, which
--    looks like DM spam to Discord) and the job keeps one edited progress message instead of
--    posting per event.
--  * Inactivity "we miss you" DMs become opt-in per guild.
--  * Index for the ban-audit lookup mass unban does per job.
-- Idempotent.

ALTER TABLE massunban_jobs
    ADD COLUMN IF NOT EXISTS notify_users BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS dm_sent INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS dm_failed INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rate_limit_hits INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS progress_channel_id BIGINT,
    ADD COLUMN IF NOT EXISTS progress_message_id BIGINT;

ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS inactivity_dm_enabled BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_audit_logs_guild_action_created
    ON audit_logs (guild_id, action, created_at DESC);
