# AGENTS.md — VEKA Discord Bot

## Commands

```bash
pip install -r requirements.txt    # or: uv sync
python main.py                     # needs .env + reachable PostgreSQL
docker compose -f docker-compose.dev.yml up -d --build  # local stack w/ bundled postgres
docker compose up -d               # production (external DB via DATABASE_URL)
docker logs veka-discord-bot       # view logs
```

Python `>=3.13`. No tests, linters, or formatters configured.

## Architecture

- **Entrypoint:** `main.py` → `src/core/app.py:run_bot()` → loads `.env`, builds bot, loads extensions, `bot.run()`
- **Extensions loaded from explicit allowlist** (`EXTENSIONS` in `src/core/app.py:27`). Only these: `admin.basic`, `admin.help`, `admin.health`, `networking.networking`, `marketplace.marketplace`, `resources.feeds`. Many stubs under `src/cogs/` are NOT loaded (fun, quiz, mentorship, gamification, portfolio, workshops). Add a cog's module path to `EXTENSIONS` to enable it.
- **Degraded-mode:** DB/cog failures don't crash the bot. `bot.runtime_state` (`src/core/runtime_state.py`) tracks `db_available`, `loaded_cogs`, `failed_cogs`, `degraded_features`.
- **Layering:** `cogs/` (thin command handlers) → `services/` (business logic) → `database/` (data access).
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
