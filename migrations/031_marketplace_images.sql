-- Durable marketplace images. Signed Discord URLs are references, not storage.
CREATE TABLE IF NOT EXISTS marketplace_listing_images (
    listing_id VARCHAR(50) NOT NULL REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL CHECK (position BETWEEN 0 AND 3),
    content_type VARCHAR(32) NOT NULL DEFAULT 'image/webp',
    sha256 CHAR(64) NOT NULL,
    width INTEGER NOT NULL CHECK (width BETWEEN 1 AND 1600),
    height INTEGER NOT NULL CHECK (height BETWEEN 1 AND 1600),
    bytes BYTEA NOT NULL CHECK (octet_length(bytes) <= 2097152),
    source_message_id BIGINT,
    source_attachment_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (listing_id, position)
);
CREATE INDEX IF NOT EXISTS idx_marketplace_image_digest ON marketplace_listing_images(listing_id, sha256);
ALTER TABLE marketplace_listings ADD COLUMN IF NOT EXISTS image_missing BOOLEAN NOT NULL DEFAULT FALSE;
