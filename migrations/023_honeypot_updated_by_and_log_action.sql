-- VEKA Discord Bot - Honeypot schema fixes
-- Migration: 023_honeypot_updated_by_and_log_action.sql
-- Created: 2026-10-05
--
-- 1. /honeypot enable|disable|edit write honeypots.updated_by, which 014 never created (audit M-13).
-- 2. /honeypot create offers a "Log Only" action ('log') that the 014 CHECK constraint rejected.

ALTER TABLE honeypots ADD COLUMN IF NOT EXISTS updated_by BIGINT;

ALTER TABLE honeypots DROP CONSTRAINT IF EXISTS honeypots_action_type_check;
ALTER TABLE honeypots ADD CONSTRAINT honeypots_action_type_check
    CHECK (action_type IN ('softban', 'ban', 'timeout', 'role', 'log'));
