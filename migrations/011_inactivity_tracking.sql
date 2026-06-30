-- Inactivity tracking flags for periodic check-ins
-- Tracks whether a user has been notified at each inactivity threshold

ALTER TABLE users ADD COLUMN IF NOT EXISTS inactive_week_notified BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS inactive_month_notified BOOLEAN DEFAULT FALSE;
