-- Default-on module switches; settings/consent remain independent.
CREATE TABLE IF NOT EXISTS guild_modules (
    guild_id BIGINT PRIMARY KEY,
    disabled TEXT[] NOT NULL DEFAULT '{}',
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    updated_by BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
