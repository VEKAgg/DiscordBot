# AGENTS.md — VEKA Discord Bot

Python `>=3.13`, no test framework. Package management via `uv` (`uv.lock` is source of truth; `requirements.txt` kept for Docker images without uv).

## Setup

```bash
cp .env.example .env              # fill in DISCORD_TOKEN and DATABASE_URL
uv sync --extra dev               # install runtime + dev deps
pre-commit install                 # once after clone
python main.py                     # needs reachable PostgreSQL
```

Docker: `docker compose -f docker-compose.dev.yml up -d --build` (bot + bundled postgres); `docker compose up -d` (production, expects external DB via `DATABASE_URL`). Logs: `docker logs veka-discord-bot`.

## Lint / Format / Typecheck (run before every push)

```bash
ruff check . --fix && ruff format .
mypy src/ main.py --explicit-package-bases
```

Config in `pyproject.toml`. Ruff: `line-length=120`, `quote-style="single"`, selects `F/I/UP/B/W/ARG`, ignores `E501/B008`. Mypy: `ignore_missing_imports=true`, `check_untyped_defs=true`, **`disable_error_code=["union-attr"]`** (Discord User/Member unions are noisy). Pre-commit runs ruff (with `--fix --unsafe-fixes`) + ruff-format + mypy — `pre-commit run --all-files`.

## Architecture

- **Entrypoint:** `main.py` → `src/core/app.py:run_bot()` → loads `.env`, sets up logging (`%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s`), builds bot, loads extensions, `bot.run()`.
- **Extensions loaded from explicit allowlist** (`EXTENSIONS` in `src/core/app.py`):
  `src.cogs.admin.basic`, `src.cogs.admin.help`, `src.cogs.admin.health`, `src.cogs.admin.moderation`, `src.cogs.admin.notifications`, `src.cogs.networking.networking`, `src.cogs.marketplace.marketplace`, `src.cogs.marketplace.reviews`, `src.cogs.resources.feeds`, `src.cogs.mentorship`, `src.cogs.marketplace_enhanced`, `src.cogs.portfolio.portfolio_manager`, `src.cogs.radio.radio`, `src.cogs.rpg.rpg_manager`, `src.cogs.stats`, `src.cogs.external.info`, `src.cogs.external.export`, `src.cogs.status`.
  Add a cog's dotted module path to `EXTENSIONS` to enable it. Unloaded stubs: `gamification/` (intentionally disabled), `quiz.py`, `workshops/`.
- **Degraded-mode:** DB/cog failures never crash the bot. `bot.runtime_state` (`src/core/runtime_state.py`) tracks `db_available`, `loaded_cogs`, `failed_cogs`, `degraded_features`, `startup_check_results`, `alert_state_cache`, `last_db_error`, `last_recovery_time`.
- **Layers:** `src/cogs/` (thin command handlers) → `src/services/` (business logic) → `src/database/` (data access).
- **Startup:** `on_ready` → set `bot.notifier` → `initialize_database()` → `StartupChecks.run_all_checks()` → `bot.notifier.send_startup_summary()` → `db_health_check.start()` (30s loop) → `bot.sync_all_application_commands()`.
- **Each cog** needs a module-level `setup(bot)` function. Cog classes are `commands.Cog` subclasses; slash groups use `nextcord.SlashCommandGroup`.
- **Intents:** `message_content`, `members`, `guilds`, `voice_states`, `presences` enabled.
- **GitHub:** `VEKAgg/DiscordBot`.

## Database

- PostgreSQL via **asyncpg** (only datastore — no Redis, no MongoDB).
- Global singleton: `from src.database.database import db`.
- **`$1`/`$2` parameter style** (asyncpg native).
- Methods: `fetch`, `fetch_one`/`fetchrow`, `fetchval`, `execute`, `execute_many`. All raise `DatabaseUnavailableError` on failure and flip `runtime_state.db_available = False`.
- Migrations: `.sql` files in `migrations/`, auto-applied on connect by `db.run_migrations()`, tracked in `schema_migrations` table. Add as `migrations/00N_name.sql`.
- Connection pool strips libpq-only keepalive params (`keepalives`, `tcp_keepalives_*`) to avoid PostgreSQL rejecting them as unknown server_settings.

## Conventions

- **Dual command surface:** prefix (`!`, hardcoded in `src/config/config.py`) and slash commands side by side in the same cog. Keep both in sync.
- Use safety wrappers from `src/utils/safety.py`: `@safe_command(requires_db=True)`, `@safe_slash_command(requires_db=True)`, `safe_send()`, `@safe_background_task(name=...)` (alerts admins after 3 consecutive failures).
- All user-facing output uses embed helpers from `src/utils/embeds.py`: `veka_embed`, `success_embed`, `error_embed`, `info_embed`, `alert_embed`. Pass `contributor_source=__name__` (resolved against `_STATIC_CONTRIBUTOR_MAP` keyed by full module path).
- Logging: `logging.getLogger('VEKA.<area>')` or `get_logger('VEKA.<area>')` from `src/utils/logger.py`.
- Rate limiting: `@rate_limit('bucket_name')` from `src.utils.security`.
- RBAC from `src.utils.security`: `@require_mod()`, `@require_admin()`, `@require_verified()`. Also `admin_only()`/`staff_only()` in `safety.py` (parallel auth via `ADMIN_IDS`/`OWNER_IDS` from config). RBAC hierarchy: USER < VERIFIED < MODERATOR < ADMIN < OWNER.
- Single `.env` file for config. Either `DATABASE_URL` or individual `POSTGRES_*` vars. Seven comma-separated ID env vars (`ADMIN_IDS`, `OWNER_IDS`, `FOUNDER_IDS`, `STAFF_IDS`, `INTERN_IDS`, `DONATOR_IDS`, `ACTIVE_PRO_IDS`). `load_dotenv()` called in both `config.py` and `app.py`.

## CI/CD

`.github/workflows/deploy-discord-bot.yml` — deploys on push to `main`/`production` **only when commit message starts with `Merge pull request`**. Self-hosted runner (`self-hosted, X64, Linux, Veka`). Writes `.env` from secrets/variables, `docker compose up -d --build`. Gates on log line `"is ready. DB available=True"` appearing within 60s.
