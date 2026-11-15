-- Discord observations and a durable, leased delivery outbox. Core owns public state.
ALTER TABLE marketplace_listings
    ADD COLUMN IF NOT EXISTS origin_channel_id BIGINT,
    ADD COLUMN IF NOT EXISTS source_message_id BIGINT,
    ADD COLUMN IF NOT EXISTS audience TEXT NOT NULL DEFAULT 'private' CHECK (audience IN ('private','community','public')),
    ADD COLUMN IF NOT EXISTS core_listing_id UUID,
    ADD COLUMN IF NOT EXISTS core_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS core_visible BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS core_moderation TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS core_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS currency CHAR(3) NOT NULL DEFAULT 'USD';

CREATE TABLE IF NOT EXISTS marketplace_core_bindings (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    body JSONB NOT NULL,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS marketplace_core_sources (
    listing_id VARCHAR(50) PRIMARY KEY REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
    observation_hash TEXT,
    tombstone BOOLEAN NOT NULL DEFAULT FALSE,
    source_id UUID,
    accepted_revision BIGINT NOT NULL DEFAULT 0,
    UNIQUE (guild_id, channel_id, message_id)
);
CREATE TABLE IF NOT EXISTS marketplace_core_outbox (
    event_id UUID PRIMARY KEY,
    listing_id VARCHAR(50) NOT NULL REFERENCES marketplace_core_sources(listing_id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    body JSONB NOT NULL,
    wire_body JSONB,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','blocked','dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_id UUID,
    lease_until TIMESTAMPTZ,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ,
    UNIQUE (listing_id, revision)
);
CREATE INDEX IF NOT EXISTS marketplace_outbox_due ON marketplace_core_outbox(next_attempt_at)
    WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS marketplace_core_outbox_images (
    event_id UUID NOT NULL REFERENCES marketplace_core_outbox(event_id) ON DELETE CASCADE,
    position SMALLINT NOT NULL CHECK (position BETWEEN 0 AND 7),
    attachment_id BIGINT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    bytes BYTEA NOT NULL CHECK (octet_length(bytes) <= 2097152),
    asset_id UUID,
    PRIMARY KEY (event_id, position)
);
CREATE TABLE IF NOT EXISTS marketplace_core_consumer (
    id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    cursor TEXT NOT NULL DEFAULT '',
    lease_id UUID,
    lease_until TIMESTAMPTZ,
    reconcile_cursor TEXT NOT NULL DEFAULT '',
    discord_cursor TEXT NOT NULL DEFAULT '',
    resnapshot BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO marketplace_core_consumer(id) VALUES (TRUE) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS marketplace_core_events (
    event_id UUID PRIMARY KEY,
    cursor TEXT NOT NULL,
    body JSONB NOT NULL,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS marketplace_core_publications (
    publication_key TEXT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL UNIQUE,
    thread_id BIGINT,
    listing_id UUID NOT NULL,
    canonical_version BIGINT NOT NULL DEFAULT 0,
    removed BOOLEAN NOT NULL DEFAULT FALSE
);
ALTER TABLE marketplace_categories ADD COLUMN IF NOT EXISTS core_id UUID UNIQUE;
ALTER TABLE marketplace_categories DROP CONSTRAINT IF EXISTS marketplace_categories_name_key;
ALTER TABLE marketplace_listing_images DROP CONSTRAINT IF EXISTS marketplace_listing_images_position_check;
ALTER TABLE marketplace_listing_images ADD CONSTRAINT marketplace_listing_images_position_check CHECK (position BETWEEN 0 AND 7);
DROP TABLE IF EXISTS marketplace_cms_publications;
