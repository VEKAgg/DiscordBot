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

Docker: `docker compose -f docker-compose.dev.yml up -d --build` (bot + bundled postgres); `docker compose up -d` (production, external DB via `DATABASE_URL`). Logs: `docker logs veka-discord-bot`. The Dockerfile installs with `pip install .` (from `pyproject.toml`).

**Lint / format / typecheck — run before every push:**

```bash
ruff check . --fix && ruff format .
mypy src/ main.py --explicit-package-bases
pre-commit run --all-files        # whitespace/yaml/toml checks, ruff (--fix --unsafe-fixes), ruff-format, mypy, pytest
```

**Tests** — 126 tests, run in <1s, no DB or network needed (DB, bot, interaction and context are mocked in `tests/conftest.py`):

```bash
uv run --extra dev pytest tests/ -v                                   # all
uv run --extra dev pytest tests/test_safety.py -v                     # one file
uv run --extra dev pytest tests/test_safety.py::TestMapExceptionToMessage::test_database_unavailable   # one test
uv run --extra dev pytest -k guild_settings                           # by keyword
```

`asyncio_mode = "auto"` — async tests need no decorator. `tests/test_cog_loading.py` loads every entry in `EXTENSIONS`, so a broken import in any cog fails the suite.

Tool config (`pyproject.toml`): ruff `line-length=120`, `quote-style="single"`, selects `F/I/UP/B/W/ARG`, ignores `E501/B008`. mypy `check_untyped_defs=true`, `ignore_missing_imports=true`, **`disable_error_code=["union-attr"]`** (Discord User/Member unions are noisy — catch these in review).

> `requirements.txt` is stale (missing `psutil`, `Pillow`, `nextcord[voice]`). Use `uv` / `pyproject.toml`.

## Architecture

- **Entrypoint:** `main.py` → `src/core/app.py:run_bot()` → loads `.env`, `setup_logging()`, `build_bot()`, registers events, loads extensions, `bot.run()`.
- **Startup (`on_ready`, guarded to run once):** set `bot.notifier` → `initialize_database()` (connect, then `db.run_migrations()`) → `StartupChecks.run_all_checks()` (`src/core/checks.py`) → `bot.notifier.send_startup_summary()` → `db_health_check.start()` (30s loop) → `bot.sync_all_application_commands()` → logs `"<bot> is ready. DB available=<bool>"` (CI greps this line).
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
- Methods: `fetch`, `fetch_one`/`fetchrow`, `fetchval`, `execute`, `execute_many` — all raise `DatabaseUnavailableError` on failure and flip `runtime_state.db_available = False`. Never assume a query succeeded.
- Connection pool strips libpq-only keepalive params (`keepalives`, `tcp_keepalives_*`) that PostgreSQL would reject as unknown server settings.
- **Migrations:** `.sql` files in `migrations/` (001–021; no `002`; `005_` and `005b_` coexist), applied in filename order on connect, tracked in `schema_migrations`. Add new ones as `migrations/0NN_name.sql` with the next unused number. Use `TIMESTAMPTZ DEFAULT NOW()` for timestamps and `IF NOT EXISTS` guards. Runner helpers: `src/database/migrations.py`.

### Per-guild settings

Channel/role config is per guild in the `guild_settings` table, read via `from src.services.guild_settings_service import guild_settings_service` (`get_settings`, `update_settings`, `invalidate_cache`, `resolve_channel`; in-memory cache). Configured by staff with `/setup` / `!setup` (`src/cogs/admin/setup.py`). The channel-ID constants in `src/config/config.py` (`LOGS_CHANNEL_ID`, `STAFF_CHANNEL_ID`, `PUBLIC_BOT_COMMANDS_CHANNEL_ID`, `STAFF_BOT_COMMANDS_CHANNEL_ID`, `OWNER_DISCORD_ID`, …) are **deprecated fallbacks** only — new code should resolve channels through the service.

## Conventions

- **Dual command surface:** features define both a `!`-prefix command (prefix hardcoded in `src/config/config.py`) and a slash command, usually side by side in the same cog. Keep both in sync.
- **Safety wrappers** (`src/utils/safety.py`): `@safe_command(requires_db=True)` / `@safe_slash_command(requires_db=True)` short-circuit when the DB is down, catch and log unexpected exceptions, and reply with an error embed. `safe_send(target, ...)` handles both `Context` and `Interaction` (responded or not) — prefer it over `ctx.send` / `interaction.response`. `@safe_background_task(name=...)` wraps `@tasks.loop` bodies and alerts admins after ≥3 consecutive failures.
- **Domain exceptions** `DatabaseUnavailableError`, `ValidationError`, `ExternalRequestError` are mapped to user messages centrally (`_handle_command_error_common` in `app.py`, `map_exception_to_message`).
- **Embeds** (`src/utils/embeds.py`): all user-facing output uses `veka_embed`, `success_embed`, `error_embed`, `info_embed`, `alert_embed`. Pass `contributor_source=__name__` so the footer attribution resolves via `_STATIC_CONTRIBUTOR_MAP` (keyed by full module path).
- **Security** (`from src.utils.security import ...`): `rate_limit('bucket')`, `InputValidator`/`sanitize`/`validate_id`/`is_safe`, `audit_log`/`audit_action`, and RBAC `require_verified`/`require_staff`/`require_mod`/`require_admin`/`require_founder`. Role hierarchy: USER < VERIFIED < INTERN < DONATOR < ACTIVE_PRO < STAFF < ADMIN < FOUNDER; `require_mod()` is an alias for `require_staff()`. RBAC decorators work for both prefix and slash commands.
- **Two parallel auth systems (intentional):** `admin_only()`/`staff_only()` in `safety.py` check `ADMIN_IDS`/`OWNER_IDS` from config — the fallback for DMs or when role detection fails. Don't consolidate.
- **Logging:** `logging.getLogger('VEKA.<area>')` or `get_logger('VEKA.<area>')` from `src/utils/logger.py`. Rotating file handler (5 MB × 3); level from `LOG_LEVEL`.
- **Time:** use `datetime.now(UTC)`, never `utcnow()`. Use `asyncio.create_task()` and keep a reference to the task.
- **Images:** CPU-bound Pillow work (`src/utils/card_generator.py`) runs in `asyncio.to_thread(...)`.
- **Config:** single `.env`. `DATABASE_URL` or individual `POSTGRES_*` vars. Comma-separated ID lists: `ADMIN_IDS`, `OWNER_IDS`, `FOUNDER_IDS`, `STAFF_IDS`, `INTERN_IDS`, `DONATOR_IDS`, `ACTIVE_PRO_IDS`.

## Notable subsystems

- **Honeypot** (`src/cogs/admin/honeypot.py`): trap channels that punish non-bot, non-webhook posters (`softban`/`ban`/`timeout`/`role`/`log`). Per-guild cooldown from `guild_settings.honeypot_cooldown_seconds`. Channel config is cached in memory and not invalidated on external DB changes.
- **Mass unban** (`src/cogs/admin/massunban.py`): admin-only, double confirmation, `preview` subcommand, resumable DB-backed jobs (`massunban_jobs`, `massunban_job_items`), sequential unbans with adaptive 429 backoff, resumes interrupted jobs in `cog_load()`. **Limitation:** Discord's ban list has no timestamps or moderator, so date/moderator filters only match bans recorded in the bot's own `audit_logs`.
- **Moderation** (`src/cogs/admin/moderation.py`): `warnings` table with auto-escalation to mute/ban at per-guild thresholds; `/modstats`.
- **RPG/activity** (`src/cogs/rpg/rpg_manager.py`): XP with streak multipliers, daily rollups in `user_activity_daily`, category leaderboards, monthly season snapshots, Pillow rank cards.
- **Radio** (`src/cogs/radio/radio.py`): streams fixed Icecast/SHOUTcast URLs (`RADIO_STATIONS`) via FFmpeg — no yt-dlp.
- **Feeds** (`src/cogs/resources/feeds.py`, `src/services/rss_service.py`): DB-backed `feed_subscriptions` with `feed_seen_items` dedup.

## CI/CD

`.github/workflows/deploy-discord-bot.yml` deploys on push to `main`/`production` **only when the commit message starts with `Merge pull request`** (merged PRs). Self-hosted runner (`self-hosted, X64, Linux, Veka`); writes `.env` from secrets (`DISCORD_TOKEN`, `DATABASE_URL`) and variables (`ADMIN_IDS`, `OWNER_IDS`, `ADMIN_ALERT_CHANNEL_ID`, `LOG_LEVEL`); `docker compose up -d --build`; passes only if `"is ready. DB available=True"` appears in the logs within 60s. Development happens on `dev`; PR `dev` → `main` to deploy.

## Known issues (open)

1. **Startup duplicate-prefix check rejects `005` + `005b`.** `db.run_migrations()` matches `^(\d{3})`, so `005_community_additions.sql` and `005b_guild_and_rss_schema.sql` both count as `005` → `RuntimeError` → no migrations run and `'migrations'` is marked degraded. `tests/test_migrations.py` allows the `005b` suffix, so the tests and the runtime check disagree. Fix one or the other before adding migrations.
2. `runtime_state.startup_time` is set at import, not in `on_ready`, so uptime is slightly inflated.
3. `massunban.py` `_update_job_progress` interpolates a whitelisted column name into SQL (not user input, but breaks the parameterized-only convention).
4. `alert_state_cache` is shared by several subsystems with ad-hoc key patterns.
5. `_is_staff_user` in `safety.py` fakes a context with `SimpleNamespace` to call RBAC — fragile coupling.
6. Unique constraint on `profiles.user_id` is duplicated across migrations `005` and `006` (harmless).
7. Empty leftover dirs `src/cogs/gamification/` and `src/cogs/workshops/` (only `__pycache__`); `src/services/quiz_service.py` has no cog.

## History

Roadmap phases 1–6 are complete (2026-07 → 2026-09): radio overhaul + migration integrity, multi-guild `guild_settings` + `/setup`, moderation warnings/honeypot/massunban preview, activity/XP/leaderboards + rank cards, community/marketplace/directory/feeds/welcome cards, and the pytest suite. Full specs and the 2026-07-21 audit live in git history (`git log -- AGENTS.md`).
