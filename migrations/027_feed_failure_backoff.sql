-- Persist outage state so restarts cannot re-send RSS warnings.
ALTER TABLE feed_subscriptions
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
