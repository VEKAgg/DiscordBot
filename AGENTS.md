# AGENTS.md — VEKA Discord Bot

Python `>=3.13`. No test framework configured.

## Setup

```bash
git clone <repo> && cd discord-bot
cp .env.example .env              # then fill in DISCORD_TOKEN and DATABASE_URL

# Install all deps (runtime + dev) via uv
uv sync --extra dev

# Activate pre-commit hooks (do this once after clone)
pre-commit install
```

## Commands

| Action | Command |
|---|---|
| Run locally | `python main.py` |
| Local stack (bot + postgres) | `docker compose -f docker-compose.dev.yml up -d --build` |
| Production (bot only) | `docker compose up -d` |
| View logs | `docker logs veka-discord-bot` |
| PM2 start (self-hosted) | `pm2 start discord-bot.json` |

## Lint / Format / Typecheck

Run these before every push:

```bash
# Lint check (no auto-fixes)
ruff check .

# Auto-fix lint issues then format
ruff check --fix . && ruff format .

# Type check
mypy src/ main.py

# All pre-commit hooks (runs ruff + mypy + misc checks)
pre-commit run --all-files
```

All config lives in `pyproject.toml` under `[tool.ruff]` and `[tool.mypy]`. Pre-commit config is `.pre-commit-config.yaml`.

## Architecture

- **Entrypoint:** `main.py` → `src/core/app.py:run_bot()` → loads `.env`, builds bot, loads extensions, `bot.run()`
- **Extensions loaded from explicit allowlist** (`EXTENSIONS` in `src/core/app.py:27`). Only these: `src.cogs.admin.basic`, `src.cogs.admin.help`, `src.cogs.admin.health`, `src.cogs.networking.networking`, `src.cogs.marketplace.marketplace`, `src.cogs.resources.feeds`. Many stubs under `src/cogs/` are NOT loaded (fun, quiz, mentorship, gamification, portfolio, workshops). Add a cog's module path (full dotted path, e.g. `src.cogs.xxx`) to `EXTENSIONS` to enable it.
- **Degraded-mode:** DB/cog failures don't crash the bot. `bot.runtime_state` (`src/core/runtime_state.py`) tracks `db_available`, `loaded_cogs`, `failed_cogs`, `degraded_features`.
- **Layering:** `src/cogs/` (thin command handlers) → `src/services/` (business logic) → `src/database/` (data access).
- **Each cog** needs a module-level `setup(bot)` function.

## Database

- PostgreSQL via **asyncpg** (the only datastore — no Redis, no MongoDB).
- Global singleton: `from src.database.database import db`.
- **`$1`/`$2` parameter style** (asyncpg native).
- All methods raise `DatabaseUnavailableError` on failure and flip `runtime_state.db_available`.
- Migrations: `.sql` files in `migrations/`, auto-applied on connect by `db.run_migrations()`, tracked in `schema_migrations` table. Add as `migrations/00N_name.sql`.

## Conventions

- **Dual command surface:** prefix (`!`) and slash commands side by side in the same cog. Keep both in sync.
- Use safety wrappers from `src/utils/safety.py`: `@safe_command(requires_db=True)`, `@safe_slash_command(requires_db=True)`, `safe_send()`, `@safe_background_task(name=...)`.
- All user-facing output uses embed helpers from `src/utils/embeds.py`: `veka_embed`, `success_embed`, `error_embed`, `info_embed`, `alert_embed`. Pass `contributor_source=__name__`.
- Logging: `logging.getLogger('VEKA.<area>')`.
- Rate limiting: `@rate_limit('bucket_name')` from `src.utils.security`.
- RBAC from `src.utils.security`: `@require_mod()`, `@require_admin()`, `@require_verified()`. Also `admin_only()` in `safety.py` (parallel auth via `ADMIN_IDS`/`OWNER_IDS`).
- Single `.env` file for config. Command prefix is hardcoded `!` in `src/config/config.py`.

## CI/CD

`.github/workflows/deploy-discord-bot.yml` — deploys on push to `main`/`production` **only when commit message starts with `Merge pull request`**. Self-hosted runner. Gates on log line `"is ready. DB available"` appearing within 60s.
