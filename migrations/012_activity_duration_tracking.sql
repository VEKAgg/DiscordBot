-- Activity duration tracking for streaming, gaming, and listening stats

ALTER TABLE users ADD COLUMN IF NOT EXISTS total_streaming_minutes INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_gaming_minutes INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_listening_minutes INTEGER DEFAULT 0;
