CREATE SCHEMA IF NOT EXISTS poker_private;
REVOKE ALL ON SCHEMA poker_private FROM PUBLIC;
SET search_path = poker_private;

CREATE TABLE IF NOT EXISTS rooms (
    code TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_events (
    id BIGSERIAL PRIMARY KEY, code TEXT NOT NULL, revision INTEGER NOT NULL,
    kind TEXT NOT NULL, command_id TEXT, player_id TEXT,
    created_at TEXT NOT NULL DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS completed_hands (
    id BIGSERIAL UNIQUE NOT NULL, code TEXT NOT NULL, hand_id TEXT NOT NULL, payload TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    PRIMARY KEY(code, hand_id)
);
CREATE INDEX IF NOT EXISTS completed_hands_room_id ON completed_hands(code, id);
CREATE TABLE IF NOT EXISTS training_profiles (
    profile_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS training_decisions (
    id BIGSERIAL PRIMARY KEY, profile_id TEXT NOT NULL, command_id TEXT NOT NULL,
    request_json TEXT NOT NULL, payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(profile_id, command_id)
);
CREATE TABLE IF NOT EXISTS training_questions (
    sequence BIGSERIAL UNIQUE NOT NULL, question_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
    source_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
    answer_json TEXT NOT NULL, UNIQUE(profile_id, source_id, kind)
);
CREATE TABLE IF NOT EXISTS training_attempts (
    id BIGSERIAL PRIMARY KEY, profile_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    question_id TEXT NOT NULL, request_json TEXT NOT NULL, payload TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK(correct IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(profile_id, attempt_id)
);
CREATE INDEX IF NOT EXISTS training_question_profile ON training_questions(profile_id);
CREATE INDEX IF NOT EXISTS training_attempt_question ON training_attempts(profile_id, question_id, id);

ALTER TABLE rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE room_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE completed_hands ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_attempts ENABLE ROW LEVEL SECURITY;
