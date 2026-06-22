-- Production indexes for VEKA v1 hot paths

-- Discord User ID is frequently queried
CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id);

-- Guild Config looks up by guild_id
CREATE INDEX IF NOT EXISTS idx_guild_config_guild_id ON guild_config(guild_id);

-- Connection requests heavily query recipient_id and status
CREATE INDEX IF NOT EXISTS idx_connection_requests_recipient_status ON connection_requests(recipient_id, status);

-- Marketplace listings filter by seller, status, and category
CREATE INDEX IF NOT EXISTS idx_marketplace_listings_seller_id ON marketplace_listings(seller_id);
CREATE INDEX IF NOT EXISTS idx_marketplace_listings_status_cat ON marketplace_listings(status, category_id);

-- RSS caching
CREATE INDEX IF NOT EXISTS idx_rss_cache_published_at ON rss_cache(published_at DESC);

-- Resource timestamp
CREATE INDEX IF NOT EXISTS idx_resources_created_at ON resources(created_at DESC);
