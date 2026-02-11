# AGENTS.md - VEKA Discord Bot

Guidelines for AI coding agents working on this Python Discord bot.

## Project Overview

A professional networking Discord bot built with Python 3.10+, using:
- **nextcord** - Discord API wrapper
- **motor** - Async MongoDB driver
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
pytest tests/test_cog.py::test_function -v  # Run single test
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

import nextcord
from nextcord.ext import commands

from src.config.config import BOT_PREFIX
from src.database.mongodb import users
```

### Naming Conventions
- **Classes**: PascalCase (`QuizService`, `Basic`)
- **Functions/Variables**: snake_case (`get_user`, `active_quizzes`)
- **Constants**: UPPER_SNAKE_CASE (`BOT_PREFIX`, `RSS_FEEDS`)
- **Private**: _leading_underscore (`_internal_method`)

### Type Hints
```python
from typing import Optional, List, Dict, Tuple

async def get_user(discord_id: str) -> Optional[Dict]:
    pass
```

### Cog Structure
```python
import nextcord
from nextcord.ext import commands
import logging

logger = logging.getLogger('VEKA.cogname')

class CogName(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("CogName cog initialized")

    @commands.command(name="command")
    async def command_name(self, ctx):
        """Command description"""
        pass

def setup(bot):
    bot.add_cog(CogName(bot))
    logging.getLogger('VEKA').info("Loaded cog: src.cogs.cogname")
```

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
```

### Database Operations
```python
from src.database.mongodb import db

async def get_user(discord_id: str) -> Optional[Dict]:
    return await db.users.find_one({"discord_id": discord_id})
```

## Project Structure

```
├── main.py                 # Bot entry point
├── src/
│   ├── cogs/              # Discord command modules
│   │   ├── basic.py       # Simple commands
│   │   ├── quiz.py        # Quiz feature
│   │   └── .../
│   ├── services/          # Business logic
│   ├── database/          # Database layer
│   └── config/            # Configuration
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Environment Variables

Required in `.env`:
```
DISCORD_TOKEN=your_token
MONGODB_URI=mongodb+srv://...
REDIS_URL=redis://redis:6379
```

## Git Workflow

- Branch from `main`
- PRs deploy via GitHub Actions (`.github/workflows/deploy-discord-bot.yml`)
- Commits must start with "Merge pull request" to trigger deploy

## Key Conventions

1. **Always use async/await** - Database and Discord operations are async
2. **Cogs auto-load** - Place `.py` files in `src/cogs/` (or subdirs)
3. **Class naming**: File `quiz.py` → class `Quiz`; `quiz_service.py` → class `QuizService`
4. **Bot prefix**: `!` (defined in config)
5. **Database**: MongoDB Atlas with motor async driver
