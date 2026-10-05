-- VEKA Discord Bot - Listing expiry warnings are sent once
-- Migration: 026_listing_expiry_warning.sql
-- Created: 2026-10-05
--
-- check_price_drops DMed every seller with a listing older than 30 days every 6 hours, forever
-- (audit M-10). Record when the warning was sent so it goes out once per listing age cycle.

ALTER TABLE marketplace_listings ADD COLUMN IF NOT EXISTS expiry_warned_at TIMESTAMPTZ;
