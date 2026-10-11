-- 033: Data the dashboard API needs from the bot (the API has no gateway connection).
--  * bot_status: one row the bot refreshes every minute (health, version, outbound guard state).
--  * bot_guild_snapshot: per guild the bot is in — channels, roles, counts — for dashboard pickers and
--    for the API's "bot is in this guild" authorisation check.
--  * massunban_jobs: dashboard-started jobs ('requested' → bot computes the preview → two-step confirm).
-- Idempotent.

CREATE TABLE IF NOT EXISTS bot_status (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version TEXT,
    commit_sha TEXT,
    started_at TIMESTAMPTZ,
    latency_ms INTEGER,
    guild_count INTEGER,
    db_ok BOOLEAN,
    degraded_features JSONB NOT NULL DEFAULT '[]'::jsonb,
    outbound JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_guild_snapshot (
    guild_id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    icon_url TEXT,
    owner_id BIGINT,
    member_count INTEGER,
    online_count INTEGER,
    channels JSONB NOT NULL DEFAULT '[]'::jsonb,
    roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    bot_permissions BIGINT,
    bot_top_role_position INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 'awaiting_confirmation' doesn't fit the original VARCHAR(20).
ALTER TABLE massunban_jobs ALTER COLUMN status TYPE VARCHAR(32);

ALTER TABLE massunban_jobs
    ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'discord',
    ADD COLUMN IF NOT EXISTS include_unaudited BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS confirm_token_hash TEXT,
    ADD COLUMN IF NOT EXISTS confirm_step SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS confirm_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

-- One item per user per job (the dashboard preview is written once, atomically).
CREATE UNIQUE INDEX IF NOT EXISTS idx_massunban_items_job_target ON massunban_job_items (job_id, target_user_id);

CREATE INDEX IF NOT EXISTS idx_massunban_jobs_requested ON massunban_jobs (status) WHERE status = 'requested';
