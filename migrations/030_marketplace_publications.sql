-- Keep global listings, but publish only into the invoking guild's configured destination.
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS marketplace_channel_id BIGINT;

-- A manual forum post may not include a parsable price. Keep it pending review,
-- never fabricate a price. The existing positive-price CHECK still validates known prices.
ALTER TABLE marketplace_listings ALTER COLUMN price DROP NOT NULL;
-- A GUI forum post does not establish an item's condition; never claim it is 'good'.
ALTER TABLE marketplace_listings DROP CONSTRAINT IF EXISTS valid_condition;
ALTER TABLE marketplace_listings ADD CONSTRAINT valid_condition
    CHECK (condition IN ('new', 'like_new', 'good', 'fair', 'poor', 'unknown'));
ALTER TABLE marketplace_listings
    ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'command',
    ADD COLUMN IF NOT EXISTS thread_id BIGINT,
    ADD COLUMN IF NOT EXISTS guild_id BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_marketplace_thread ON marketplace_listings(thread_id);

CREATE TABLE IF NOT EXISTS marketplace_publications (
    guild_id BIGINT NOT NULL,
    listing_id VARCHAR(50) NOT NULL REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    thread_id BIGINT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, listing_id)
);

CREATE TABLE IF NOT EXISTS marketplace_cms_publications (
    listing_id VARCHAR(50) PRIMARY KEY REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
