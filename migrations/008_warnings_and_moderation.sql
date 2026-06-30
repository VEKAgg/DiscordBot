-- VEKA Discord Bot - Warnings & Moderation Schema
-- Migration: 008_warnings_and_moderation.sql
-- Created: 2026-06-29

-- Warnings table
CREATE TABLE IF NOT EXISTS warnings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    moderator_id INTEGER REFERENCES users(id),
    reason TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_warnings_user_id ON warnings(user_id);
CREATE INDEX IF NOT EXISTS idx_warnings_moderator_id ON warnings(moderator_id);
CREATE INDEX IF NOT EXISTS idx_warnings_created_at ON warnings(created_at);
