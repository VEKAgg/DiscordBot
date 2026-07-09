# AGENTS.md — VEKA Discord Bot

> Python ≥3.13, nextcord, PostgreSQL (asyncpg). No test framework. Package management via `uv`.

## Index

- [Quick Start](#quick-start) — setup, run, lint
- [Pending](#pending) — stale files, known gaps
- [Architecture](#architecture) — entrypoint, cogs, layers, degraded mode
- [Database](#database) — asyncpg, migrations, parameter style
- [Conventions](#conventions) — dual commands, safety wrappers, embeds, RBAC
- [CI/CD](#cicd) — deployment gate, runner
- [Honeypot Anti-Spam System](#honeypot-anti-spam-system) — trap channels, moderation actions, and schema

## Quick Start

```bash
cp .env.example .env              # fill in DISCORD_TOKEN and DATABASE_URL
uv sync --extra dev               # install runtime + dev deps
pre-commit install                 # once after clone
python main.py                     # needs reachable PostgreSQL
```

Docker: `docker compose -f docker-compose.dev.yml up -d --build` (bot + bundled postgres); `docker compose up -d` (production, expects external DB via `DATABASE_URL`). Logs: `docker logs veka-discord-bot`.

**Lint / Format / Typecheck — run before every push:**

```bash
ruff check . --fix && ruff format .
mypy src/ main.py --explicit-package-bases
```

Config in `pyproject.toml`. Ruff: `line-length=120`, `quote-style="single"`, selects `F/I/UP/B/W/ARG`, ignores `E501/B008`. Mypy: `ignore_missing_imports=true`, `check_untyped_defs=true`, **`disable_error_code=["union-attr"]`** (Discord User/Member unions are noisy). Pre-commit runs trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-added-large-files, ruff (with `--fix --unsafe-fixes`), ruff-format, and mypy — `pre-commit run --all-files`.

## Pending

- **`CLAUDE.md` is stale** — it lists only 6 loaded extensions while `src/core/app.py` actually loads 18. Follow this file (`AGENTS.md`) instead.
- **Hardcoded channel IDs** in `src/config/config.py` (not in `.env`): `STAFF_BOT_COMMANDS_CHANNEL_ID`, `STAFF_CHANNEL_ID`, `PUBLIC_BOT_COMMANDS_CHANNEL_ID`, `LOGS_CHANNEL_ID`.

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

## Honeypot Anti-Spam System

This system implements trap channels to catch and automatically punish spam bots.

### Database Schema
- **`honeypots`**: Track channels configured as traps.
  - `id` (serial PK), `guild_id` (bigint), `channel_id` (bigint), `action_type` (varchar: `softban`, `ban`, `timeout`, `role`), `delete_message_days` (int, nullable), `timeout_hours` (int, nullable), `role_id` (bigint, nullable), `enabled` (boolean), `created_by` (bigint), `created_at`, `updated_at`. Unique index on `(guild_id, channel_id)`.
- **`honeypot_logging_config`**: Alert and notification settings.
  - `guild_id` (bigint PK), `logging_channel_id` (bigint, nullable), `notification_role_id` (bigint, nullable), `enabled` (boolean), `updated_by` (bigint), `updated_at`.
- **`honeypot_events`**: Audit log of triggered honeypots.
  - `id` (serial PK), `guild_id`, `channel_id`, `user_id`, `honeypot_id`, `action_type`, `action_result` (varchar: `success`, `failed`), `message_id` (bigint, nullable), `message_content_preview` (text, nullable), `created_at`. Indexes on `(guild_id, created_at desc)` and `(user_id)`.

### Core Behaviors & Events
- **Trigger**: Non-bot, non-webhook messages in any channel registered in `honeypots` where `enabled = True`.
- **Moderation Actions**:
  - `softban`: Ban member, delete messages (default 1 day), immediately unban (acts as kick + purge).
  - `ban`: Ban member, delete messages.
  - `timeout`: Put member in timeout (timeout duration validated against Discord 28-day limit).
  - `role`: Assign a configured role (requires role hierarchy and bot permission validation).
- **Graceful Degradation**: If the database is offline, triggers must still attempt to execute moderation actions and log locally. Logging channel failure should not prevent moderation execution.
- **Deduplication / Cooldown**: Add brief event-cooldowns to prevent race conditions from multi-message bursts.

### Commands to Implement (Slash Groups)
- `/honeypot create <channel> [delete_messages_days]`: Creates softban honeypot.
- `/honeypot list`: Paginated table of server honeypots.
- `/honeypot view <channel>`: Details of target channel honeypot.
- `/honeypot delete <channel>`: Removes trap channel.
- `/honeypot enable/disable <channel>`: Toggles active status.
- `/honeypot edit ban/timeout/role/softban`: Changes parameters and action type. Must validate role hierarchy / Discord timeout limits.
- `/honeypot test <channel>`: Dry-run check verifying bot permissions and configurations.
- `/logging set channel <channel>`: Sets output for logging triggers.
- `/logging set/clear role <role>`: Configures notification ping on trigger.
- `/logging view`: Displays logging configuration.

### Permissions & UI Styling
- **Permissions**: Command execution requires `manage_guild`, `manage_channels`, or `administrator`. Trigger execution requires standard validation of bot roles and hierarchy permissions (`ban_members`, `moderate_members`, `manage_roles`).
- **UI Styling**: Use orange accent, header `VEKA Bot` (linking to `https://veka.gg`), no emojis in user errors, and standard dynamic footers. Log triggers to the logging channel with details of target user, deleted message days/hours, content preview (if enabled), and role pings.
- **Architecture**: Placed in `src/cogs/admin/honeypot.py` (or `src/cogs/moderation/honeypot.py`), with query handling via database wrappers. Use existing wrappers (`@safe_slash_command`, `safe_send()`, `success_embed`, `error_embed`).
