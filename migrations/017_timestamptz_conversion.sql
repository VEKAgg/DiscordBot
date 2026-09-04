-- VEKA Discord Bot - Convert all legacy TIMESTAMP columns to TIMESTAMPTZ
-- Migration: 017_timestamptz_conversion.sql
-- All future migrations must use TIMESTAMPTZ DEFAULT NOW().
-- Uses DO blocks to skip tables that may not exist (disabled stubs).

-- users
DO $$ BEGIN ALTER TABLE users ALTER COLUMN last_daily TYPE TIMESTAMPTZ USING last_daily AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE users ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE users ALTER COLUMN last_active TYPE TIMESTAMPTZ USING last_active AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- profiles
DO $$ BEGIN ALTER TABLE profiles ALTER COLUMN last_updated TYPE TIMESTAMPTZ USING last_updated AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- connections
DO $$ BEGIN ALTER TABLE connections ALTER COLUMN connected_at TYPE TIMESTAMPTZ USING connected_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- connection_requests
DO $$ BEGIN ALTER TABLE connection_requests ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- quizzes (may not exist if disabled)
DO $$ BEGIN ALTER TABLE quizzes ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- quiz_attempts (may not exist if disabled)
DO $$ BEGIN ALTER TABLE quiz_attempts ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- mentorships
DO $$ BEGIN ALTER TABLE mentorships ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE mentorships ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- workshops (may not exist if disabled)
DO $$ BEGIN ALTER TABLE workshops ALTER COLUMN workshop_date TYPE TIMESTAMPTZ USING workshop_date AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE workshops ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- workshop_participants (may not exist if disabled)
DO $$ BEGIN ALTER TABLE workshop_participants ALTER COLUMN registered_at TYPE TIMESTAMPTZ USING registered_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- portfolios
DO $$ BEGIN ALTER TABLE portfolios ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE portfolios ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- resources
DO $$ BEGIN ALTER TABLE resources ALTER COLUMN published_at TYPE TIMESTAMPTZ USING published_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE resources ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- audit_logs
DO $$ BEGIN ALTER TABLE audit_logs ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- user_security
DO $$ BEGIN ALTER TABLE user_security ALTER COLUMN last_warning TYPE TIMESTAMPTZ USING last_warning AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE user_security ALTER COLUMN blocked_until TYPE TIMESTAMPTZ USING blocked_until AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE user_security ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE user_security ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- security_events
DO $$ BEGIN ALTER TABLE security_events ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING expires_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE security_events ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_categories
DO $$ BEGIN ALTER TABLE marketplace_categories ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_listings
DO $$ BEGIN ALTER TABLE marketplace_listings ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_listings ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_listings ALTER COLUMN sold_at TYPE TIMESTAMPTZ USING sold_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_views
DO $$ BEGIN ALTER TABLE marketplace_views ALTER COLUMN viewed_at TYPE TIMESTAMPTZ USING viewed_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_watchlist
DO $$ BEGIN ALTER TABLE marketplace_watchlist ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_offers
DO $$ BEGIN ALTER TABLE marketplace_offers ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING expires_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_offers ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_offers ALTER COLUMN responded_at TYPE TIMESTAMPTZ USING responded_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_transactions
DO $$ BEGIN ALTER TABLE marketplace_transactions ALTER COLUMN completed_at TYPE TIMESTAMPTZ USING completed_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_transactions ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_reviews
DO $$ BEGIN ALTER TABLE marketplace_reviews ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_reviews ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_review_votes
DO $$ BEGIN ALTER TABLE marketplace_review_votes ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_seller_stats
DO $$ BEGIN ALTER TABLE marketplace_seller_stats ALTER COLUMN last_sale_at TYPE TIMESTAMPTZ USING last_sale_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_seller_stats ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- marketplace_fraud_flags
DO $$ BEGIN ALTER TABLE marketplace_fraud_flags ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE marketplace_fraud_flags ALTER COLUMN resolved_at TYPE TIMESTAMPTZ USING resolved_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- rss_cache (may have been dropped/recreated by 005b)
DO $$ BEGIN ALTER TABLE rss_cache ALTER COLUMN cached_at TYPE TIMESTAMPTZ USING cached_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE rss_cache ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING expires_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE rss_cache ALTER COLUMN published_at TYPE TIMESTAMPTZ USING published_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE rss_cache ALTER COLUMN fetched_at TYPE TIMESTAMPTZ USING fetched_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- guild_config
DO $$ BEGIN ALTER TABLE guild_config ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE guild_config ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- schema_migrations
DO $$ BEGIN ALTER TABLE schema_migrations ALTER COLUMN applied_at TYPE TIMESTAMPTZ USING applied_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- warnings
DO $$ BEGIN ALTER TABLE warnings ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- user_footer_state
DO $$ BEGIN ALTER TABLE user_footer_state ALTER COLUMN last_contribution_prompt TYPE TIMESTAMPTZ USING last_contribution_prompt AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- user_activity_log
DO $$ BEGIN ALTER TABLE user_activity_log ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- user_rpg_roles
DO $$ BEGIN ALTER TABLE user_rpg_roles ALTER COLUMN last_evaluated TYPE TIMESTAMPTZ USING last_evaluated AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- user_activity_details
DO $$ BEGIN ALTER TABLE user_activity_details ALTER COLUMN last_seen TYPE TIMESTAMPTZ USING last_seen AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;

-- user_active_activities
DO $$ BEGIN ALTER TABLE user_active_activities ALTER COLUMN started_at TYPE TIMESTAMPTZ USING started_at AT TIME ZONE 'UTC'; EXCEPTION WHEN undefined_table THEN NULL; END $$;
