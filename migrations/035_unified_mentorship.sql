-- D13: new guild-scoped engagements; old mentorships remain unbound history.
-- Do not infer guilds, import matches, reinterpret naive legacy dates or grant historical XP.
ALTER TABLE mentorships
    ADD COLUMN IF NOT EXISTS guild_id BIGINT,
    ADD COLUMN IF NOT EXISTS request_message TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS outcome VARCHAR(16),
    ADD COLUMN IF NOT EXISTS reward_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS created_at_utc TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at_utc TIMESTAMPTZ;
-- New rows/transitions fill UTC shadows explicitly; legacy naive dates remain unchanged/unknown.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'mentorship_scoped_state' AND conrelid = 'mentorships'::regclass) THEN
        ALTER TABLE mentorships ADD CONSTRAINT mentorship_scoped_state CHECK (
            guild_id IS NULL OR (guild_id > 0 AND mentor_id IS NOT NULL AND mentee_id IS NOT NULL
                AND mentor_id <> mentee_id AND status IS NOT NULL AND status IN ('pending','active','completed','cancelled','declined')
                AND (outcome IS NULL OR outcome IN ('successful','incomplete','cancelled'))));
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS mentorship_live_pair
    ON mentorships(guild_id, LEAST(mentor_id, mentee_id), GREATEST(mentor_id, mentee_id))
    WHERE guild_id IS NOT NULL AND status IN ('pending','active');
CREATE INDEX IF NOT EXISTS mentorship_guild_status ON mentorships(guild_id, status, id);

CREATE TABLE IF NOT EXISTS mentor_registrations (
    guild_id BIGINT NOT NULL CHECK (guild_id > 0),
    user_id INTEGER NOT NULL REFERENCES users(id),
    skills TEXT[] NOT NULL DEFAULT '{}',
    categories TEXT[] NOT NULL DEFAULT '{}',
    bio TEXT NOT NULL DEFAULT '',
    available BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(guild_id,user_id)
);
-- Preferences are per participant, not a mentor-only flag: mentees may also opt in.
CREATE TABLE IF NOT EXISTS mentorship_notification_preferences (
    guild_id BIGINT NOT NULL CHECK (guild_id > 0),
    user_id INTEGER NOT NULL REFERENCES users(id),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    revision BIGINT NOT NULL DEFAULT 0,
    last_sent_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(guild_id,user_id)
);
CREATE TABLE IF NOT EXISTS mentorship_awards (
    mentorship_id INTEGER NOT NULL REFERENCES mentorships(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    points INTEGER NOT NULL CHECK (points IN (25,50)),
    awarded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(mentorship_id,user_id)
);
-- mentorship_matches is retained untouched as a legacy archive. No runtime writer/poller uses it.
