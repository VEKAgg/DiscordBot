-- Configurable access tiers: bot-wide operator settings and per-guild access roles.
-- Migration: 041_configurable_access.sql
-- Replaces the BOT_OPERATOR_IDS / ADMIN_IDS / STAFF_IDS / ... environment allowlists.

-- Bot-wide (platform scope) key/value settings. JSONB so values stay typed and extensible.
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by BIGINT
);

-- Per-guild access roles (server scope). Empty list = tier not configured.
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS admin_role_ids BIGINT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS staff_role_ids BIGINT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS perk_role_ids BIGINT[] NOT NULL DEFAULT '{}';
