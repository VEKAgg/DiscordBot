-- 010: RPG activity tracking — XP, voice time, activity roles, and leaderboard support.

-- Activity tracking columns on users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_messages INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_voice_minutes INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_commands INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP;

-- Detailed activity log for leaderboard calculations
CREATE TABLE IF NOT EXISTS user_activity_log (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(20) NOT NULL,
    activity_type   VARCHAR(20) NOT NULL,
    points_awarded  INTEGER DEFAULT 0,
    channel_id      BIGINT,
    guild_id        BIGINT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_log_user ON user_activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_created ON user_activity_log(created_at);

-- Dynamic activity role tracking (auto-assigned/removed)
CREATE TABLE IF NOT EXISTS user_rpg_roles (
    user_id         VARCHAR(20) PRIMARY KEY,
    active_role     VARCHAR(20),
    last_evaluated  TIMESTAMP DEFAULT NOW()
);
