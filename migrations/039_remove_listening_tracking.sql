-- Listening tracking was removed; do not retain obsolete member listening data.
ALTER TABLE users DROP COLUMN IF EXISTS total_listening_minutes;
DELETE FROM user_activity_details WHERE activity_type = 'listening';
DELETE FROM user_active_activities WHERE activity_type = 'listening';
