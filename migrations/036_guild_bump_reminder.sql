-- Explicit server opt-in; never seed reminders for existing guilds.
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS bump_reminder_enabled BOOLEAN NOT NULL DEFAULT FALSE;
