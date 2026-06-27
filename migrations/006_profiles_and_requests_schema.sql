-- VEKA Discord Bot - Profiles and Connection Request Enhancements
-- Migration: 006_profiles_and_requests_schema.sql
-- Created: 2026-06-02

-- Add missing profile columns for bio and links, and enforce one profile per user.
ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS bio TEXT,
    ADD COLUMN IF NOT EXISTS links TEXT;

ALTER TABLE profiles
    ADD CONSTRAINT unique_profile_user_id UNIQUE (user_id);

-- Ensure the app can prevent duplicate active connection requests.
ALTER TABLE connection_requests
    ADD CONSTRAINT unique_pending_connection_request UNIQUE (requester_id, recipient_id, status);
