# AGENTS.md - VEKA Discord Bot

Guidelines for AI coding agents working on this Python Discord bot.

## Project Overview

A professional networking Discord bot built with Python 3.10+, using:
- **nextcord** - Discord API wrapper (modern fork of discord.py)
- **asyncpg** - Async PostgreSQL driver
- **PostgreSQL** - Database (via DATABASE_URL env var)
- **docker/podman** - Containerization

## Build & Run Commands

```bash
# Local development
pip install -r requirements.txt
python main.py

# Docker
docker-compose up -d --build
docker logs veka-discord-bot

# Podman
podman build -t veka-discord-bot:latest .
podman pod create --name veka-bot-pod
podman run -d --pod veka-bot-pod --name veka-redis -v redis-data:/data redis:alpine
podman run -d --pod veka-bot-pod --name veka-discord-bot -v ./logs:/app/logs -v ./.env:/app/.env:ro veka-discord-bot:latest
```

## Testing

**No test framework is currently configured.**

When adding tests, create a `tests/` directory and use pytest:
```bash
pip install pytest pytest-asyncio
pytest                          # Run all tests
pytest tests/ -v                 # Run with verbose output
pytest tests/test_cog.py -v      # Run single test file
pytest tests/test_cog.py::test_function -v  # Run single test function
pytest tests/ -k "test_name" -v  # Run tests matching pattern
```

## Linting & Formatting

**No linting configuration exists yet.**

Recommended setup (create if needed):
```bash
pip install black isort flake8
black src/ main.py && isort src/ main.py  # Format
flake8 src/ main.py                       # Lint
```

## Code Style Guidelines

### Imports
Order: stdlib → third-party → local
```python
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple

import nextcord
from nextcord.ext import commands

from src.config.config import BOT_PREFIX
from src.database.database import db
```

**Note:** Place `import logging` at the top since module-level loggers are defined immediately after.

### Naming Conventions
- **Classes**: PascalCase (`QuizService`, `Basic`, `WorkshopManager`)
- **Functions/Variables**: snake_case (`get_user`, `active_quizzes`)
- **Constants**: UPPER_SNAKE_CASE (`BOT_PREFIX`, `RSS_FEEDS`, `QUIZ_CATEGORIES`)
- **Private**: _leading_underscore (`_internal_method`)
- **Files**: snake_case (`quiz_service.py`, `database.py`)

### Type Hints
Use type hints for function signatures and return types:
```python
from typing import Optional, List, Dict, Tuple

async def get_user(discord_id: str) -> Optional[Dict]:
    pass
```

### Cog Structure
Cogs are auto-loaded from `src/cogs/` (flat files) and subdirectories (`workshops/`, `portfolio/`, `gamification/`).

```python
import logging
from typing import Optional

import nextcord
from nextcord.ext import commands

logger = logging.getLogger('VEKA.cogname')

class CogName(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("CogName cog initialized")

    @commands.command(name="command")
    async def command_name(self, ctx):
        """Command description"""
        pass

    @nextcord.slash_command(name="slashcmd", description="Description")
    async def slash_command(self, interaction: nextcord.Interaction):
        """Slash command handler"""
        pass
```

**Important:** Cogs are loaded dynamically by `main.py` using class name detection:
- File `quiz.py` → class `Quiz`
- File `quiz_service.py` → class `QuizService`  
- File `workshop_manager.py` → class `WorkshopManager`

### Logging & Error Handling
```python
logger = logging.getLogger('VEKA.modulename')
logger.info("Message")
logger.error(f"Error: {str(e)}")

try:
    result = await some_async_operation()
except Exception as e:
    logger.error(f"Operation failed: {str(e)}")
    return None
```

### Discord Embeds
```python
embed = nextcord.Embed(
    title="Title",
    description="Description",
    color=nextcord.Color.orange()  # Primary brand color
)
embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
await ctx.send(embed=embed)
```

### Database Operations
```python
from src.database.database import db

async def get_user(discord_id: str) -> Optional[Dict]:
    return await db.fetch_one("SELECT * FROM users WHERE discord_id = $1", discord_id)
```

## Project Structure

```
├── main.py                 # Bot entry point with cog loader
├── src/
│   ├── cogs/              # Discord command modules
│   │   ├── basic.py       # Simple commands (class: Basic)
│   │   ├── quiz.py        # Quiz feature (class: Quiz)
│   │   ├── feeds.py       # RSS feeds
│   │   ├── fun.py         # Fun commands
│   │   ├── help.py        # Help system
│   │   ├── mentorship.py  # Mentorship system
│   │   ├── networking.py  # Networking features
│   │   ├── gamification/  # Gamification cog
│   │   │   └── gamification_manager.py (class: GamificationManager)
│   │   ├── portfolio/     # Portfolio cog
│   │   │   └── portfolio_manager.py (class: PortfolioManager)
│   │   └── workshops/     # Workshops cog
│   │       └── workshop_manager.py (class: WorkshopManager)
│   ├── services/          # Business logic
│   │   ├── quiz_service.py
│   │   ├── rss_service.py
│   │   └── mentorship_service.py
│   ├── database/          # Database layer
│   │   └── database.py    # PostgreSQL connection and operations
│   └── config/            # Configuration
│       └── config.py      # Constants and env vars
├── requirements.txt       # Python dependencies
├── Dockerfile
└── docker-compose.yml
```

## Environment Variables

Required in `.env`:
```
DISCORD_TOKEN=your_token
DATABASE_URL=postgresql://user:pass@host:5432/dbname
REDIS_URL=redis://redis:6379
```

## Git Workflow

- Branch from `main`
- PRs deploy via GitHub Actions (`.github/workflows/deploy-discord-bot.yml`)
- Commits must start with "Merge pull request" to trigger deploy

## Key Conventions

1. **Always use async/await** - Database and Discord operations are async
2. **Cogs auto-load** - Place `.py` files in `src/cogs/` (or subdirs)
3. **Class naming**: 
   - `quiz.py` → class `Quiz`
   - `quiz_service.py` → class `QuizService`
   - `workshop_manager.py` → class `WorkshopManager`
4. **Bot prefix**: `!` (defined in config)
5. **Database**: PostgreSQL with asyncpg driver
6. **Loggers**: Use `logging.getLogger('VEKA.modulename')` format
