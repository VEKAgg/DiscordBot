# VEKA Discord Bot - PostgreSQL Migration & Development Plan

**Date:** 2026-02-12  
**Status:** Ready for Immediate Implementation  
**Priority:** IMMEDIATE

---

## Executive Summary

This plan outlines the migration from MongoDB to PostgreSQL and aligns with the original development roadmap. Since discrepancies have been fixed, this plan focuses on:

1. **Immediate PostgreSQL migration** (This week)
2. **Core feature stabilization** (Quiz, Mentorship, Networking, Workshops, Portfolio, Gamification)
3. **Future expansion** based on original Plan.md features

---

## Phase 1: PostgreSQL Migration (IMMEDIATE - Week 1)

### 1.1 Database Schema

**File:** `migrations/001_initial_schema.sql`

```sql
-- Users (central identity)
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
CREATE INDEX idx_workshops_date ON workshops(workshop_date);
```

### 1.2 Technology Stack

**Remove:**
- `motor` - MongoDB driver
- `pymongo`

**Add:**
```txt
# Database
asyncpg>=0.29.0

# (Optional) If you want query building
databases[postgresql]>=0.8.0
```

### 1.3 Database Module Refactor

**Current:** `src/database/mongodb.py`
**New:** `src/database/database.py`

```python
import asyncpg
import logging
from src.config.config import DATABASE_URL

logger = logging.getLogger('VEKA.database')

class Database:
    def __init__(self):
        self.pool = None
    
    async def connect(self):
        """Initialize database connection pool"""
        self.pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("Database connection established")
    
    async def close(self):
        """Close database connection"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection closed")
    
    async def fetch_one(self, query: str, *args):
        """Fetch single record"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetch_many(self, query: str, *args):
        """Fetch multiple records"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def execute(self, query: str, *args):
        """Execute query (INSERT, UPDATE, DELETE)"""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def execute_many(self, query: str, args_list):
        """Execute query with multiple parameter sets"""
        async with self.pool.acquire() as conn:
            return await conn.executemany(query, args_list)

# Global instance
db = Database()

# Convenience functions
async def get_user(discord_id: str):
    """Get user by Discord ID or create if not exists"""
    user = await db.fetch_one(
        "SELECT * FROM users WHERE discord_id = $1", 
        discord_id
    )
    if not user:
        user = await db.fetch_one(
            """INSERT INTO users (discord_id) 
               VALUES ($1) 
               RETURNING *""",
            discord_id
        )
    return user

async def get_or_create_user(discord_id: str):
    """Alias for get_user"""
    return await get_user(discord_id)
```

### 1.4 Service Migration Checklist

**Migrate these files from MongoDB to PostgreSQL:**

- [ ] `src/services/quiz_service.py`
- [ ] `src/services/mentorship_service.py`
- [ ] `src/cogs/quiz.py`
- [ ] `src/cogs/networking.py`
- [ ] `src/cogs/mentorship.py`
- [ ] `src/cogs/workshops/workshop_manager.py`
- [ ] `src/cogs/portfolio/portfolio_manager.py`
- [ ] `src/cogs/gamification/gamification_manager.py`
- [ ] `src/cogs/feeds.py` (RSS caching)

**Query Pattern Examples:**

**Old (MongoDB):**
```python
user = await users.find_one({"discord_id": discord_id})
await users.insert_one({"discord_id": discord_id, "points": 0})
```

**New (PostgreSQL):**
```python
user = await db.fetch_one("SELECT * FROM users WHERE discord_id = $1", discord_id)
await db.execute("INSERT INTO users (discord_id) VALUES ($1)", discord_id)
```

### 1.5 Main.py Updates

```python
# In on_ready() event, replace:
# from src.database.mongodb import init_db
# await init_db()

# With:
from src.database.database import db
await db.connect()
```

---

## Phase 2: Core Features Stabilization (Week 2)

### 2.1 Currently Implemented (Working)

Based on your Plan.md Phase 1 & 2, these are complete:

1. **Welcome System** ✅
2. **Basic Commands** ✅ (`!hello`, `!ping`)
3. **Quiz System** ✅ (Categories, difficulty, scoring, leaderboard)
4. **Mentorship System** ✅ (Request, accept, complete)
5. **Networking** ✅ (Profiles, connections, requests)
6. **RSS Feeds** ✅ (Tech news, jobs, dev blogs)
7. **Gamification** ✅ (Points, levels, experience)
8. **Workshops** ✅ (Create, list, signup)
9. **Portfolio** ✅ (Add, list, view projects)
10. **Help System** ✅

### 2.2 Testing Required

Create basic tests for:

```python
# tests/test_database.py
import pytest
import asyncio
from src.database.database import db

@pytest.fixture
async def database():
    await db.connect()
    yield db
    await db.close()

@pytest.mark.asyncio
async def test_get_user(database):
    user = await get_user("123456789")
    assert user is not None
    assert user['discord_id'] == "123456789"
```

### 2.3 Docker Compose Update

Already done in .env.example section above.

---

## Phase 3: Feature Expansion (Week 3-4)

Based on Plan.md, implement these prioritized features:

### Priority 1: Community Features

1. **Leaderboard System**
   - Global points leaderboard
   - Quiz-specific leaderboard
   - Weekly/monthly rankings

2. **XP System Enhancement**
   - Message XP (already in gamification)
   - Voice channel XP
   - Activity streaks

3. **Auto-Moderation** 
   - Spam detection
   - Profanity filter
   - Rate limiting

### Priority 2: Content Features

4. **GitHub Integration**
   - `!github user <username>` - Show user stats
   - `!github repo <owner>/<repo>` - Show repo info

5. **News Integration**
   - Already have RSS, enhance with:
   - Custom feed subscriptions per channel
   - Keyword filtering

6. **Reminder System**
   - `!remindme <time> <message>`
   - Workshop reminders (already implemented)

### Priority 3: Utility Features

7. **Poll System**
   - `!poll "Question" "Option1" "Option2" ...`
   - Reaction-based voting

8. **Custom Commands**
   - `!custom add <name> <response>`
   - `!custom remove <name>`

9. **Server Analytics**
   - Member growth tracking
   - Activity heatmaps
   - Message statistics

---

## Phase 4: Advanced Features (Week 5+)

From Plan.md Phase 3 & 4:

### Dashboard (FastAPI)
- Web-based configuration
- Real-time statistics
- User management

### Price Tracking
- Crypto via CoinGecko
- Stocks via Alpha Vantage
- Product price alerts

### Game Integrations
- Genshin Impact
- Valorant
- Steam deals

### Streaming
- Twitch stream alerts
- YouTube upload notifications

---

## Implementation Roadmap

### Week 1: CRITICAL - PostgreSQL Migration

**Day 1-2:**
- [ ] Create PostgreSQL schema
- [ ] Set up asyncpg connection pool
- [ ] Create database abstraction layer
- [ ] Update docker-compose.yml

**Day 3-4:**
- [ ] Migrate quiz service
- [ ] Migrate mentorship service  
- [ ] Migrate networking cog
- [ ] Migrate gamification cog

**Day 5:**
- [ ] Migrate workshops
- [ ] Migrate portfolio
- [ ] Test all commands
- [ ] Remove MongoDB dependencies

### Week 2: Stabilization

- [ ] Write basic tests
- [ ] Add error handling
- [ ] Performance optimization
- [ ] Documentation update

### Week 3-4: Feature Expansion

- [ ] Implement Priority 1 features
- [ ] Implement Priority 2 features

### Week 5+: Advanced

- [ ] Dashboard (if needed)
- [ ] Price tracking
- [ ] Game integrations

---

## Environment Setup

### Local Development

```bash
# 1. Start PostgreSQL and Redis
docker-compose up -d postgres redis

# 2. Run migrations
psql -h localhost -U veka_user -d veka_bot -f migrations/001_initial_schema.sql

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run bot
python main.py
```

### Production Deployment

```bash
# Build and deploy
docker-compose up -d --build

# View logs
docker-compose logs -f discord-bot
```

---

## Key Design Decisions

### 1. No ORM
Using raw SQL with asyncpg for:
- Better performance
- Full SQL control
- Easier migration from MongoDB mindset

### 2. Parameterized Queries
All queries use `$1, $2...` placeholders for:
- SQL injection protection
- Automatic type handling

### 3. Connection Pooling
Built-in asyncpg pool for:
- Concurrent request handling
- Connection reuse
- Automatic cleanup

### 4. No Data Migration
Starting fresh with PostgreSQL since you mentioned no existing MongoDB data.

---

## Security Considerations

✅ **Already Protected:**
- SQL injection (parameterized queries)
- Environment variables for secrets
- Admin-only commands with decorator

**To Add:**
- Rate limiting on commands
- Input validation
- Audit logging

---

## Success Criteria

- [ ] All existing features work with PostgreSQL
- [ ] No MongoDB dependencies remaining
- [ ] Bot starts without errors
- [ ] All commands respond correctly
- [ ] Data persists across restarts
- [ ] Performance is equal or better than MongoDB

---

## Quick Start Commands

After migration:

```bash
# Test database connection
python -c "from src.database.database import db; import asyncio; asyncio.run(db.connect()); print('OK')"

# Run the bot
python main.py

# Test a command
!quiz start
!profile
!mentor list
```

---

**Ready to start immediately?** Begin with Week 1, Day 1 tasks. The schema is ready, and the migration pattern is clear. Focus on one service at a time, test thoroughly, then move to the next.

**Questions?** Prioritize getting PostgreSQL working with the existing features before adding new ones from Phase 3+.
