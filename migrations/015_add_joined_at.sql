-- 015: Add joined_at column to users for inactivity tracking.

ALTER TABLE users ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ;

-- Backfill from created_at where joined_at is NULL
UPDATE users SET joined_at = created_at WHERE joined_at IS NULL;
