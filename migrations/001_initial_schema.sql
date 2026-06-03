-- VEKA Discord Bot - Initial PostgreSQL Schema
-- Migration: 001_initial_schema.sql
-- Created: 2026-02-12

-- Enable UUID extension for unique identifiers
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users (central identity table)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    discord_id VARCHAR(20) UNIQUE NOT NULL,
    username VARCHAR(100),
    points INTEGER DEFAULT 0,
    experience INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    quiz_score INTEGER DEFAULT 0,
    challenge_score INTEGER DEFAULT 0,
    daily_streak INTEGER DEFAULT 0,
    last_daily TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Profiles (Networking feature)
CREATE TABLE profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    skills TEXT,
    experience TEXT,
    looking_for TEXT,
    last_updated TIMESTAMP DEFAULT NOW()
);

-- Connections (Networking)
CREATE TABLE connections (
    id SERIAL PRIMARY KEY,
    user1_id INTEGER REFERENCES users(id),
    user2_id INTEGER REFERENCES users(id),
    connected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user1_id, user2_id)
);

CREATE TABLE connection_requests (
    id SERIAL PRIMARY KEY,
    requester_id INTEGER REFERENCES users(id),
    recipient_id INTEGER REFERENCES users(id),
    message TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Quizzes (Quiz System)
CREATE TABLE quizzes (
    id SERIAL PRIMARY KEY,
    category VARCHAR(100) NOT NULL,
    difficulty VARCHAR(20) NOT NULL,
    question TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    wrong_answers TEXT[],
    explanation TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE quiz_attempts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    quiz_id INTEGER REFERENCES quizzes(id),
    correct BOOLEAN NOT NULL,
    time_taken FLOAT,
    is_daily BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Mentorships
CREATE TABLE mentorships (
    id SERIAL PRIMARY KEY,
    mentor_id INTEGER REFERENCES users(id),
    mentee_id INTEGER REFERENCES users(id),
    category VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT different_users CHECK (mentor_id != mentee_id)
);

-- Workshops
CREATE TABLE workshops (
    id VARCHAR(50) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    workshop_date TIMESTAMP NOT NULL,
    duration INTEGER NOT NULL,
    max_participants INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE workshop_participants (
    workshop_id VARCHAR(50) REFERENCES workshops(id),
    user_id INTEGER REFERENCES users(id),
    registered_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (workshop_id, user_id)
);

-- Portfolios
CREATE TABLE portfolios (
    id VARCHAR(50) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    url VARCHAR(500),
    tags TEXT[],
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Resources (RSS caching)
CREATE TABLE resources (
    id SERIAL PRIMARY KEY,
    category VARCHAR(100),
    title VARCHAR(500),
    url VARCHAR(500),
    description TEXT,
    author VARCHAR(255),
    published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for Performance
CREATE INDEX idx_users_discord_id ON users(discord_id);
CREATE INDEX idx_quizzes_category ON quizzes(category);
CREATE INDEX idx_quizzes_difficulty ON quizzes(difficulty);
CREATE INDEX idx_quiz_attempts_user_id ON quiz_attempts(user_id);
CREATE INDEX idx_quiz_attempts_created ON quiz_attempts(created_at);
CREATE INDEX idx_mentorships_mentor ON mentorships(mentor_id);
CREATE INDEX idx_mentorships_mentee ON mentorships(mentee_id);
CREATE INDEX idx_mentorships_status ON mentorships(status);
CREATE INDEX idx_profiles_user_id ON profiles(user_id);
CREATE INDEX idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX idx_connections_user1 ON connections(user1_id);
CREATE INDEX idx_connections_user2 ON connections(user2_id);
CREATE INDEX idx_connection_requests_recipient ON connection_requests(recipient_id);
CREATE INDEX idx_connection_requests_status ON connection_requests(status);
CREATE INDEX idx_workshops_date ON workshops(workshop_date);
