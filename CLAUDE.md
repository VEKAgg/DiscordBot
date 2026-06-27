# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

VEKA is a nextcord-based professional-networking/community Discord bot backed by PostgreSQL.

## Commands

```bash
pip install -r requirements.txt      # canonical install (pyproject.toml mirrors the same pins)
python main.py                       # run locally — needs a reachable PostgreSQL + DISCORD_TOKEN in .env
docker compose -f docker-compose.dev.yml up -d --build    # local stack: bot + bundled postgres
docker compose up -d                 # production: bot only, expects external DB via DATABASE_URL
docker logs veka-discord-bot         # view logs
```

Requires Python `>=3.13` (nextcord 3.x supports 3.12–3.14). No tests, linters, or formatters are configured — there are no pytest/black/flake8 configs. There is **no Redis and no MongoDB** anywhere — PostgreSQL is the only datastore.

## Architecture

Entrypoint chain: `main.py` → `src/core/app.py:run_bot()`. `run_bot()` loads `.env`, sets up logging, builds the bot, registers events, then `bot.run()`.

**Degraded-mode design is the central architectural theme.** The bot is built to keep running when the database (or a cog, or a background task) is down, rather than crashing:

- `src/core/runtime_state.py` — a single global `runtime_state` dataclass instance holding `db_available`, `loaded_cogs`, `failed_cogs`, `degraded_features`, startup-check results, and an `alert_state_cache`. Attached to the bot as `bot.runtime_state`. This is the source of truth for health/observability.
- DB connection failures at startup do **not** abort boot — `initialize_database()` catches the error, sets `runtime_state.db_available = False`, and adds `'database'` to `degraded_features`.
- A `@tasks.loop(minutes=1)` `db_health_check` continuously pings the DB, flips `db_available`, and fires admin alerts on transition (lost/recovered).
- Cog load failures are caught per-extension in `load_extensions()` and recorded in `failed_cogs`; other cogs still load.

**Extensions are loaded from an explicit allowlist** in `src/core/app.py` (`EXTENSIONS`). Only these load:
`admin.basic`, `admin.help`, `admin.health`, `networking.networking`, `marketplace.marketplace`, `resources.feeds`.
Many modules under `src/cogs/` exist but are **NOT loaded** (e.g. `fun.py`, `quiz.py`, `mentorship.py`, `marketplace_enhanced.py`, `marketplace/reviews.py`, `gamification/`, `portfolio/`, `workshops/`). To enable a cog, add it to `EXTENSIONS`. Gamification is an intentional disabled stub.

**Layering:** `cogs/` (Discord command handlers) → `services/` (business logic, e.g. `NetworkingService`) → `database/` (data access). Cogs should be thin; put logic in services.

### Database

- `src/database/database.py` exposes a global singleton `db` (`from src.database.database import db`). asyncpg pool, **`$1`/`$2` parameter style**.
- All `db` methods (`fetch`, `fetch_one`/`fetchrow`, `fetchval`, `execute`, `execute_many`) raise `DatabaseUnavailableError` on failure and flip `runtime_state.db_available = False`. Never assume a query succeeded.
- Migrations: `.sql` files in `migrations/` are applied automatically on connect by `db.run_migrations()`, tracked in the `schema_migrations` table. Add a new migration as `migrations/00N_name.sql` — it runs on next startup. Runner helpers live in `src/database/migrations.py`.

### Safety wrappers (`src/utils/safety.py`)

This module is how the degraded-mode contract reaches command code. Use it:

- `@safe_command(requires_db=True)` / `@safe_slash_command(requires_db=True)` — wrap command callbacks. They short-circuit with `DatabaseUnavailableError` when `requires_db` and the DB is down, catch unexpected exceptions, log with context, and reply with an error embed.
- `safe_send(target, ...)` — unified reply helper that handles both `commands.Context` and `nextcord.Interaction` (and the interaction responded/not-responded distinction). Prefer over raw `ctx.send` / `interaction.response`.
- `@safe_background_task(name=...)` — wrap `@tasks.loop` bodies; tracks consecutive failures in `runtime_state.alert_state_cache` and alerts admins after 3 failures, with recovery notices.
- Domain exceptions `DatabaseUnavailableError`, `ValidationError`, `ExternalRequestError` are mapped to user-facing messages centrally in `app.py`'s `on_command_error` / `on_application_command_error` and in `map_exception_to_message`.

### Embeds (`src/utils/embeds.py`)

All user-facing output uses the VEKA embed helpers: `veka_embed`, `success_embed`, `error_embed`, `info_embed`, `alert_embed`. They auto-attach a "Command made by … contribute: <repo>" footer via a static `contributor_source` → contributor map. Pass `contributor_source=__name__` from a cog so attribution resolves.

### Security utilities (`src/utils/security/`)

Package exports (`from src.utils.security import ...`): `rate_limiter`, `rate_limit`, `InputValidator`, `sanitize`, `validate_id`, `is_safe`, `audit_log`, `audit_action`, `rbac`, `Role`, `require_mod`, `require_admin`, `require_verified`.
RBAC hierarchy: USER < VERIFIED < MODERATOR < ADMIN < OWNER, mapped from Discord role names (and guild owner). Note `safety.py` also has a simpler `admin_only()` check keyed off `ADMIN_IDS`/`OWNER_IDS` from config — two parallel auth mechanisms exist.

### Config (`src/config/config.py`)

All env/constants live here: `BOT_PREFIX = "!"` (hardcoded), `DISCORD_TOKEN`, `DATABASE_URL` (composed from `POSTGRES_*` if not set directly), `ADMIN_IDS`/`OWNER_IDS`/`ADMIN_ALERT_CHANNEL_ID`, `RSS_FEEDS`, `RATE_LIMITS`.

## Conventions

- **Dual command surface:** features typically define both a `!`-prefix command and a slash command, often side by side in the same cog. When adding/changing a feature, keep both in sync.
- Every cog module needs a module-level `setup(bot)`. Cog classes are standard `commands.Cog` subclasses; slash groups use `nextcord.SlashCommandGroup`.
- Logging: every module uses `logging.getLogger('VEKA.<area>')`; configured by `setup_logging()` in `src/utils/logger.py`.
- Startup health checks live in `src/core/checks.py` (`StartupChecks.run_all_checks()`), run from `on_ready`; results stored in `runtime_state.startup_check_results`. Admin alerts/startup summaries go through `src/services/admin_notifier.py` (`bot.notifier`).

## CI/CD

`.github/workflows/deploy-discord-bot.yml` deploys on push to `main`/`production`, **but only when the commit message starts with `Merge pull request`** (i.e. merged PRs). Runs on a self-hosted runner (`self-hosted, X64, Linux, Veka`) using Docker (`docker compose up -d --build`), writes `.env` from GitHub secrets (`DISCORD_TOKEN`, `DATABASE_URL`) and variables (`ADMIN_IDS`, `OWNER_IDS`, `ADMIN_ALERT_CHANNEL_ID`, `LOG_LEVEL`), and gates success on the log line `"is ready. DB available"` appearing within 60s.
