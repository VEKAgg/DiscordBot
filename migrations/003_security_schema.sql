-- VEKA Discord Bot - Security Schema Migration
-- Migration: 003_security_schema.sql
-- Created: 2026-02-12

-- Audit Logs Table
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL,
    action VARCHAR(100) NOT NULL,
    details JSONB,
    guild_id VARCHAR(20),
    channel_id VARCHAR(20),
    severity VARCHAR(20) DEFAULT 'info', -- info, warning, critical
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for audit logs
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at);
CREATE INDEX idx_audit_logs_severity ON audit_logs(severity);

-- User Security Tracking
CREATE TABLE user_security (
    user_id VARCHAR(20) PRIMARY KEY,
    failed_commands INTEGER DEFAULT 0,
    warnings INTEGER DEFAULT 0,
    last_warning TIMESTAMP,
    is_blocked BOOLEAN DEFAULT FALSE,
    blocked_until TIMESTAMP,
    blocked_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Security Events (blocked users, etc.)
CREATE TABLE security_events (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL,
    event_type VARCHAR(50) NOT NULL, -- blocked, warned, rate_limited, etc.
    reason TEXT,
    triggered_by VARCHAR(20), -- moderator/admin who triggered
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_security_events_user ON security_events(user_id);
CREATE INDEX idx_security_events_type ON security_events(event_type);
CREATE INDEX idx_security_events_created ON security_events(created_at);
