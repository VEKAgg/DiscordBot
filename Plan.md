# VEKA Discord Bot - Complete Development Plan

**Version:** 2.0  
**Status:** PostgreSQL Migration Phase  
**Priority:** IMMEDIATE  
**Last Updated:** 2026-02-12

---

## Phase 1: PostgreSQL Migration (IMMEDIATE - This Week)

### 1.1 Why PostgreSQL?

- **Better for relationships:** Users → Items → Transactions
- **ACID compliance:** Critical for ecommerce payments
- **Complex queries:** Search by price, category, seller
- **Data integrity:** Foreign keys prevent orphaned records

### 1.2 Database Schema

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

### 1.3 Migration Tasks

#### Day 1: Database Setup
- [ ] Create `migrations/001_initial_schema.sql`
- [ ] Create `src/database/database.py` with asyncpg
- [ ] Update `requirements.txt` (remove motor, add asyncpg)
- [ ] Update `docker-compose.yml` with PostgreSQL service
- [ ] Test database connection

#### Day 2-3: Service Migration
- [ ] Migrate `src/services/quiz_service.py`
- [ ] Migrate `src/services/mentorship_service.py`
- [ ] Update `src/cogs/quiz.py`
- [ ] Update `src/cogs/mentorship.py`

#### Day 4: Cog Migration
- [ ] Update `src/cogs/networking.py`
- [ ] Update `src/cogs/gamification/gamification_manager.py`
- [ ] Update `src/cogs/workshops/workshop_manager.py`
- [ ] Update `src/cogs/portfolio/portfolio_manager.py`

#### Day 5: Finalization
- [ ] Update `main.py` to use new database
- [ ] Test all commands
- [ ] Remove MongoDB dependencies
- [ ] Update documentation

### 1.4 Technology Changes

**Remove from `requirements.txt`:**
```txt
motor
pymongo
```

**Add to `requirements.txt`:**
```txt
# Database
asyncpg>=0.29.0

# (Keep existing)
nextcord
python-dotenv
feedparser
beautifulsoup4
aiohttp
python-dateutil
apscheduler
validators
```

### 1.5 Database Module Code

**File:** `src/database/database.py`

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

### 1.6 Query Translation Examples

**Before (MongoDB):**
```python
user = await users.find_one({"discord_id": discord_id})
await users.update_one(
    {"discord_id": user_id},
    {"$inc": {"points": 10}}
)
```

**After (PostgreSQL):**
```python
user = await db.fetch_one(
    "SELECT * FROM users WHERE discord_id = $1", 
    discord_id
)
await db.execute(
    "UPDATE users SET points = points + $1 WHERE discord_id = $2",
    10, user_id
)
```

---

## Phase 2: Security Implementation (Week 2)

### 2.1 Input Validation & Sanitization

- [ ] Add input length limits
- [ ] Sanitize Discord markdown
- [ ] Validate email/URL formats
- [ ] Check for profanity

### 2.2 Rate Limiting

```python
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self):
        self.cooldowns = {}
    
    def check_rate_limit(self, user_id: str, command: str, cooldown_seconds: int):
        key = f"{user_id}:{command}"
        now = datetime.utcnow()
        
        if key in self.cooldowns:
            last_used = self.cooldowns[key]
            if now - last_used < timedelta(seconds=cooldown_seconds):
                return False
        
        self.cooldowns[key] = now
        return True
```

### 2.3 Audit Logging

```sql
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(20),
    action VARCHAR(100),
    details TEXT,
    ip_address INET,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 2.4 Role-Based Access

- Admin: Full access
- Moderator: Ban/kick, manage messages
- Verified Seller: Can post marketplace items
- User: Basic commands

---

## Phase 3: Marketplace/Ecommerce (Week 3-4)

### 3.1 Database Schema

**File:** `migrations/002_marketplace_schema.sql`

```sql
-- Marketplace Categories
CREATE TABLE marketplace_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    parent_id INTEGER REFERENCES marketplace_categories(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Marketplace Listings
CREATE TABLE marketplace_listings (
    id SERIAL PRIMARY KEY,
    seller_id INTEGER REFERENCES users(id),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
    category_id INTEGER REFERENCES marketplace_categories(id),
    condition VARCHAR(50), -- new, used, refurbished
    images TEXT[], -- array of image URLs
    status VARCHAR(20) DEFAULT 'active', -- active, sold, withdrawn
    views INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Marketplace Transactions
CREATE TABLE marketplace_transactions (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER REFERENCES marketplace_listings(id),
    buyer_id INTEGER REFERENCES users(id),
    seller_id INTEGER REFERENCES users(id),
    price DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending', -- pending, completed, cancelled, disputed
    payment_method VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Reviews & Ratings
CREATE TABLE marketplace_reviews (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER REFERENCES marketplace_transactions(id),
    reviewer_id INTEGER REFERENCES users(id),
    reviewee_id INTEGER REFERENCES users(id),
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Watchlist (Users watching items)
CREATE TABLE marketplace_watchlist (
    user_id INTEGER REFERENCES users(id),
    listing_id INTEGER REFERENCES marketplace_listings(id),
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, listing_id)
);

-- Indexes
CREATE INDEX idx_listings_seller ON marketplace_listings(seller_id);
CREATE INDEX idx_listings_category ON marketplace_listings(category_id);
CREATE INDEX idx_listings_status ON marketplace_listings(status);
CREATE INDEX idx_listings_price ON marketplace_listings(price);
CREATE INDEX idx_transactions_buyer ON marketplace_transactions(buyer_id);
CREATE INDEX idx_transactions_seller ON marketplace_transactions(seller_id);
```

### 3.2 Commands

**Marketplace Commands:**
- `!marketplace post` - Create listing (interactive)
- `!marketplace browse [category]` - Browse items
- `!marketplace search <query>` - Search listings
- `!marketplace view <id>` - View item details
- `!marketplace buy <id>` - Purchase item
- `!marketplace mylistings` - Your active listings
- `!marketplace withdraw <id>` - Remove listing
- `!marketplace watch <id>` - Add to watchlist
- `!marketplace rate <user> <1-5> [comment]` - Leave review

### 3.3 Fraud Prevention

- Seller verification required
- Cannot buy your own items
- Transaction limits per day
- Suspicious activity detection
- Price range validation

---

## Phase 4: Core Features (From Original Plan.md)

### 4.1 Welcome System ✅ (Already Done)
- Welcome messages
- Auto-role assignment
- DM with instructions

### 4.2 Activity Tracking

```sql
CREATE TABLE user_activity (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    activity_type VARCHAR(50), -- message, voice, reaction
    channel_id VARCHAR(20),
    duration INTEGER, -- for voice (seconds)
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4.3 Leaderboards

```sql
CREATE VIEW leaderboard_weekly AS
SELECT 
    u.discord_id,
    u.username,
    COUNT(a.id) as activity_count,
    RANK() OVER (ORDER BY COUNT(a.id) DESC) as rank
FROM users u
LEFT JOIN user_activity a ON u.id = a.user_id 
    AND a.created_at > NOW() - INTERVAL '7 days'
GROUP BY u.id
ORDER BY activity_count DESC
LIMIT 10;
```

### 4.4 Auto-Moderation

- Spam detection (5 messages/10 seconds)
- Profanity filter
- Link filtering (except allowed domains)
- Caps lock detection (>70% caps)

---

## Phase 5: Integrations (Week 5-6)

### 5.1 GitHub Integration
- `!github user <username>` - User stats
- `!github repo <owner>/<repo>` - Repository info

### 5.2 News & RSS ✅ (Already Done)
- Enhanced with custom channels per category

### 5.3 Reminders
- `!remindme <time> <message>`
- Persist in database

### 5.4 Price Tracking (Future)
- Crypto via CoinGecko
- Product price alerts

### 5.5 Game Integrations (Future)
- Genshin Impact
- Valorant
- Steam deals

---

## Phase 6: Dashboard & Web (Week 7+)

### 6.1 FastAPI Dashboard
- Server statistics
- User management
- Configuration interface
- Real-time updates (WebSocket)

### 6.2 Features
- JWT authentication
- Role management
- Audit logs viewer
- Analytics charts

---

## Implementation Priority

### Immediate (This Week)
1. ✅ PostgreSQL migration
2. ✅ Fix all database queries
3. ✅ Test all existing commands

### Week 2
1. Security layer (rate limiting, validation)
2. Audit logging
3. Role-based access

### Week 3-4
1. Marketplace schema
2. Marketplace commands
3. Seller verification
4. Transaction system

### Week 5+
1. GitHub integration
2. Enhanced leaderboards
3. Auto-moderation
4. Dashboard (optional)

---

## Security Checklist

- [ ] SQL Injection protection (parameterized queries) ✅
- [ ] Input validation (length, format, content)
- [ ] Rate limiting (commands per user)
- [ ] Audit logging (who did what when)
- [ ] Role-based access control
- [ ] Data encryption at rest (database)
- [ ] Secure environment variables ✅
- [ ] Error handling (don't expose internals)
- [ ] Marketplace fraud detection
- [ ] Transaction validation

---

## Database Connection Security

### Environment Variables (`.env`)
```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=veka_bot
POSTGRES_USER=veka_bot_user
POSTGRES_PASSWORD=your_secure_random_password_here
DATABASE_URL=postgresql://veka_bot_user:password@localhost:5432/veka_bot
```

### Connection Security
- Use SSL in production
- Connection pooling (asyncpg handles this)
- Database user with minimal permissions
- Separate read-only user for analytics

---

## Success Criteria

### Phase 1 (PostgreSQL Migration)
- [ ] All commands work with PostgreSQL
- [ ] No MongoDB code remaining
- [ ] Bot starts without errors
- [ ] Data persists across restarts
- [ ] Performance equal or better

### Phase 2 (Security)
- [ ] Rate limiting active
- [ ] Input validation working
- [ ] Audit logs recording
- [ ] Role-based access implemented

### Phase 3 (Marketplace)
- [ ] Users can post items
- [ ] Browse and search working
- [ ] Purchase flow complete
- [ ] Reviews system working
- [ ] Fraud detection active

---

## Quick Commands

```bash
# Start PostgreSQL and Redis
docker-compose up -d postgres redis

# Run migrations
psql -h localhost -U veka_user -d veka_bot -f migrations/001_initial_schema.sql

# Install dependencies
pip install -r requirements.txt

# Run bot
python main.py

# View logs
docker-compose logs -f discord-bot
```

---

**Ready to begin Phase 1?** Start with creating the migration file and database module.
