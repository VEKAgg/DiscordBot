-- 016: Mass unban job tracking — resumable jobs with per-user item tracking.

-- Job tracking
CREATE TABLE IF NOT EXISTS massunban_jobs (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    requested_by BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- Filters
    start_datetime TIMESTAMPTZ NOT NULL,
    end_datetime TIMESTAMPTZ NOT NULL,
    banned_by BIGINT,
    reason TEXT,
    -- Counters
    total_matched INTEGER DEFAULT 0,
    total_attempted INTEGER DEFAULT 0,
    total_succeeded INTEGER DEFAULT 0,
    total_failed INTEGER DEFAULT 0,
    total_skipped INTEGER DEFAULT 0,
    -- Progress
    last_processed_user_id VARCHAR(20),
    retry_after TIMESTAMPTZ,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    -- Metadata (rate limit stats, resume info, etc.)
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_massunban_jobs_guild_status ON massunban_jobs (guild_id, status);
CREATE INDEX IF NOT EXISTS idx_massunban_jobs_resumable ON massunban_jobs (status, retry_after)
    WHERE status IN ('retry_wait', 'running', 'paused');

-- Per-user job items
CREATE TABLE IF NOT EXISTS massunban_job_items (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES massunban_jobs(id) ON DELETE CASCADE,
    target_user_id VARCHAR(20) NOT NULL,
    target_username TEXT,
    ban_reason TEXT,
    banned_by BIGINT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    failure_reason TEXT,
    unbanned_at TIMESTAMPTZ,
    dm_status VARCHAR(10) DEFAULT 'pending',
    dm_failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_massunban_items_job ON massunban_job_items (job_id, status);
CREATE INDEX IF NOT EXISTS idx_massunban_items_user ON massunban_job_items (target_user_id);
CREATE INDEX IF NOT EXISTS idx_massunban_items_pending ON massunban_job_items (job_id) WHERE status = 'pending';
