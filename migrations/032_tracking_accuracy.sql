-- 032: Accurate activity tracking and presence opt-in.
--  * Coding minutes get their own column (they were added to total_gaming_minutes).
--  * Presence-derived tracking (games, coding apps, streaming) becomes opt-in per user.
--  * Per-guild daily rollups count commands too.
--  * The auto-updating leaderboard remembers its message instead of adopting any bot message.
-- Idempotent.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS total_coding_minutes INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS presence_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS presence_opt_in_changed_at TIMESTAMPTZ;

ALTER TABLE user_activity_daily
    ADD COLUMN IF NOT EXISTS commands INTEGER NOT NULL DEFAULT 0;

ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS leaderboard_message_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_users_presence_opt_in ON users (discord_id) WHERE presence_opt_in;
CREATE INDEX IF NOT EXISTS idx_activity_daily_guild_date ON user_activity_daily (guild_id, activity_date);
-- Remove duplicate snapshot rows (keep the first) so the unique index can be built.
DELETE FROM leaderboard_snapshots a
USING leaderboard_snapshots b
WHERE a.guild_id = b.guild_id AND a.season_month = b.season_month AND a.category = b.category
  AND a.user_id = b.user_id AND a.id > b.id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_leaderboard_snapshots_unique
    ON leaderboard_snapshots (guild_id, season_month, category, user_id);

-- One-time repair of the corrupted gaming/coding totals (runs once: the runner records this file).
-- total_gaming_minutes held real+capped gaming minutes (double count) plus capped coding minutes.
-- user_activity_details was written by a separate path without those bugs, so rebuild both totals
-- from it for users that have detail rows. 'game' rows include coding apps (they show as "Playing"),
-- so coding is subtracted from gaming. Streaming totals can't be repaired (no independent record).
UPDATE users u
SET total_coding_minutes = d.coding,
    total_gaming_minutes = GREATEST(0, d.game - d.coding)
FROM (
    SELECT user_id,
           COALESCE(SUM(duration_minutes) FILTER (WHERE activity_type = 'game'), 0) AS game,
           COALESCE(SUM(duration_minutes) FILTER (WHERE activity_type = 'coding'), 0) AS coding
    FROM user_activity_details
    WHERE activity_type IN ('game', 'coding')
    GROUP BY user_id
) d
WHERE u.discord_id = d.user_id;

-- Season archives are complete only when every category was snapshotted in one transaction.
CREATE TABLE IF NOT EXISTS season_archives (
    season_month VARCHAR(7) PRIMARY KEY,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    announced_at TIMESTAMPTZ
);
