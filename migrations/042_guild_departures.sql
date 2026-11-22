-- 042: remember when the bot left a server; nightly maintenance deletes that server's data 30 days
-- later unless the bot was added back. Member activity tracking is untouched: it stays server opt-in +
-- member opt-out (037, owner decision 2026-10-11, confirmed 2026-11-22).
-- Idempotent.

CREATE TABLE IF NOT EXISTS bot_guild_departures (
    guild_id BIGINT PRIMARY KEY,
    left_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
