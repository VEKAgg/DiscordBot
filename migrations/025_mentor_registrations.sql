-- VEKA Discord Bot - Mentor registrations are not mentorships
-- Migration: 025_mentor_registrations.sql
-- Created: 2026-10-05
--
-- /mentor apply stored registrations as mentorship_matches rows with mentor_id = mentee_id and
-- status 'active', with no unique key. /mentor end could then "complete" the self-match and award XP
-- twice to the same user, repeatably; weekly check-ins DMed people about themselves (audit M-18).

-- Existing self-matches become registrations; keep one per (guild, mentor).
UPDATE mentorship_matches SET status = 'registered' WHERE mentor_id = mentee_id;

DELETE FROM mentorship_matches a
USING mentorship_matches b
WHERE a.mentor_id = a.mentee_id AND b.mentor_id = b.mentee_id
  AND a.guild_id = b.guild_id AND a.mentor_id = b.mentor_id
  AND a.id > b.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mentor_registration_unique
    ON mentorship_matches (guild_id, mentor_id) WHERE mentor_id = mentee_id;
