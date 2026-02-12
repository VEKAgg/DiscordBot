# VEKA Discord Bot - Code Analysis & Migration Plan

**Date:** 2026-02-12  
**Status:** Analysis Complete - Ready for Implementation

---

## Executive Summary

This document outlines all discovered discrepancies, missing functionality, and provides a comprehensive plan for fixing issues and migrating from MongoDB to PostgreSQL.

---

## Part 1: Critical Code Discrepancies

### 1.1 Quiz System Mismatches

**File:** `src/cogs/quiz.py` vs `src/services/quiz_service.py`

#### Missing Methods in `quiz_service.py`

The quiz cog calls these methods that don't exist:

| Cog Call | Service Method | Status |
|----------|---------------|---------|
| `check_daily_taken(user_id)` | ❌ Missing | Needs implementation |
| `get_time_until_next_daily()` | ❌ Missing | Needs implementation |
| `get_daily_quiz()` | `get_daily_challenge()` | ❌ Wrong name/return format |
| `record_quiz_attempt()` | `record_attempt()` | ❌ Wrong name |

#### Return Format Mismatch in `get_user_stats()`

**Cog expects:**
```python
{
    'total_quizzes': int,
    'correct_answers': int,
    'accuracy': float,
    'points': int,
    'categories': dict,
    'recent_quizzes': list
}
```

**Service returns:**
```python
{
    'total_attempts': int,
    'correct_attempts': int,
    'accuracy': float,
    'average_time': float,
    'total_points': int,
    'quiz_score': int
}
```

**Impact:** Quiz stats command will fail or show wrong data.

### 1.2 Networking Module Bug

**File:** `src/cogs/networking.py:162`

**Issue:** Uses `self.db.connection_requests` but variable is named `self.connection_requests` (line 14)

**Fix:**
```python
# Change line 162 from:
await self.db.connection_requests.insert_one(connection_data)
# To:
await self.connection_requests.insert_one(connection_data)
```

### 1.3 Missing Networking Commands

**File:** `src/cogs/networking.py`

Commands referenced in help messages but not implemented:

- `!accept @user` - Accept connection request
- `!decline @user` - Decline connection request  
- `!connections` - List your connections

**Current state:** Users can send connection requests but cannot respond to them.

### 1.4 Missing Quiz Management

**File:** `src/cogs/quiz.py`

No way to add quizzes to the database. Need admin commands:
- `!quiz add` - Interactive quiz creation
- `!quiz edit <id>` - Edit existing quiz
- `!quiz delete <id>` - Delete quiz

### 1.5 Workshop Data Persistence Issue

**File:** `src/cogs/workshops/workshop_manager.py`

**Issue:** Workshops stored only in memory (`self.active_workshops = {}`)

**Impact:** All workshop data lost on bot restart

**Solution:** Persist to MongoDB collection (pre-migration) or PostgreSQL table (post-migration)

### 1.6 Gamification Points Conflict

**File:** `src/cogs/gamification/gamification_manager.py` vs `src/config/config.py`

**Issue:** Point values defined in both places with different values:

| Action | Config.py | Gamification Manager |
|--------|-----------|---------------------|
| Quiz correct | 10 | 10 ✓ |
| Workshop host | N/A | 50 |
| Workshop attendance | N/A | 20 |
| Mentorship complete | 30 | 100 |
| Daily activity | 20 | 5 |

**Impact:** Inconsistent point awards depending on which system records the action.

### 1.7 Missing Test Framework

**Status:** No tests configured

**Missing:**
- `tests/` directory
- pytest configuration
- Test coverage for any functionality

---

## Part 2: MongoDB to PostgreSQL Migration Plan

### 2.1 Migration Strategy

**Approach:** Parallel implementation with data migration

1. Fix MongoDB discrepancies first
2. Design PostgreSQL schema
3. Create database abstraction layer
4. Migrate services one by one
5. Run parallel systems during transition
6. Switch over once verified

### 2.2 Proposed PostgreSQL Schema

#### Core Tables

```sql
-- Users (central identity table)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    discord_id VARCHAR(20) UNIQUE NOT NULL,
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

-- Profiles (networking feature)
CREATE TABLE profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    skills TEXT,
    experience TEXT,
    looking_for TEXT,
    last_updated TIMESTAMP DEFAULT NOW()
);

-- Quizzes
CREATE TABLE quizzes (
    id SERIAL PRIMARY KEY,
    category VARCHAR(100) NOT NULL,
    difficulty VARCHAR(20) NOT NULL,
    question TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    wrong_answers TEXT[], -- PostgreSQL array
    explanation TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Quiz Attempts
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

-- Workshop Participants (junction table)
CREATE TABLE workshop_participants (
    workshop_id VARCHAR(50) REFERENCES workshops(id),
    user_id INTEGER REFERENCES users(id),
    registered_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (workshop_id, user_id)
);

-- Connections
CREATE TABLE connections (
    id SERIAL PRIMARY KEY,
    requester_id INTEGER REFERENCES users(id),
    recipient_id INTEGER REFERENCES users(id),
    message TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- RSS Cache
CREATE TABLE rss_cache (
    id SERIAL PRIMARY KEY,
    url VARCHAR(500) UNIQUE NOT NULL,
    title VARCHAR(255),
    content JSONB,
    cached_at TIMESTAMP DEFAULT NOW()
);
```

#### Indexes

```sql
-- Performance indexes
CREATE INDEX idx_users_discord_id ON users(discord_id);
CREATE INDEX idx_quiz_attempts_user_id ON quiz_attempts(user_id);
CREATE INDEX idx_quiz_attempts_quiz_id ON quiz_attempts(quiz_id);
CREATE INDEX idx_quizzes_category ON quizzes(category);
CREATE INDEX idx_quizzes_difficulty ON quizzes(difficulty);
CREATE INDEX idx_mentorships_mentor ON mentorships(mentor_id);
CREATE INDEX idx_mentorships_mentee ON mentorships(mentee_id);
CREATE INDEX idx_mentorships_status ON mentorships(status);
CREATE INDEX idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX idx_connections_requester ON connections(requester_id);
CREATE INDEX idx_connections_recipient ON connections(recipient_id);
```

### 2.3 Technology Stack Changes

#### Current Stack
- `motor` - Async MongoDB driver
- Raw queries (no ORM)

#### New Stack Options

**Option A: asyncpg + SQL (Recommended)**
- `asyncpg` - High-performance async PostgreSQL driver
- Raw SQL with parameter binding
- Pros: Fastest, most control, easy to migrate from MongoDB style
- Cons: More code, manual query writing

**Option B: databases + SQLAlchemy Core**
- `databases` - Simple async SQL layer
- SQLAlchemy Core for query building
- Pros: Clean API, connection pooling, query builder
- Cons: Additional dependency

**Option C: SQLAlchemy ORM (Not Recommended)**
- Full ORM with models
- Pros: Most abstracted, automatic migrations
- Cons: Steepest learning curve, async support still maturing

**Recommendation:** Option A (asyncpg) for simplicity and performance.

### 2.4 File Changes Required

#### Files to Modify

1. **Database Layer**
   - `src/database/mongodb.py` → `src/database/database.py`
   - New: `src/database/models.py` - Type definitions

2. **Services**
   - `src/services/quiz_service.py`
   - `src/services/mentorship_service.py`
   - `src/services/rss_service.py`

3. **Cogs**
   - `src/cogs/quiz.py`
   - `src/cogs/networking.py`
   - `src/cogs/mentorship.py`
   - `src/cogs/gamification/gamification_manager.py`
   - `src/cogs/portfolio/portfolio_manager.py`
   - `src/cogs/workshops/workshop_manager.py`
   - `src/cogs/feeds.py`

4. **Configuration**
   - `src/config/config.py` - Add PostgreSQL config
   - `main.py` - Update DB initialization
   - `requirements.txt` - Replace motor with asyncpg

5. **Infrastructure**
   - `docker-compose.yml` - Add PostgreSQL service
   - `.env.example` - Update environment variables

#### New Files to Create

```
migrations/
├── 001_initial_schema.sql
├── 002_create_indexes.sql
└── 003_seed_data.sql

scripts/
└── migrate_mongo_to_postgres.py

tests/
├── conftest.py
├── test_quiz.py
├── test_networking.py
└── test_database.py
```

### 2.5 Migration Script Structure

```python
# scripts/migrate_mongo_to_postgres.py
"""
Data migration script from MongoDB to PostgreSQL
"""

import asyncio
import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient

async def migrate_users(mongo_db, pg_pool):
    """Migrate users collection"""
    users = mongo_db.users.find()
    async for user in users:
        await pg_pool.execute("""
            INSERT INTO users (discord_id, points, experience, level, quiz_score, 
                             challenge_score, daily_streak, last_daily, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (discord_id) DO NOTHING
        """, user['discord_id'], user.get('points', 0), user.get('experience', 0),
             user.get('level', 1), user.get('quiz_score', 0), user.get('challenge_score', 0),
             user.get('daily_streak', 0), user.get('last_daily'), user.get('created_at'))

async def main():
    # Connect to both databases
    mongo_client = AsyncIOMotorClient("mongodb://...")
    mongo_db = mongo_client.veka_bot
    
    pg_pool = await asyncpg.create_pool("postgresql://...")
    
    # Run migrations
    await migrate_users(mongo_db, pg_pool)
    await migrate_quizzes(mongo_db, pg_pool)
    await migrate_quiz_attempts(mongo_db, pg_pool)
    await migrate_mentorships(mongo_db, pg_pool)
    await migrate_portfolios(mongo_db, pg_pool)
    
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(main())
```

### 2.6 Query Translation Examples

#### MongoDB → PostgreSQL

**Find One:**
```python
# MongoDB
user = await users.find_one({"discord_id": discord_id})

# PostgreSQL
user = await conn.fetchrow(
    "SELECT * FROM users WHERE discord_id = $1", 
    discord_id
)
```

**Insert:**
```python
# MongoDB
result = await quizzes.insert_one(quiz_data)
quiz_id = result.inserted_id

# PostgreSQL
quiz_id = await conn.fetchval(
    """INSERT INTO quizzes (category, difficulty, question, correct_answer, 
                          wrong_answers, explanation) 
       VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
    category, difficulty, question, correct_answer, wrong_answers, explanation
)
```

**Update:**
```python
# MongoDB
await users.update_one(
    {"discord_id": user_id},
    {"$inc": {"points": points}}
)

# PostgreSQL
await conn.execute(
    "UPDATE users SET points = points + $1 WHERE discord_id = $2",
    points, user_id
)
```

**Aggregate:**
```python
# MongoDB
pipeline = [
    {"$match": {"user_id": user_id}},
    {"$group": {"_id": None, "avg_time": {"$avg": "$time_taken"}}}
]
result = await quiz_attempts.aggregate(pipeline).to_list(length=1)

# PostgreSQL
result = await conn.fetchrow(
    "SELECT AVG(time_taken) as avg_time FROM quiz_attempts WHERE user_id = $1",
    user_id
)
```

---

## Part 3: Implementation Roadmap

### Phase 1: Fix Critical Issues (Week 1)

**Priority: HIGH**

- [ ] Fix quiz service/cog method name mismatches
- [ ] Fix `get_user_stats()` return format
- [ ] Fix networking.py `self.db` → `self.connection_requests` bug
- [ ] Add missing `!accept` and `!decline` commands to networking
- [ ] Unify point values across gamification and config

### Phase 2: Add Missing Features (Week 2)

**Priority: MEDIUM**

- [ ] Add `!quiz add/edit/delete` admin commands
- [ ] Persist workshops to database (not memory)
- [ ] Add `!connections` list command
- [ ] Implement daily quiz tracking methods
- [ ] Add test framework (pytest)
- [ ] Write basic tests for critical paths

### Phase 3: PostgreSQL Setup (Week 3)

**Priority: HIGH**

- [ ] Create PostgreSQL schema migration files
- [ ] Add PostgreSQL to docker-compose.yml
- [ ] Create database connection module with asyncpg
- [ ] Update requirements.txt with new dependencies
- [ ] Create database abstraction layer

### Phase 4: Service Migration (Week 4-5)

**Priority: HIGH**

Migrate services one by one:

- [ ] User service (get_or_create_user, etc.)
- [ ] Quiz service
- [ ] Mentorship service
- [ ] RSS service (if caching needed)
- [ ] Portfolio cog database calls
- [ ] Workshop cog database calls
- [ ] Gamification cog database calls

### Phase 5: Data Migration (Week 6)

**Priority: HIGH**

- [ ] Create data migration script
- [ ] Test migration in staging environment
- [ ] Run migration in production
- [ ] Verify data integrity

### Phase 6: Switch Over (Week 7)

**Priority: CRITICAL**

- [ ] Update main.py to use PostgreSQL
- [ ] Remove MongoDB dependencies
- [ ] Run full test suite
- [ ] Deploy to production
- [ ] Monitor for issues

### Phase 7: Cleanup (Week 8)

**Priority: LOW**

- [ ] Remove MongoDB code
- [ ] Update documentation
- [ ] Archive MongoDB data
- [ ] Optimize PostgreSQL queries

---

## Part 4: Environment Configuration

### Updated .env File

```env
# Discord
DISCORD_TOKEN=your_discord_bot_token

# MongoDB (Remove after migration)
# MONGODB_URI=mongodb+srv://...

# PostgreSQL (Add for migration)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=veka_bot
POSTGRES_USER=veka_user
POSTGRES_PASSWORD=secure_password
DATABASE_URL=postgresql://veka_user:secure_password@localhost:5432/veka_bot

# Redis (Keep for caching)
REDIS_URL=redis://localhost:6379
```

### Updated docker-compose.yml

```yaml
version: '3.8'

services:
  discord-bot:
    build: .
    image: veka-discord-bot:latest
    container_name: veka-discord-bot
    restart: unless-stopped
    volumes:
      - ./logs:/app/logs
      - ./.env:/app/.env:ro
    environment:
      - PYTHONUNBUFFERED=1
    networks:
      - veka-network
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:15-alpine
    container_name: veka-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: veka_bot
      POSTGRES_USER: veka_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - veka-network
    ports:
      - "5432:5432"

  redis:
    image: redis:alpine
    container_name: veka-redis
    restart: unless-stopped
    volumes:
      - redis-data:/data
    networks:
      - veka-network
    ports:
      - "6379:6379"

networks:
  veka-network:
    driver: bridge

volumes:
  postgres-data:
  redis-data:
```

---

## Part 5: Quick Reference

### MongoDB to PostgreSQL Type Mapping

| MongoDB | PostgreSQL | Notes |
|---------|-----------|-------|
| ObjectId | SERIAL | Auto-incrementing integer |
| String | VARCHAR/TEXT | Use VARCHAR with length limits |
| Integer | INTEGER | Same |
| Float | FLOAT/REAL | Same |
| Boolean | BOOLEAN | Same |
| Date | TIMESTAMP | Use TIMESTAMP WITH TIME ZONE |
| Array | ARRAY | PostgreSQL native arrays |
| Object | JSONB | For flexible schemas |
| Embedded Doc | Separate Table | Normalize data |
| Reference | FOREIGN KEY | Use proper constraints |

### Critical Files Checklist

**Must Fix:**
- [ ] `src/services/quiz_service.py` - Method names and return formats
- [ ] `src/cogs/networking.py:162` - Database variable reference
- [ ] `src/cogs/networking.py` - Add accept/decline commands
- [ ] `src/cogs/gamification/gamification_manager.py` - Point value consistency

**Should Fix:**
- [ ] `src/cogs/quiz.py` - Add quiz management commands
- [ ] `src/cogs/workshops/workshop_manager.py` - Persist to database
- [ ] `src/services/quiz_service.py` - Daily quiz methods

**Nice to Have:**
- [ ] Add comprehensive test suite
- [ ] Add logging to all error paths
- [ ] Add input validation

---

## Appendix A: Query Performance Notes

### MongoDB Queries to Optimize for PostgreSQL

1. **Quiz random selection** - Currently uses `$sample`, use `ORDER BY RANDOM()` in PostgreSQL
2. **Leaderboard queries** - Add composite indexes on (points DESC, discord_id)
3. **Mentorship lookups** - Index on (mentor_id, mentee_id, status)
4. **Quiz attempts aggregation** - Use materialized view for leaderboard if slow

### PostgreSQL Specific Optimizations

```sql
-- Use partial indexes for common queries
CREATE INDEX idx_active_mentorships ON mentorships(mentor_id, mentee_id) 
WHERE status = 'active';

-- Use GIN index for array searches
CREATE INDEX idx_quiz_tags ON quizzes USING GIN(tags);

-- Partition quiz_attempts by date if high volume
CREATE TABLE quiz_attempts_2024 PARTITION OF quiz_attempts 
FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
```

---

## Conclusion

This codebase has solid architecture but suffers from:
1. Method signature mismatches between cogs and services
2. Incomplete networking features
3. Memory-only storage for workshops
4. No test coverage

The migration to PostgreSQL is straightforward and will provide:
- Better data consistency (foreign keys, constraints)
- Easier backups and replication
- Better query performance for complex aggregations
- ACID compliance

**Estimated Timeline:** 8 weeks  
**Risk Level:** Medium (data migration complexity)  
**Recommendation:** Proceed with Phase 1 fixes immediately, then migrate.

---

**Document generated by:** Code Analysis Agent  
**Last updated:** 2026-02-12
