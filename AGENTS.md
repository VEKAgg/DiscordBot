# AGENTS.md — VEKA Discord Bot

Canonical guide for all coding agents (Claude Code, Codex, OpenCode, Pi, …). `CLAUDE.md` imports this file — edit here, not there.

> nextcord 3.x professional-networking/community bot. Python ≥3.13, PostgreSQL via asyncpg (the **only** datastore — no Redis, no MongoDB). Package management via `uv`; `pyproject.toml` is the source of truth for dependencies.

## Commands

```bash
cp .env.example .env              # fill in DISCORD_TOKEN and DATABASE_URL (or POSTGRES_*)
uv sync --extra dev               # runtime + dev deps (ruff, mypy, pytest, pre-commit)
pre-commit install                # once after clone
python main.py                    # run locally — needs reachable PostgreSQL
```

Docker: `docker compose -f docker-compose.dev.yml up -d --build` (bot + bundled postgres); `docker compose up -d` (production, external DB via `DATABASE_URL`). Logs: `docker logs veka-discord-bot`. The Dockerfile is multi-stage and installs the locked dependencies with `uv sync --locked` (from `uv.lock`).

**Lint / format / typecheck — run before every push:**

```bash
ruff check . --fix && ruff format .
mypy src/ main.py --explicit-package-bases
pre-commit run --all-files        # whitespace/yaml/toml checks, ruff (--fix --unsafe-fixes), ruff-format, mypy, pytest
```

**Tests** — 188 tests; unit tests need no DB or network (DB, bot, interaction and context are mocked in `tests/conftest.py`). `tests/test_schema_postgres.py` is skipped unless `VEKA_TEST_DATABASE_URL` points at an **empty, disposable** PostgreSQL database (its `public` schema is dropped); it applies every migration with the real runner and `prepare()`s every static SQL string in `src/`. CI runs it against a service container:

```bash
uv run --extra dev pytest tests/ -v                                   # all
uv run --extra dev pytest tests/test_safety.py -v                     # one file
uv run --extra dev pytest tests/test_safety.py::TestMapExceptionToMessage::test_database_unavailable   # one test
uv run --extra dev pytest -k guild_settings                           # by keyword
```

`asyncio_mode = "auto"` — async tests need no decorator. `tests/test_cog_loading.py` loads every entry in `EXTENSIONS`, so a broken import in any cog fails the suite.

Tool config (`pyproject.toml`): ruff `line-length=120`, `quote-style="single"`, selects `F/I/UP/B/W/ARG`, ignores `E501/B008`. mypy `check_untyped_defs=true`, `ignore_missing_imports=true`, **`disable_error_code=["union-attr"]`** (Discord User/Member unions are noisy — catch these in review).

> `requirements.txt` is generated from `uv.lock` (`uv export --no-dev --no-hashes --format requirements-txt -o requirements.txt`). `pyproject.toml` + `uv.lock` are the source of truth.

## Architecture

- **Entrypoint:** `main.py` → `src/core/app.py:run_bot()` → loads `.env`, `setup_logging()`, `build_bot()`, registers events, loads extensions, `bot.run()`.
- **Startup (`on_ready`, guarded to run once):** set `bot.notifier` → `initialize_database()` (connect, then `db.run_migrations()`) → `StartupChecks.run_all_checks()` (`src/core/checks.py`) → `bot.notifier.send_startup_summary()` → `db_health_check.start()` (30s loop) → `run_cog_ready_hooks(bot)` (each cog's `cog_ready()`) → logs `"<bot> is ready. DB available=<bool> migrations=<ok|degraded>"` (the deploy greps this line) → `bot.sync_all_application_commands()`.
- **Extensions load from an explicit allowlist** — `EXTENSIONS` in `src/core/app.py` (22 entries, dotted `src.cogs.*` paths). A cog not in the list is not loaded; add it there to enable it. Every cog module needs a module-level `setup(bot)`; slash groups use `nextcord.SlashCommandGroup`.
- **Layers:** `src/cogs/` (thin Discord handlers) → `src/services/` (business logic) → `src/database/` (data access).
- **Intents:** `message_content`, `members`, `guilds`, `voice_states`, `presences`.

### Degraded mode (central design theme)

The bot keeps running when the DB, a cog, or a background task fails:

- `src/core/runtime_state.py` — global `runtime_state` dataclass (attached as `bot.runtime_state`): `db_available`, `loaded_cogs`, `failed_cogs`, `degraded_features`, `startup_check_results`, `alert_state_cache`, `last_db_error`, `last_recovery_time`. Source of truth for health/observability.
- DB connect failure at boot → `db_available=False`, `'database'` added to `degraded_features`; boot continues. Migration failure → `'migrations'` degraded, DB stays available.
- `db_health_check` (`@tasks.loop(seconds=30)`) pings the DB, flips `db_available`, and alerts admins on lost/recovered transitions.
- Per-extension load failures are recorded in `failed_cogs`; other cogs still load.

### Database

- Global singleton `from src.database.database import db`. **`$1`/`$2` parameter style.**
- Methods: `fetch`, `fetch_one`/`fetchrow`, `fetchval`, `execute`, `execute_many` (all via `Database._run`). Connection-class failures (incl. `OSError`/timeouts) raise `DatabaseUnavailableError` and flip `runtime_state.db_available = False`; SQL errors raise `DatabaseQueryError` (a subclass, so `except DatabaseUnavailableError` still catches it) and leave the DB marked available. Only argument *types* are logged, never values. Pool has `command_timeout=30s`. Never assume a query succeeded.
- Connection pool strips libpq-only keepalive params (`keepalives`, `tcp_keepalives_*`) that PostgreSQL would reject as unknown server settings.
- **Migrations:** `.sql` files in `migrations/` (001–026; no `002`; `005_` and `005b_` coexist — the duplicate check compares the full prefix incl. letter suffix), applied in filename order on connect, tracked in `schema_migrations` by filename. **Never rename an applied migration**; if you must, add the old name to `LEGACY_MIGRATION_NAMES` in `src/database/migrations.py` (as for `005b`). Add new ones as `migrations/0NN_name.sql` with the next unused number. Make them idempotent (`IF NOT EXISTS`, guarded `DO $$` blocks) and use `TIMESTAMPTZ DEFAULT NOW()`. Discord IDs are `BIGINT`; `users.id` is an internal serial PK — don't mix them.

### Per-guild settings

Channel/role config is per guild in the `guild_settings` table, read via `from src.services.guild_settings_service import guild_settings_service` (`get_settings`, `update_settings`, `invalidate_cache`, `resolve_channel`; in-memory cache). Configured by staff with `/setup` / `!setup` (`src/cogs/admin/setup.py`). The channel-ID constants in `src/config/config.py` (`LOGS_CHANNEL_ID`, `STAFF_CHANNEL_ID`, `PUBLIC_BOT_COMMANDS_CHANNEL_ID`, `STAFF_BOT_COMMANDS_CHANNEL_ID`, `OWNER_DISCORD_ID`, …) are **deprecated fallbacks** only — new code should resolve channels through the service.

## Conventions

- **Dual command surface:** features define both a `!`-prefix command (prefix hardcoded in `src/config/config.py`) and a slash command, usually side by side in the same cog. Keep both in sync.
- **Safety wrappers** (`src/utils/safety.py`): `@safe_command(requires_db=True)` / `@safe_slash_command(requires_db=True)` short-circuit when the DB is down, catch and log unexpected exceptions, and reply with an error embed. `safe_send(target, ...)` handles both `Context` and `Interaction` (responded or not) — prefer it over `ctx.send` / `interaction.response`. `@safe_background_task(name=...)` wraps `@tasks.loop` bodies and alerts admins after ≥3 consecutive failures.
- **Domain exceptions** `DatabaseUnavailableError`, `ValidationError`, `ExternalRequestError` are mapped to user messages centrally (`_handle_command_error_common` in `app.py`, `map_exception_to_message`).
- **Embeds** (`src/utils/embeds.py`): all user-facing output uses `veka_embed`, `success_embed`, `error_embed`, `info_embed`, `alert_embed`. Pass `contributor_source=__name__` so the footer attribution resolves via `_STATIC_CONTRIBUTOR_MAP` (keyed by full module path).
- **Security** (`from src.utils.security import ...`): `rate_limit('bucket')`, `InputValidator`/`sanitize`/`validate_id`/`is_safe`, `audit_log`/`audit_action`, and RBAC `require_verified`/`require_staff`/`require_mod`/`require_admin`/`require_founder`. Role hierarchy: USER < VERIFIED < INTERN < DONATOR < ACTIVE_PRO < STAFF < ADMIN < FOUNDER; `require_mod()` is an alias for `require_staff()`. RBAC decorators work for both prefix and slash commands.
- **Two parallel auth systems (intentional):** `admin_only()`/`staff_only()`/`manage_guild_only()`/`bot_operator_only()` in `safety.py` (ID lists + Discord permissions) and the RBAC `require_*` decorators (role names). Don't consolidate.
- **Slash-command permission checks:** nextcord **ignores `commands.check` on application commands**. Every guard must go through `permission_guard(predicate, message)` in `safety.py` (all the decorators above and `guild_gate.main_server_only`/`owner_in_external_only` do). Put guards directly under `@slash_command`/`@subcommand`. Add privileged commands to `PRIVILEGED_SLASH_COMMANDS` in `tests/test_permissions.py`. Bot-wide actions (reloading code, global settings) use `bot_operator_only()`.
- **Channels are resolved inside the invoking guild only** (`guild_settings_service.resolve_channel(guild, ...)` / `guild.get_channel`). Never `bot.get_channel(<config fallback>)` from a guild-scoped path — that posts into the main server from other servers.
- **Mentions:** the bot defaults to `AllowedMentions(everyone=False, roles=False)`. A send that must ping a role or @everyone passes `allowed_mentions=` explicitly, and the mention goes in `content` (mentions inside embeds never notify).
- **Logging:** `logging.getLogger('VEKA.<area>')` or `get_logger('VEKA.<area>')` from `src/utils/logger.py`. Rotating file handler (5 MB × 3); level from `LOG_LEVEL`.
- **Time:** use `datetime.now(UTC)`, never `utcnow()`.
- **Background work:** use `spawn(coro, name=...)` from `src/core/lifecycle.py` (keeps a reference, logs exceptions) — never bare `asyncio.create_task`/`ensure_future`. Callbacks from other threads (e.g. voice `after=`) must use `asyncio.run_coroutine_threadsafe(coro, bot.loop)`.
- **Cog lifecycle (nextcord ≠ discord.py):** nextcord never calls `cog_load`, and calls `cog_unload` **synchronously**. Put async startup in `async def cog_ready(self)` (called once per cog instance from `on_ready` after the DB is up, and after `/admin reloadcog`); keep `cog_unload` sync and `spawn` any async cleanup. `tests/test_lifecycle.py` enforces this.
- **Images:** CPU-bound Pillow work (`src/utils/card_generator.py`) runs in `asyncio.to_thread(...)`.
- **Config:** single `.env`. `DATABASE_URL` or individual `POSTGRES_*` vars. Comma-separated ID lists: `ADMIN_IDS`, `OWNER_IDS`, `FOUNDER_IDS`, `STAFF_IDS`, `INTERN_IDS`, `DONATOR_IDS`, `ACTIVE_PRO_IDS`.

## Notable subsystems

- **Honeypot** (`src/cogs/admin/honeypot.py`): trap channels that punish non-bot, non-webhook posters (`softban`/`ban`/`timeout`/`role`/`log`). Per-guild cooldown from `guild_settings.honeypot_cooldown_seconds`. Acts first (ban/softban purge server-side via `delete_message_seconds`, 0–7 days); timeout/role actions get a bounded bulk purge in the background. Members with Manage Messages/Administrator, the owner, and anyone at/above the bot's top role are exempt (logged as `exempt`). Channel config is cached in memory and not invalidated on external DB changes.
- **Mass unban** (`src/cogs/admin/massunban.py`): admin-only, double confirmation, `preview` subcommand, resumable DB-backed jobs (`massunban_jobs`, `massunban_job_items`), sequential unbans with one worker per job (lock) and 429 pause/resume, resumes interrupted jobs in `cog_ready()`. Every ban is recorded in `audit_logs` (`ban_executed`) by the `on_member_ban` listener. **Limitation:** Discord's ban list has no timestamps or moderator, so date/moderator filters only match bans the bot recorded; unaudited bans are **excluded** unless `include_unaudited:true` (slash only, never with a moderator filter). Selection logic: `match_bans()`.
- **Moderation** (`src/cogs/admin/moderation.py`): `warnings` table (snowflake `BIGINT` columns since 022) with auto-escalation to mute/ban at per-guild thresholds; role-hierarchy checks (`_hierarchy_refusal`); escalations write `audit_logs`; `/modstats` reads `warnings` + `audit_logs`.
- **RPG/activity** (`src/cogs/rpg/rpg_manager.py`): XP with streak multipliers, daily rollups in `user_activity_daily`, category leaderboards, monthly season snapshots, Pillow rank cards.
- **Radio** (`src/cogs/radio/radio.py`): streams fixed Icecast/SHOUTcast URLs (`RADIO_STATIONS`) via FFmpeg — no yt-dlp.
- **Feeds** (`src/cogs/resources/feeds.py`, `src/services/rss_service.py`): DB-backed `feed_subscriptions`; dedupe per subscription in `feed_seen_items(subscription_id, item_guid)`. User-supplied URLs are fetched only through `src/utils/http.fetch_public_url` (http/https only, public IPs only via `PublicOnlyResolver`, redirects re-checked, 2 MB cap). `/feed add|remove|test` need Manage Server.

## CI/CD

`.github/workflows/ci.yml` runs on every push/PR: ruff (lint + format check), mypy, pytest with a PostgreSQL 17 service (`VEKA_TEST_DATABASE_URL`), `pip-audit` on the locked runtime deps (PyNaCl advisories ignored — see `MIGRATION_NOTES.md`), and a Docker build. Keep mypy at zero errors.

`.github/workflows/deploy-discord-bot.yml` deploys on push to `main`/`production` **only when the commit message starts with `Merge pull request`** (merged PRs). Self-hosted runner (`self-hosted, X64, Linux, Veka`); writes `.env` from secrets (`DISCORD_TOKEN`, `DATABASE_URL`) and variables (`ADMIN_IDS`, `OWNER_IDS`, `ADMIN_ALERT_CHANNEL_ID`, `LOG_LEVEL`); `docker compose up -d --build`; passes only if `"is ready. DB available=True"` appears in the logs within 60s, and emits a warning annotation if that line says `migrations=degraded`. Development happens on `dev`; PR `dev` → `main` to deploy.

## Known issues (open)

See `AUDIT_REPORT.md` (remediation status per finding) and `MIGRATION_NOTES.md`. Still open:

1. `alert_state_cache` is shared by several subsystems with ad-hoc key patterns; per-URL RSS failure keys are unbounded.
2. `_is_staff_user` in `safety.py` fakes a context with `SimpleNamespace` to call RBAC — fragile coupling.
3. Unique constraint on `profiles.user_id` is duplicated across migrations `005` and `006` (harmless).
4. Empty leftover dirs `src/cogs/gamification/` and `src/cogs/workshops/`; `src/services/quiz_service.py` has no cog.
5. XP, leaderboards, profiles and the marketplace are global across guilds (pending a product decision).
6. Coding minutes are stored in `total_gaming_minutes`.
7. The container still runs as root (the bind-mounted `./logs` must stay writable).

## History

Roadmap phases 1–6 are complete (2026-07 → 2026-09): radio overhaul + migration integrity, multi-guild `guild_settings` + `/setup`, moderation warnings/honeypot/massunban preview, activity/XP/leaderboards + rank cards, community/marketplace/directory/feeds/welcome cards, and the pytest suite. Full specs and the 2026-07-21 audit live in git history (`git log -- AGENTS.md`).
