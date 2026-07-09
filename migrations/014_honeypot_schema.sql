-- Honeypot Anti-Spam System
-- Trap channels that automatically punish spam bots on message.

CREATE TABLE IF NOT EXISTS honeypots (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    action_type VARCHAR(20) NOT NULL DEFAULT 'softban'
        CHECK (action_type IN ('softban', 'ban', 'timeout', 'role')),
    delete_message_days INT,
    timeout_hours INT,
    role_id BIGINT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_honeypots_guild_channel
    ON honeypots (guild_id, channel_id);

CREATE TABLE IF NOT EXISTS honeypot_logging_config (
    guild_id BIGINT PRIMARY KEY,
    logging_channel_id BIGINT,
    notification_role_id BIGINT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS honeypot_events (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    honeypot_id INT NOT NULL REFERENCES honeypots(id) ON DELETE CASCADE,
    action_type VARCHAR(20) NOT NULL,
    action_result VARCHAR(10) NOT NULL DEFAULT 'success'
        CHECK (action_result IN ('success', 'failed')),
    message_id BIGINT,
    message_content_preview TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_honeypot_events_guild_created
    ON honeypot_events (guild_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_honeypot_events_user
    ON honeypot_events (user_id);
