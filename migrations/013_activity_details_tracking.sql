-- 013: Detailed activity tracking for games, listening, and coding stats

-- Track specific activity names (games, songs, coding apps)
CREATE TABLE IF NOT EXISTS user_activity_details (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(20) NOT NULL,
    activity_type   VARCHAR(20) NOT NULL,  -- 'game', 'listening', 'coding', 'streaming_game', 'radio'
    activity_name   TEXT NOT NULL,
    duration_minutes INTEGER DEFAULT 0,
    last_seen       TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, activity_type, activity_name)
);

CREATE INDEX IF NOT EXISTS idx_activity_details_user ON user_activity_details(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_details_type ON user_activity_details(activity_type);
CREATE INDEX IF NOT EXISTS idx_activity_details_name ON user_activity_details(activity_type, activity_name);

-- Track currently active activities for accurate duration calculation
CREATE TABLE IF NOT EXISTS user_active_activities (
    user_id         VARCHAR(20) NOT NULL,
    activity_type   VARCHAR(20) NOT NULL,
    activity_name   TEXT NOT NULL,
    started_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, activity_type, activity_name)
);
