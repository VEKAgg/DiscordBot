-- Track per-user footer state for dynamic footer system
-- Stores contribution prompt cooldown and tip rotation index
CREATE TABLE IF NOT EXISTS user_footer_state (
    user_id                     BIGINT PRIMARY KEY,
    last_contribution_prompt    TIMESTAMP,
    tip_index                   INT DEFAULT 0
);
