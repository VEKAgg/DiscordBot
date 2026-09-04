# AGENTS.md — VEKA Discord Bot

> Python ≥3.13, nextcord, PostgreSQL (asyncpg). No test framework. Package management via `uv`.

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

## Architecture

- **Entrypoint:** `main.py` → `src/core/app.py:run_bot()` → loads `.env`, sets up logging (`%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s`), builds bot, loads extensions, `bot.run()`.
- **Extensions loaded from explicit allowlist** (`EXTENSIONS` in `src/core/app.py` — 20 entries):
  `src.cogs.admin.basic`, `src.cogs.admin.help`, `src.cogs.admin.health`, `src.cogs.admin.moderation`, `src.cogs.admin.notifications`, `src.cogs.admin.honeypot`, `src.cogs.networking.networking`, `src.cogs.marketplace.marketplace`, `src.cogs.marketplace.reviews`, `src.cogs.resources.feeds`, `src.cogs.mentorship`, `src.cogs.marketplace_enhanced`, `src.cogs.portfolio.portfolio_manager`, `src.cogs.radio.radio`, `src.cogs.rpg.rpg_manager`, `src.cogs.stats`, `src.cogs.external.info`, `src.cogs.external.export`, `src.cogs.status`.
  Add a cog's dotted module path to `EXTENSIONS` to enable it.
- **Degraded-mode:** DB/cog failures never crash the bot. `bot.runtime_state` (`src/core/runtime_state.py`) tracks `db_available`, `loaded_cogs`, `failed_cogs`, `degraded_features`, `startup_check_results`, `alert_state_cache`, `last_db_error`, `last_recovery_time`.
- **Layers:** `src/cogs/` (thin command handlers) → `src/services/` (business logic) → `src/database/` (data access).
- **Startup:** `on_ready` → set `bot.notifier` → `initialize_database()` → `StartupChecks.run_all_checks()` → `bot.notifier.send_startup_summary()` → `db_health_check.start()` (30s loop) → `bot.sync_all_application_commands()`.
- **Each cog** needs a module-level `setup(bot)` function. Cog classes are `commands.Cog` subclasses; slash groups use `nextcord.SlashCommandGroup`.
- **Intents:** `message_content`, `members`, `guilds`, `voice_states`, `presences` enabled.

## Database

- PostgreSQL via **asyncpg** (only datastore — no Redis, no MongoDB).
- Global singleton: `from src.database.database import db`.
- **`$1`/`$2` parameter style** (asyncpg native).
- Methods: `fetch`, `fetch_one`/`fetchrow`, `fetchval`, `execute`, `execute_many`. All raise `DatabaseUnavailableError` on failure and flip `runtime_state.db_available = False`.
- Migrations: `.sql` files in `migrations/` (currently 001–016), auto-applied on connect by `db.run_migrations()`, tracked in `schema_migrations` table. Add as `migrations/00N_name.sql`. Note: two files share the `005_` prefix — ordering is filesystem-dependent.
- Connection pool strips libpq-only keepalive params (`keepalives`, `tcp_keepalives_*`) to avoid PostgreSQL rejecting them as unknown server_settings.

## Conventions

- **Dual command surface:** prefix (`!`, hardcoded in `src/config/config.py`) and slash commands side by side in the same cog. Keep both in sync.
- Use safety wrappers from `src/utils/safety.py`: `@safe_command(requires_db=True)`, `@safe_slash_command(requires_db=True)`, `safe_send()`, `@safe_background_task(name=...)` (alerts admins after 3 consecutive failures).
- All user-facing output uses embed helpers from `src/utils/embeds.py`: `veka_embed`, `success_embed`, `error_embed`, `info_embed`, `alert_embed`. Pass `contributor_source=__name__` (resolved against `_STATIC_CONTRIBUTOR_MAP` keyed by full module path).
- Logging: `logging.getLogger('VEKA.<area>')` or `get_logger('VEKA.<area>')` from `src/utils/logger.py`.
- Rate limiting: `@rate_limit('bucket_name')` from `src.utils.security`.
- RBAC from `src.utils.security`: `@require_mod()`, `@require_admin()`, `@require_verified()`. Also `admin_only()`/`staff_only()` in `safety.py` (parallel auth via `ADMIN_IDS`/`OWNER_IDS` from config). RBAC hierarchy: USER < VERIFIED < INTERN < DONATOR < ACTIVE_PRO < STAFF < ADMIN < FOUNDER. `@require_mod()` is aliased to `require_staff()` (see issue #27).
- Single `.env` file for config. Either `DATABASE_URL` or individual `POSTGRES_*` vars. Seven comma-separated ID env vars (`ADMIN_IDS`, `OWNER_IDS`, `FOUNDER_IDS`, `STAFF_IDS`, `INTERN_IDS`, `DONATOR_IDS`, `ACTIVE_PRO_IDS`). `load_dotenv()` called in both `config.py` and `app.py`.

## Hardcoded values in `src/config/config.py`

Not in `.env` — requires code change: `STAFF_BOT_COMMANDS_CHANNEL_ID` (1328775724668031126), `STAFF_CHANNEL_ID` (1091908318324334704), `PUBLIC_BOT_COMMANDS_CHANNEL_ID` (1385610318889222226), `LOGS_CHANNEL_ID` (1329192112410857563), `OWNER_DISCORD_ID` (941009204045557842).

## CI/CD

`.github/workflows/deploy-discord-bot.yml` — deploys on push to `main`/`production` **only when commit message starts with `Merge pull request`**. Self-hosted runner (`self-hosted, X64, Linux, Veka`). Writes `.env` from secrets/variables, `docker compose up -d --build`. Gates on log line `"is ready. DB available=True"` appearing within 60s.

## Honeypot Anti-Spam System

Implemented in `src/cogs/admin/honeypot.py` (loaded as `src.cogs.admin.honeypot`). Both `/honeypot` slash group and `!honeypot` prefix group. Traps channels to catch spam bots. Actions: softban, ban, timeout, role. Trigger: non-bot, non-webhook messages in registered channels with `enabled=True`. 5-second dedup cooldown per user per guild. Schema: `honeypots`, `honeypot_logging_config`, `honeypot_events` (migration `014_honeypot_schema.sql`).

## Mass Unban System

Implemented in `src/cogs/admin/massunban.py` (loaded as `src.cogs.admin.massunban`). Slash-only command group `/massunban` with subcommands: `run`, `status`, `cancel`, `recent`. Also `!massunban` prefix group with same subcommands. Admin-only, requires double confirmation (two button clicks). Resumable job model with per-user tracking in DB (`massunban_jobs`, `massunban_job_items` tables, migration `016_massunban_schema.sql`). Sequential unban processing with adaptive rate limiting (base 1.5s interval, progressive backoff on repeated 429s). On rate limit, persists progress and pauses; resumes automatically. DMs unbanned users with apology template on failure. Logs per-user results to `LOGS_CHANNEL_ID` (or `MASSUNBAN_LOG_CHANNEL_ID` if set). Startup resume for interrupted jobs via `cog_load()`.

**Known limitation:** Discord's `Guild.bans()` API does not expose ban timestamps or the moderator who placed the ban. The `start_datetime`, `end_datetime`, and `banned_by` filters only apply to bans logged by this bot via its audit system (`audit_logs` table). Bans placed externally or before the bot was running cannot be filtered by date/moderator — they are included when no filters are specified, or skipped when filters are active.

## Known Issues (Codebase Audit — 2026-07-21)

### CRITICAL

1. ~~**`rss_service.py` queries a column that does not exist in the correct schema**~~ — **FIXED.** Migration ordering issue documented; service uses correct schema.
2. ~~**`bot.loop.create_task()` is deprecated in Python 3.10+**~~ — **FIXED.** Replaced with `asyncio.create_task()` in `massunban.py:198,221,943`.
3. ~~**`on_disconnect` closes the database pool on every gateway disconnect**~~ — **FIXED.** `on_disconnect` now only logs a warning; pool is managed by the health-check loop.

### HIGH

4. ~~**Widespread use of `datetime.utcnow()` (deprecated since Python 3.12)**~~ — **FIXED.** All 11+ usages replaced with `datetime.now(UTC)` across the entire codebase.
5. ~~**`MASSUNBAN_LOG_CHANNEL_ID` is not documented in `.env.example`**~~ — **FIXED.** Added to `.env.example`.
6. **`rss_cache` migration creates naive `TIMESTAMP` columns without timezone** (`migrations/005_guild_and_rss_schema.sql:36`, plus `001`, `003`, `004`, `008`, `010`, `013`). Most older migrations use `TIMESTAMP DEFAULT NOW()` (no timezone) while newer ones (`014`, `015`, `016`) correctly use `TIMESTAMPTZ`. Fix: add a migration to `ALTER TABLE ... ALTER COLUMN ... TYPE TIMESTAMPTZ USING ... AT TIME ZONE 'UTC'` for the affected columns.

### MEDIUM

7. **Radio `_started_at` is not reset to `None` after disconnection** (`radio.py`). `_disconnect()` does not clear it, so `/uptime` will show stale uptime after a radio disconnect/reconnect.

8. ~~**`feeds.py` sends subsequent feed embeds to `interaction.channel` instead of using followup**~~ — **FIXED.** All entries now use `interaction.followup.send()`.

9. ~~**`safe_background_task` decorator only fires the alert on exactly 3 consecutive failures**~~ — **FIXED.** Changed `count == 3` to `count >= 3`.

10. **Honeypot in-memory cache (`_honeypot_cache`) is never invalidated on bot reconnect** (`src/cogs/admin/honeypot.py:32-45`). After a successful load, if a honeypot is added/modified by a different cog reload or external DB change, the cache goes stale indefinitely. Acceptable for normal usage but should be noted.

### LOW

11. **`_update_job_progress` in `massunban.py` uses an f-string SQL query with a whitelisted column** (`massunban.py:878-886`). The `counter_col` value originates from a dict literal (not user input), making SQL injection practically impossible. However, it violates the project's convention of "parameterized queries only".

12. **`runtime_state.startup_time` is set at module import time**, not at `on_ready`. If the bot takes a long time to connect, `/uptime` and status embeds will show inflated uptime. Consider setting `startup_time` inside `on_ready` for accuracy.

13. **`migrate rss_cache` has two `005_` numbered migrations with different schemas**. The `DROP TABLE IF EXISTS` guard in the latter file helps, but the situation is fragile. Document this prominently or renumber the files.

### CRITICAL (Second Pass — 2026-07-21)

14. ~~**Audit log time-based filtering is completely broken**~~ — **FIXED.** Changed `INTERVAL '$2 hours'` to `INTERVAL '1 hour' * $2` in `audit.py:113,128`.

15. ~~**Rate limiter decorator never actually consumes a token**~~ — **FIXED.** Decorator now calls `check()` after the `is_rate_limited()` pass.

16. ~~**`on_command_error` calls `ctx.send()` without `safe_send()`**~~ — **FIXED.** Both error handlers now use `safe_send()` via shared `_handle_command_error_common` helper.

17. ~~**`assert DISCORD_TOKEN is not None` is stripped in `-O` mode**~~ — **FIXED.** Replaced with `if DISCORD_TOKEN is None: raise SystemExit(...)`.

18. ~~**`get_user`/`create_user` has a race condition**~~ — **FIXED.** `get_user` now delegates directly to `create_user` (which uses `ON CONFLICT DO UPDATE`).

19. ~~**Tool config targets wrong Python version**~~ — **FIXED.** ruff `target-version = "py313"`, mypy `python_version = "3.13"`.

20. ~~**`asyncio.create_task()` without storing the reference in `rss_service.py`**~~ — **FIXED.** Tasks stored in `_background_tasks` set with `done_callback` cleanup.

### HIGH (Second Pass — 2026-07-21)

21. ~~**Rate limiter `buckets` dict grows unboundedly**~~ — **FIXED.** Added `cleanup_stale_buckets()` with 10-min TTL and `start_cleanup_loop()`.

22. ~~**`AdminNotifier._get_channel` caches the channel reference forever**~~ — **FIXED.** Added 5-minute TTL cache with automatic re-fetch.

23. ~~**`feeds.py` sends subsequent embeds to `interaction.channel` instead of `followup`**~~ — **FIXED.** (Same as #8.)

24. ~~**`mentorship_service.get_user_stats` always reports 0 active mentorships**~~ — **FIXED.** Now queries all mentorships (not just completed) and counts active separately.

25. ~~**`runtime_state._load_git_metadata()` runs `subprocess.check_output` at module import time**~~ — **FIXED.** Wrapped with `@functools.lru_cache`.

26. ~~**`sanitize_text` uses `html.escape()` which is wrong for Discord**~~ — **FIXED.** Removed `html.escape()` call entirely.

27. ~~**RBAC `require_role` and `require_permission` decorators don't work with slash commands**~~ — **FIXED.** Now detects `Interaction` vs `Context` and uses the appropriate API.

28. ~~**`setup_logging()` ignores the `LOG_LEVEL` env var**~~ — **FIXED.** Now reads `LOG_LEVEL` from config.

### MEDIUM (Second Pass — 2026-07-21)

29. ~~**Directus `_rehost_image` downloads entire images into memory**~~ — **FIXED.** Added `HEAD` request to check `Content-Length` (8 MB limit) before download.

30. ~~**`guild_gate.py` uses `asyncio.ensure_future()` inside a synchronous check predicate**~~ — **FIXED.** Converted to async predicates.

31. ~~**No log rotation**~~ — **FIXED.** Switched to `RotatingFileHandler` (5 MB, 3 backups).

32. ~~**`.env.example` has `POSTGRES_USER=veka_user` but `docker-compose.dev.yml` uses `POSTGRES_USER=veka_bot_user`**~~ — **FIXED.** Aligned `.env.example` to `veka_bot_user`.

33. ~~**`MASSUNBAN_LOG_CHANNEL_ID` missing from `.env.example`**~~ — **FIXED.** (Same as #5.)

34. **`alert_state_cache` mixes heterogeneous data without type safety** (`src/core/runtime_state.py`). At least 5 subsystems write to it with different key patterns. A wrong key could interfere. Low priority — no key collisions have occurred in practice.

35. **`.github/workflows/deploy-discord-bot.yml` is documented in AGENTS.md but does not exist in the repository**. Either it was removed, renamed, or the documentation is stale.

### LOW (Second Pass — 2026-07-21)

36. ~~**Massive duplicated error-handling logic in `app.py`**~~ — **FIXED.** Extracted into `_handle_command_error_common()` shared helper.

37. ~~**`bot.runtime_state` and `bot.notifier` are monkey-patched with `# type: ignore`**~~ — **FIXED.** `bot.notifier` initialized to `None` in `build_bot()`. `runtime_state` assignment kept (acceptable).

38. ~~**`error_embed` uses orange color instead of red**~~ — **FIXED.** Defaults to `nextcord.Color.red()`.

39. **`admin_only()`/`staff_only()` in `safety.py` bypass the RBAC system** — **INTENTIONAL.** Two parallel auth systems: ID-list checks for owner/admin are the fallback when RBAC role detection fails (DMs, missing roles). Consolidating would break DM-based admin commands.

40. ~~**`runtime_state.last_db_error` is never cleared**~~ — **FIXED.** Cleared on successful recovery in `app.py:116`.

41. ~~**`rate_limit` decorator only handles prefix commands**~~ — **FIXED.** Decorator now uses `safe_send()` which handles both Context and Interaction.

42. ~~**`rss_service.py` `datetime.strptime` with fixed format fails on many RSS date formats**~~ — **FIXED.** Added `_parse_entry_date()` supporting RFC 2822 and ISO 8601.

43. ~~**Missing `src/utils/marketplace/__init__.py`**~~ — **FIXED.** Created the file.

44. **Duplicated unique constraint on `profiles.user_id`** across migrations `005_community_additions` and `006_profiles_and_requests`. Harmless but wasteful. Can be cleaned up in a future migration.

45. **`_is_staff_user` in `safety.py` creates a `SimpleNamespace` to fake a context** (`src/utils/safety.py:103-106`). Fragile coupling — if `rbac.get_user_role` changes its context expectations, this breaks silently. Low priority.

## Roadmap & Implementation Instructions

### Phase 1: Foundations, Radio Overhaul & Migration Integrity

> **Status:** Completed (2026-07-21)  
> **Target files:** `src/cogs/radio/radio.py`, `src/database/database.py`, `migrations/`, `pyproject.toml`, removal of `src/cogs/quiz.py`, `src/cogs/workshops/`, `src/cogs/gamification/`.  
> **Rule:** Do not edit bot code unless executing this specification. Follow all project conventions (dual prefix + slash commands, safe wrappers, ruff, mypy).

#### 1. Radio System Overhaul (`src/cogs/radio/radio.py`)
- **Eliminate `yt-dlp` scraping entirely:** Remove `import yt_dlp`, `_extract_stream_url()`, and any YouTube format extraction logic. Radio must stream directly from reliable, 24/7 Icecast/SHOUTcast audio streams.
- **Define `RADIO_STATIONS` dictionary:**
  ```python
  RADIO_STATIONS: dict[str, dict[str, str]] = {
      'lofi': {
          'name': 'Groove Salad (Lofi / Ambient)',
          'url': 'https://ice1.somafm.com/groovesalad-128-mp3',
          'description': 'Downtempo ambient groove and chillout beats',
          'emoji': '☕',
      },
      'ambient': {
          'name': 'Drone Zone',
          'url': 'https://ice6.somafm.com/dronezone-128-mp3',
          'description': 'Deep atmospheric ambient soundscapes',
          'emoji': '🌌',
      },
      'chill': {
          'name': 'Groove Salad Classic',
          'url': 'https://ice6.somafm.com/gsclassic-128-mp3',
          'description': 'Early 2000s nostalgic chillout and downtempo',
          'emoji': '🛋️',
      },
      'spy': {
          'name': 'Secret Agent',
          'url': 'https://ice4.somafm.com/secretagent-128-mp3',
          'description': 'Lounge, spy film themes, and vintage spy jazz',
          'emoji': '🍸',
      },
      'trip': {
          'name': 'The Trip',
          'url': 'https://ice2.somafm.com/thetrip-128-mp3',
          'description': 'Progressive, psychedelic, and electronic vibes',
          'emoji': '🚀',
      },
      'chillhop': {
          'name': 'Chillhop Music',
          'url': 'https://streams.fluxfm.de/Chillhop/mp3-128/streams.fluxfm.de/',
          'description': 'Relaxing lofi hip-hop beats to study and work to',
          'emoji': '🎧',
      },
      'jazz': {
          'name': 'Smooth Jazz Global',
          'url': 'https://smoothjazz.cdnstream1.com/2585_128.mp3',
          'description': 'Modern and classic smooth jazz radio',
          'emoji': '🎷',
      },
  }
  DEFAULT_STATION = 'lofi'
  ```
- **Track current station:** In `RadioManager.__init__`, set `self._active_station = DEFAULT_STATION`.
- **Implement station switching:**
  - Slash command `/radio station <name>` and prefix `!radio station <name>` (with autocomplete for station names on slash command).
  - If bot is currently streaming in voice, call `self._voice_client.stop()` (do NOT disconnect), switch `self._active_station`, and start playing the new stream URL immediately with FFmpeg.
  - Return a success embed indicating the newly active station with its emoji and description.
- **Implement station directory:**
  - Slash command `/radio list` and prefix `!radio list`.
  - Sends a `veka_embed` listing all stations from `RADIO_STATIONS`, highlighting the currently playing station with a `▶ Active` badge.
- **Fix Known Issue #7 (`_started_at` bug):**
  - In `_disconnect()`, ensure `self._started_at = None` is set so `/uptime` and status indicators do not display stale radio uptime after leaving a voice channel.
- **Dependency cleanup:** Remove `yt-dlp` from `pyproject.toml` dependencies if no other module relies on it.

#### 2. Migration System Audit & Duplicate Prefix Guard
- **Rename Duplicate `005_` Migration:**
  - Rename `migrations/005_guild_and_rss_schema.sql` to avoid collisions with `migrations/005_community_additions.sql`.
  - Guard the renamed migration with `CREATE TABLE IF NOT EXISTS` / `DROP TABLE IF EXISTS` to ensure backwards compatibility on databases where `005_guild_and_rss_schema.sql` was already executed.
- **Startup Migration Assertion (`src/database/database.py`):**
  - Inside `db.run_migrations()`, before running migrations, scan all filenames in `migrations/`.
  - Parse the numerical prefix (e.g. `001`, `002`, `005`).
  - Check for duplicate numeric prefixes. If any duplicates exist, raise `RuntimeError("Duplicate migration prefix detected: ...")` and prevent startup.
  - Ensure all files follow strict three-digit sequential numbering (`001_`, `002_`, ...).

#### 3. Database Timestamp Consistency (`migrations/017_timestamptz_conversion.sql`)
- Add migration `migrations/017_timestamptz_conversion.sql` converting all legacy naive `TIMESTAMP` columns to `TIMESTAMPTZ`.
- Target all columns created in migrations 001–013:
  - `users.created_at`, `users.updated_at`, `users.last_active`
  - `audit_logs.created_at`
  - `profiles.created_at`, `profiles.updated_at`
  - `mentorships.created_at`, `mentorships.updated_at`
  - `marketplace_listings.created_at`, `marketplace_listings.updated_at`
  - `rss_cache.published_at`, `rss_cache.fetched_at`
  - Any remaining `TIMESTAMP` column without timezone across the database schema.
- Syntax pattern:
  ```sql
  ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC';
  ```
- All future migrations must strictly use `TIMESTAMPTZ DEFAULT NOW()`.

#### 4. Dead Code Removal
- Delete unloaded stub cogs:
  - `src/cogs/quiz.py`
  - `src/cogs/workshops/` (`src/cogs/workshops/workshop_manager.py`)
  - `src/cogs/gamification/` (`src/cogs/gamification/gamification_manager.py`)
- Remove references to these stubs from comments in `src/core/app.py` and `AGENTS.md`.
- *Note:* Do NOT delete root-level legacy folders (`cogs/`, `commands/`, etc.) during Phase 1; keep them untouched until external references/scripts are verified in later phases.

#### 5. Verification & Quality Gates
- **Format & Lint:** `ruff check . --fix && ruff format .`
- **Type Checking:** `mypy src/ main.py --explicit-package-bases`
- **Pre-commit:** `pre-commit run --all-files`
- Verify bot starts up cleanly with `python main.py` or docker dev environment.

