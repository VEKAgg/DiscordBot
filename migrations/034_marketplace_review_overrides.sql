-- Preserve staff corrections/approval across silent forum re-ingestion.
-- These fields are independent of archived/locked thread lifecycle state.
ALTER TABLE marketplace_listings
    ADD COLUMN IF NOT EXISTS price_override BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS forum_review_status TEXT;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'marketplace_forum_review_status_valid'
                   AND conrelid = 'marketplace_listings'::regclass) THEN
        ALTER TABLE marketplace_listings ADD CONSTRAINT marketplace_forum_review_status_valid
            CHECK (forum_review_status IS NULL OR forum_review_status IN ('active', 'removed'));
    END IF;
END $$;
