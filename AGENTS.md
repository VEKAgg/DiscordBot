# AGENTS.md — VEKA Discord Bot

A nextcord-based professional networking Discord bot. Work-in-progress — several modules referenced in imports do not exist yet (`src.core.app`, `src.core.runtime_state`, `src.database.migrations`, `src.utils.embeds`, `src.utils.safety`).

## Python & Dependencies

- **Python**: `>=3.10` (Dockerfile uses `3.10-slim`; `pyproject.toml` says `>=3.13` — install via `requirements.txt`, not `pyproject.toml` which lists no deps)
- **Install**: `pip install -r requirements.txt`
- **Key pinned deps**: nextcord 2.6.0, asyncpg 0.29.2, aiohttp 3.12.11, feedparser 6.0.12, python-dotenv 1.2.2

## Run

```bash
python main.py                        # local (needs postgres + redis)
docker-compose up -d --build          # full stack
```

Requires PostgreSQL + Redis. Docker Compose provides both.

## Project Structure

```
main.py                     → entrypoint (delegates to src.core.app — not yet created)
src/
├── core/                   → app bootstrap, runtime state (WIP — mostly missing)
├── config/config.py        → all env vars, constants, feature flags, cooldowns
├── database/
│   ├── database.py         → asyncpg pool manager, global `db` singleton, migrations runner
│   └── migrations.py       → referenced but does not exist yet
├── cogs/
│   ├── admin/              → basic.py, help.py, health.py (all use missing utils modules)
│   ├── networking/         → networking.py (profiles, connections — slash + prefix fallbacks)
│   ├── marketplace/        → marketplace.py, reviews.py
│   ├── marketplace_enhanced.py (background tasks for price drops, expiring listings)
│   ├── resources/feeds.py  → RSS, uses @tasks.loop(minutes=15), safe_background_task
│   ├── fun.py, quiz.py, mentorship.py (flat files)
│   ├── gamification/       → stub (disabled)
│   ├── portfolio/          → portfolio_manager.py
│   └── workshops/          → workshop_manager.py
├── services/               → mentorship_service.py, networking_service.py, quiz_service.py, rss_service.py
├── utils/
│   ├── security/           → rbac.py, rate_limiter.py, audit.py, validation.py
│   └── marketplace/        → fraud_detection.py
migrations/                 → 6 SQL files (001–007), auto-applied on startup by database.py
```

## Commands

Prefix: `!` (hardcoded in `config.py`). Both prefix commands and slash commands are defined — often in parallel for the same feature.

## Cogs — Conventions

Require a `setup(bot)` function at module level. Some cogs guard with `if bot is not None:`, others don't. All use `logging.getLogger('VEKA.xxx')`.

Cog class name auto-mapping:
- `fun.py` → `Fun`
- `networking/networking.py` → `Networking`
- `admin/basic.py` → `Basic`
- `admin/health.py` → `Health`

## Database

- PostgreSQL via asyncpg. **Parameter style**: `$1`, `$2` (asyncpg native).
- Global singleton: `from src.database.database import db`
- Migration files live in `migrations/` directory. Applied automatically by `db.run_migrations()` on connect. The migration runner module itself (`database/migrations.py`) does not exist yet.
- Tables: `users`, `profiles`, `connections`, `connection_requests`, `mentorships`, `quizzes`, `quiz_attempts`, `listings`, `reviews`, `transactions`, `rss_cache`, `guild_settings`, `audit_log`, `audit_trail`, `rate_limits`, `security_events`, `watchlist`

## Testing / Linting

**None configured.** No test files, no config files for pytest/black/flake8. `pyproject.toml` is a stub.

## CI/CD

- GitHub Actions at `.github/workflows/deploy-discord-bot.yml`
- Triggers on push to `main` or `production`, but only runs if commit message starts with `Merge pull request`
- Self-hosted runner (label: `self-hosted, X64, Linux, Veka`)
- Supports both Docker and Podman (controlled by `CONTAINER_ENGINE` secret, defaults to `docker`)
- Health check waits for log line `"has connected to Discord"` (up to 60s)

## Security Utilities

Package at `src.utils.security` exports: `rate_limiter`, `rate_limit`, `InputValidator`, `sanitize`, `validate_id`, `is_safe`, `audit_log`, `audit_action`, `rbac`, `Role`, `require_mod`, `require_admin`, `require_verified`.

RBAC hierarchy: USER < VERIFIED < MODERATOR < ADMIN < OWNER. Mapped from Discord role names (`everyone`, `verified`, `mod`/`moderator`, `admin`/`administrator`, guild owner).

## Key WIP Facts

- `src.core.app`, `src.core.runtime_state`, `src.database.migrations`, `src.utils.embeds`, `src.utils.safety` are **imported but do not exist**. The bot cannot run as-is.
- Several cogs (`admin/basic.py`, `admin/health.py`, `resources/feeds.py`) depend on these missing modules.
- `pyproject.toml` has no dependencies (all deps in `requirements.txt`).
- Gamification cog is a stub (`gamification_manager.py` responds "disabled").
