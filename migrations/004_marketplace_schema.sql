-- VEKA Discord Bot - Marketplace Schema
-- Migration: 004_marketplace_schema.sql
-- Created: 2026-02-12

-- Marketplace Categories
CREATE TABLE marketplace_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    emoji VARCHAR(10),
    parent_id INTEGER REFERENCES marketplace_categories(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert default categories
INSERT INTO marketplace_categories (name, description, emoji) VALUES
('Electronics', 'Phones, laptops, gadgets, and electronic accessories', '💻'),
('Gaming', 'Video games, consoles, gaming accessories', '🎮'),
('Clothing', 'Apparel, shoes, accessories', '👕'),
('Books', 'Physical books, e-books, textbooks', '📚'),
('Services', 'Freelance services, tutoring, consulting', '💼'),
('Collectibles', 'Trading cards, figurines, memorabilia', '🏆'),
('Home & Garden', 'Furniture, decor, appliances', '🏠'),
('Vehicles', 'Cars, bikes, parts', '🚗'),
('Other', 'Miscellaneous items', '📦');

-- Marketplace Listings
CREATE TABLE marketplace_listings (
    id VARCHAR(50) PRIMARY KEY,
    seller_id INTEGER REFERENCES users(id) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    price DECIMAL(10,2) NOT NULL CHECK (price > 0 AND price <= 999999.99),
    original_price DECIMAL(10,2), -- For showing discounts
    category_id INTEGER REFERENCES marketplace_categories(id),
    condition VARCHAR(50) NOT NULL, -- new, like_new, good, fair, poor
    images TEXT[], -- Array of image URLs
    status VARCHAR(20) DEFAULT 'active', -- active, sold, withdrawn, pending_review
    views INTEGER DEFAULT 0,
    is_negotiable BOOLEAN DEFAULT FALSE,
    location VARCHAR(100), -- Optional location info
    tags TEXT[], -- For searchability
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    sold_at TIMESTAMP,
    CONSTRAINT valid_condition CHECK (condition IN ('new', 'like_new', 'good', 'fair', 'poor'))
);

-- Listing Views (Track unique views)
CREATE TABLE marketplace_views (
    listing_id VARCHAR(50) REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    viewed_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (listing_id, user_id)
);

-- Watchlist/Favorites
CREATE TABLE marketplace_watchlist (
    user_id INTEGER REFERENCES users(id),
    listing_id VARCHAR(50) REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, listing_id)
);

-- Offers/Bids (For negotiable items)
CREATE TABLE marketplace_offers (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(50) REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    buyer_id INTEGER REFERENCES users(id),
    offered_price DECIMAL(10,2) NOT NULL,
    message TEXT,
    status VARCHAR(20) DEFAULT 'pending', -- pending, accepted, rejected, expired
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    responded_at TIMESTAMP
);

-- Marketplace Transactions
CREATE TABLE marketplace_transactions (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(50) REFERENCES marketplace_listings(id),
    seller_id INTEGER REFERENCES users(id),
    buyer_id INTEGER REFERENCES users(id),
    agreed_price DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending', -- pending, completed, cancelled, disputed, refunded
    payment_method VARCHAR(50),
    payment_status VARCHAR(20) DEFAULT 'pending', -- pending, confirmed, failed, refunded
    escrow_status VARCHAR(20) DEFAULT 'none', -- none, held, released
    notes TEXT,
    cancellation_reason TEXT,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Reviews and Ratings
CREATE TABLE marketplace_reviews (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER REFERENCES marketplace_transactions(id),
    reviewer_id INTEGER REFERENCES users(id),
    reviewee_id INTEGER REFERENCES users(id),
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    is_buyer_review BOOLEAN DEFAULT TRUE, -- True if buyer reviewing seller, False if seller reviewing buyer
    helpful_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(transaction_id, reviewer_id)
);

-- Review Helpfulness (Users marking reviews as helpful)
CREATE TABLE marketplace_review_votes (
    review_id INTEGER REFERENCES marketplace_reviews(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    is_helpful BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (review_id, user_id)
);

-- Seller Statistics (Cached for performance)
CREATE TABLE marketplace_seller_stats (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    total_sales INTEGER DEFAULT 0,
    total_revenue DECIMAL(12,2) DEFAULT 0,
    average_rating DECIMAL(2,1) DEFAULT 0,
    review_count INTEGER DEFAULT 0,
    active_listings INTEGER DEFAULT 0,
    response_time_hours INTEGER, -- Average response time
    last_sale_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Fraud Detection - Flagged Transactions
CREATE TABLE marketplace_fraud_flags (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(50) REFERENCES marketplace_listings(id),
    transaction_id INTEGER REFERENCES marketplace_transactions(id),
    user_id INTEGER REFERENCES users(id),
    flag_type VARCHAR(50) NOT NULL, -- suspicious_price, rapid_transactions, self_purchase, etc.
    severity VARCHAR(20) DEFAULT 'low', -- low, medium, high
    details JSONB,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_by INTEGER REFERENCES users(id),
    resolution_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

-- Indexes for Performance
CREATE INDEX idx_listings_seller ON marketplace_listings(seller_id);
CREATE INDEX idx_listings_category ON marketplace_listings(category_id);
CREATE INDEX idx_listings_status ON marketplace_listings(status);
CREATE INDEX idx_listings_price ON marketplace_listings(price);
CREATE INDEX idx_listings_created ON marketplace_listings(created_at);
CREATE INDEX idx_listings_condition ON marketplace_listings(condition);
CREATE INDEX idx_listings_title ON marketplace_listings USING gin(to_tsvector('english', title));
CREATE INDEX idx_listings_description ON marketplace_listings USING gin(to_tsvector('english', description));

CREATE INDEX idx_transactions_seller ON marketplace_transactions(seller_id);
CREATE INDEX idx_transactions_buyer ON marketplace_transactions(buyer_id);
CREATE INDEX idx_transactions_status ON marketplace_transactions(status);
CREATE INDEX idx_transactions_created ON marketplace_transactions(created_at);

CREATE INDEX idx_offers_listing ON marketplace_offers(listing_id);
CREATE INDEX idx_offers_buyer ON marketplace_offers(buyer_id);
CREATE INDEX idx_offers_status ON marketplace_offers(status);

CREATE INDEX idx_reviews_reviewee ON marketplace_reviews(reviewee_id);
CREATE INDEX idx_reviews_rating ON marketplace_reviews(rating);
CREATE INDEX idx_reviews_created ON marketplace_reviews(created_at);

CREATE INDEX idx_watchlist_user ON marketplace_watchlist(user_id);
CREATE INDEX idx_watchlist_listing ON marketplace_watchlist(listing_id);

CREATE INDEX idx_fraud_flags_user ON marketplace_fraud_flags(user_id);
CREATE INDEX idx_fraud_flags_severity ON marketplace_fraud_flags(severity);
CREATE INDEX idx_fraud_flags_resolved ON marketplace_fraud_flags(is_resolved);

-- Triggers for updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_marketplace_listings_updated_at
    BEFORE UPDATE ON marketplace_listings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_marketplace_reviews_updated_at
    BEFORE UPDATE ON marketplace_reviews
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_marketplace_seller_stats_updated_at
    BEFORE UPDATE ON marketplace_seller_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
