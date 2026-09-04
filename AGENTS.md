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
- **Extensions loaded from explicit allowlist** (`EXTENSIONS` in `src/core/app.py` — 22 entries):
  `src.cogs.admin.basic`, `src.cogs.admin.help`, `src.cogs.admin.health`, `src.cogs.admin.moderation`, `src.cogs.admin.notifications`, `src.cogs.admin.honeypot`, `src.cogs.admin.massunban`, `src.cogs.admin.setup`, `src.cogs.admin.welcome`, `src.cogs.networking.networking`, `src.cogs.marketplace.marketplace`, `src.cogs.marketplace.reviews`, `src.cogs.resources.feeds`, `src.cogs.mentorship`, `src.cogs.marketplace_enhanced`, `src.cogs.portfolio.portfolio_manager`, `src.cogs.radio.radio`, `src.cogs.rpg.rpg_manager`, `src.cogs.stats`, `src.cogs.external.info`, `src.cogs.external.export`, `src.cogs.status`.
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
- Migrations: `.sql` files in `migrations/` (currently 001–021), auto-applied on connect by `db.run_migrations()`, tracked in `schema_migrations` table. Add as `migrations/00N_name.sql`. Note: two files share the `005_` prefix — ordering is filesystem-dependent.
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

### Phase 2: Multi-Guild Engine & Dynamic Guild Settings

> **Status:** Completed (2026-07-21)  
> **Target files:** `migrations/018_guild_settings_schema.sql` (new), `src/services/guild_settings_service.py` (new), `src/cogs/admin/setup.py` (new), `src/core/app.py`, `src/services/admin_notifier.py`, `src/cogs/admin/massunban.py`, `src/cogs/admin/notifications.py`, `src/cogs/admin/honeypot.py`, `src/cogs/radio/radio.py`, `src/cogs/rpg/rpg_manager.py`, `src/config/config.py`.  
> **Rule:** Do not edit bot code unless executing this specification. Follow all project conventions (dual prefix + slash commands, safe wrappers, ruff, mypy).

#### 1. Guild Settings Migration (`migrations/018_guild_settings_schema.sql`)
- Create `guild_settings` table to store per-server channel and role configurations:
  ```sql
  CREATE TABLE IF NOT EXISTS guild_settings (
      guild_id BIGINT PRIMARY KEY,
      log_channel_id BIGINT,
      staff_channel_id BIGINT,
      alert_channel_id BIGINT,
      public_commands_channel_id BIGINT,
      welcome_channel_id BIGINT,
      radio_channel_id BIGINT,
      leaderboard_channel_id BIGINT,
      muted_role_id BIGINT,
      honeypot_channel_ids BIGINT[] DEFAULT '{}',
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_guild_settings_guild_id ON guild_settings(guild_id);
  ```
- **Seed Backward-Compatibility Row:**
  Insert a default row for the primary guild (`MAIN_GUILD_ID = 1088553066334273537`) pre-populated with the legacy channel IDs (`LOGS_CHANNEL_ID`, `STAFF_CHANNEL_ID`, `PUBLIC_BOT_COMMANDS_CHANNEL_ID`, `LEADERBOARD_CHANNEL_ID`) with `ON CONFLICT (guild_id) DO NOTHING` so existing server operations do not regress.

#### 2. Guild Settings Service (`src/services/guild_settings_service.py`)
- Define a strongly typed `GuildSettings` dataclass containing all schema fields with helper property methods.
- Implement `GuildSettingsService` singleton:
  - Maintain an in-memory TTL/dict cache (`_cache: dict[int, GuildSettings]`) to eliminate repetitive database lookups on every event.
  - `async def get_settings(self, guild_id: int) -> GuildSettings`:
    - Checks cache; on miss, queries `guild_settings` from database.
    - If no row exists, inserts and returns a default `GuildSettings(guild_id=guild_id)`.
  - `async def update_settings(self, guild_id: int, **kwargs) -> GuildSettings`:
    - Executes parameterized SQL updating specified fields and sets `updated_at = NOW()`.
    - Updates the in-memory cache and returns the refreshed `GuildSettings`.
  - `def invalidate_cache(self, guild_id: int | None = None) -> None`:
    - Clears cache for a single guild or all guilds.
  - `async def resolve_channel(self, guild: nextcord.Guild, channel_type: str) -> nextcord.abc.GuildChannel | None`:
    - Helper to fetch the channel ID from settings and resolve it to a `nextcord.TextChannel` or `nextcord.VoiceChannel` object on the given guild.

#### 3. Interactive Server Setup Command (`src/cogs/admin/setup.py`)
- Implement a dedicated cog loaded in `EXTENSIONS` as `src.cogs.admin.setup`.
- Restrict to staff/admin via `@require_staff()`.
- Expose both slash group `/setup` and prefix group `!setup`:
  - **`/setup show` / `!setup show`:**
    - Displays a comprehensive `veka_embed` detailing all configured channels and roles for the current server (Log channel, Staff channel, Alert channel, Commands channel, Welcome channel, Radio voice channel, Leaderboard channel, Muted role).
  - **`/setup set <setting_type> <channel_or_role>`:**
    - Directly configures a single channel or role with slash parameter autocomplete/choices.
  - **`/setup interactive`:**
    - Sends an interactive Nextcord UI `View` using `nextcord.ui.ChannelSelect` and `nextcord.ui.RoleSelect` allowing server admins to configure channels through native Discord dropdown menus without typing IDs.
  - **`/setup reset <setting_type>`:**
    - Clears a specific channel/role configuration back to `None`.

#### 4. Decouple Hardcoded Constants Across Existing Modules
Update all existing cogs and services to resolve channels dynamically via `GuildSettingsService`, using `src/config/config.py` constants solely as fallback defaults when no guild-specific channel is configured:
- **`src/services/admin_notifier.py`:** Update `_get_channel()` to accept `guild_id: int | None` and resolve alerts and log channels from `GuildSettingsService`.
- **`src/cogs/admin/massunban.py`:** Update log output destination to use the current guild's configured `log_channel_id`.
- **`src/cogs/admin/honeypot.py`:** Direct honeypot trigger notifications to the guild's configured `log_channel_id`.
- **`src/cogs/admin/notifications.py`:** Resolve staff channels for daily reminders and inactivity alerts dynamically per guild.
- **`src/cogs/rpg/rpg_manager.py`:** Fetch `leaderboard_channel_id` from `guild_settings` rather than the hardcoded `1332399327100010569`.
- **`src/cogs/radio/radio.py`:** Allow the target voice channel to be resolved per-guild from `guild_settings.radio_channel_id` if `RADIO_VOICE_CHANNEL_ID` is unset.
- **`src/config/config.py`:** Add comments marking the legacy channel IDs as deprecated fallbacks.

#### 5. Verification & Quality Gates
- **Format & Lint:** `ruff check . --fix && ruff format .`
- **Type Checking:** `mypy src/ main.py --explicit-package-bases`
- **Pre-commit:** `pre-commit run --all-files`
- **Functional Validation:**
  - Verify `/setup show` displays correct seeded values for the primary server.
  - Invite or simulate an external server and verify `/setup` creates a new row in `guild_settings` without collisions.
  - Verify moderation logs and honeypot alerts route to the newly configured channels.

### Phase 3: Moderation & Safety Upgrades

> **Status:** Completed (2026-09-05)  
> **Target files:** `migrations/019_moderation_upgrades.sql` (new), `src/cogs/admin/moderation.py`, `src/cogs/admin/honeypot.py`, `src/cogs/admin/massunban.py`, `src/services/guild_settings_service.py`, `src/cogs/admin/setup.py`.  
> **Rule:** Do not edit bot code unless executing this specification. Follow all project conventions (dual prefix + slash commands, safe wrappers, ruff, mypy).

#### 1. Database Schema Additions (`migrations/019_moderation_upgrades.sql`)
- **Warnings Table:**
  ```sql
  CREATE TABLE IF NOT EXISTS warnings (
      id BIGSERIAL PRIMARY KEY,
      guild_id BIGINT NOT NULL,
      user_id BIGINT NOT NULL,
      moderator_id BIGINT NOT NULL,
      reason TEXT NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      active BOOLEAN DEFAULT TRUE
  );

  CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id, active);
  CREATE INDEX IF NOT EXISTS idx_warnings_moderator ON warnings(moderator_id, created_at);
  ```
- **Extend `guild_settings`:**
  ```sql
  ALTER TABLE guild_settings
  ADD COLUMN IF NOT EXISTS warn_mute_threshold INT DEFAULT 3,
  ADD COLUMN IF NOT EXISTS warn_ban_threshold INT DEFAULT 5,
  ADD COLUMN IF NOT EXISTS honeypot_cooldown_seconds INT DEFAULT 60;
  ```

#### 2. Warning & Auto-Escalation System (`src/cogs/admin/moderation.py`)
- Restrict all warning commands to staff (`@require_mod()` / `@require_staff()`).
- Expose dual command surface (slash + prefix):
  - **`/warn <user> <reason>` & `!warn <user> <reason>`:**
    - Inserts a new warning record into `warnings`.
    - Queries total active warnings for the user on this guild.
    - Sends a direct message to the warned user with server name, reason, and warning count (handle `nextcord.Forbidden` gracefully).
    - **Auto-escalation logic:**
      - Fetch `warn_mute_threshold` and `warn_ban_threshold` from `GuildSettingsService`.
      - If active count $\ge$ `warn_ban_threshold`: Automatically ban the user (`reason=f"Auto-ban: reached {active_count} warnings"`), log to guild log channel.
      - Else if active count $\ge$ `warn_mute_threshold`: Automatically apply timeout or assign `muted_role_id` from `guild_settings`, log to guild log channel.
    - Responds with `success_embed` or `alert_embed` highlighting the new warning count and any automated escalation triggered.
  - **`/warnings <user>` & `!warnings <user>`:**
    - Fetches active and past warnings for the target user.
    - If more than 5 warnings exist, display in a paginated embed using interactive buttons (`Previous` / `Next` via `nextcord.ui.View`).
    - Format entries with Warning ID, timestamp (`<t:ts:R>`), issuing moderator mention, reason, and active status badge.
  - **`/clearwarnings <user>` & `!clearwarnings <user>`:**
    - Sets `active = FALSE` for all warnings of the user on the current guild.
    - Returns `success_embed` indicating how many warnings were resolved.
  - **`/modstats` & `!modstats`:**
    - Aggregates moderation activity over the past 30 days from `audit_logs` and `warnings`.
    - Shows a leaderboard table of staff members detailing: Bans, Kicks, Mutes/Timeouts, and Warns issued.

#### 3. Honeypot System Enhancements (`src/cogs/admin/honeypot.py`)
- **Configurable Actions per Channel:**
  - Update `/honeypot add` choices to support: `softban`, `timeout`, `ban`, `role`, and `log` (log only without punitive action).
  - Store selected action directly in `honeypots.action`.
- **Honeypot Status Overview:**
  - Add `/honeypot status` and `!honeypot status` displaying a `veka_embed` listing all registered honeypot channels, current enabled status, action type, and total triggered count.
- **Configurable Cooldown:**
  - Replace the hardcoded 5-second deduplication with `guild_settings.honeypot_cooldown_seconds` (default 60s) to prevent spamming logs when bots flood multiple messages.
- **Rich Honeypot Audit Embed:**
  - Post detailed trigger logs to `guild_settings.log_channel_id`:
    - Embed fields: User (mention + tag + ID), Account age / creation date, Trigger channel, Message content preview, Action executed, and Timestamp.

#### 4. Mass Unban Preview & Disclosure (`src/cogs/admin/massunban.py`)
- **`/massunban preview` & `!massunban preview`:**
  - Takes the exact same filter arguments as `/massunban run` (`start_datetime`, `end_datetime`, `banned_by`).
  - Fetches guild bans, cross-references against `audit_logs`, and calculates matching bans without executing unbans.
  - Returns a `veka_embed` with:
    - Total bans in guild.
    - Total bans matching the criteria.
    - Estimated processing duration (based on sequential 1.5s rate-limit interval).
    - Prominent note explaining Discord API constraints:
      > *"Note: Discord's API does not store ban timestamps or banning moderators. Date and moderator filters only match bans logged in the bot's audit database while the bot was active."*
- **Audit Limitation Notice in Execution:**
  - Ensure the same disclosure note is prominently displayed on the `/massunban run` confirmation view before staff click confirmation.

#### 5. Verification & Quality Gates
- **Format & Lint:** `ruff check . --fix && ruff format .`
- **Type Checking:** `mypy src/ main.py --explicit-package-bases`
- **Pre-commit:** `pre-commit run --all-files`
- **Functional Validation:**
  - Verify `/warn` increments active warnings and triggers auto-mute upon hitting the threshold.
  - Verify `/massunban preview` calculates matching bans without executing changes.
  - Verify honeypot trigger events send complete embeds to the configured log channel.

### Phase 4: Activity, XP & Leaderboards Overhaul

> **Status:** Completed (2026-09-05)  
> **Target files:** `migrations/020_activity_and_leaderboard_schema.sql` (new), `pyproject.toml`, `src/cogs/rpg/rpg_manager.py`, `src/utils/card_generator.py` (new).  
> **Rule:** Do not edit bot code unless executing this specification. Follow all project conventions (dual prefix + slash commands, safe wrappers, ruff, mypy).

#### 1. Database Schema Additions (`migrations/020_activity_and_leaderboard_schema.sql`)
- **Daily Activity Rollup Table:**
  ```sql
  CREATE TABLE IF NOT EXISTS user_activity_daily (
      id BIGSERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      guild_id BIGINT NOT NULL,
      activity_date DATE NOT NULL DEFAULT CURRENT_DATE,
      xp_earned INT NOT NULL DEFAULT 0,
      messages INT NOT NULL DEFAULT 0,
      voice_minutes INT NOT NULL DEFAULT 0,
      gaming_minutes INT NOT NULL DEFAULT 0,
      streaming_minutes INT NOT NULL DEFAULT 0,
      coding_minutes INT NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE(user_id, guild_id, activity_date)
  );

  CREATE INDEX IF NOT EXISTS idx_activity_daily_lookup
  ON user_activity_daily(guild_id, user_id, activity_date);
  ```
- **Streaks Tracking in `users`:**
  ```sql
  ALTER TABLE users
  ADD COLUMN IF NOT EXISTS current_streak INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS longest_streak INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_streak_date DATE;
  ```
- **Leaderboard Snapshots Table:**
  ```sql
  CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
      id BIGSERIAL PRIMARY KEY,
      guild_id BIGINT NOT NULL,
      season_month VARCHAR(7) NOT NULL, -- Format: YYYY-MM
      category VARCHAR(32) NOT NULL,    -- 'xp', 'voice', 'chat', 'gaming', 'streaming', 'coding'
      user_id BIGINT NOT NULL,
      rank INT NOT NULL,
      score BIGINT NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_leaderboard_snapshots
  ON leaderboard_snapshots(guild_id, season_month, category);
  ```

#### 2. Streak Tracking & XP Multipliers (`src/cogs/rpg/rpg_manager.py`)
- **Consecutive Day Tracking:**
  - Track user activity (sending messages or voice sessions $\ge 1$ min).
  - Compare `last_streak_date` against `today = datetime.now(UTC).date()`:
    - If `last_streak_date == today`: Streak already accounted for today; no change.
    - If `last_streak_date == today - timedelta(days=1)`: Consecutive day! Increment `current_streak += 1`, update `longest_streak = max(longest_streak, current_streak)`, set `last_streak_date = today`.
    - If `last_streak_date < today - timedelta(days=1)`: Streak broken! Reset `current_streak = 1`, set `last_streak_date = today`.
- **Streak Bonus XP Multipliers:**
  - When awarding XP for any activity:
    - $\ge 30$-day streak: `2.0x` XP
    - $\ge 7$-day streak: `1.5x` XP
    - $\ge 3$-day streak: `1.25x` XP
    - Default: `1.0x`
- **Daily Rollup Upsert:**
  - In `_award_points` and activity listeners, perform an upsert into `user_activity_daily`:
    ```sql
    INSERT INTO user_activity_daily (user_id, guild_id, activity_date, xp_earned, {metric_col})
    VALUES ($1, $2, CURRENT_DATE, $3, $4)
    ON CONFLICT (user_id, guild_id, activity_date)
    DO UPDATE SET
        xp_earned = user_activity_daily.xp_earned + EXCLUDED.xp_earned,
        {metric_col} = user_activity_daily.{metric_col} + EXCLUDED.{metric_col},
        updated_at = NOW();
    ```

#### 3. Activity Summary with Unicode Mini Graphs (`src/cogs/rpg/rpg_manager.py`)
- Command: `/activity summary [user]` and `!activity summary [user]`.
- Fetch the last 7 days of rows from `user_activity_daily` for the target member.
- Render clean mini bar graphs using Unicode block elements (` `, `▂`, `▃`, `▄`, `▅`, `▆`, `▇`, `█`) without external image libraries:
  - Map each day's metric proportional to the week's maximum.
  - Display 7-day sparkline charts for:
    - 💬 Messages: `[ ▂▃▅█▃ ]` + 7-day total
    - 🔊 Voice: `[   ▃▅█  ]` + total hours/minutes
    - 💻 Coding: `[  ▅██▃  ]` + total hours/minutes
    - 🎮 Gaming & 📺 Streaming breakdowns.
  - Include streak badge: `🔥 Current Streak: X days (Best: Y days) | Bonus: Zx XP`.

#### 4. Visual Rank Card Generator (`src/utils/card_generator.py`)
- **Dependency:** Add `Pillow>=11.0.0` to `dependencies` in `pyproject.toml`.
- Create `src/utils/card_generator.py` containing an asynchronous image generator:
  - `async def generate_rank_card(username: str, avatar_bytes: bytes | None, level: int, current_xp: int, xp_needed: int, rank: int, streak: int) -> io.BytesIO`:
    - Generates a sleek dark mode card (e.g. 900x260 canvas, dark gradient `#121216` to `#1E1F28`).
    - Circular avatar with anti-aliasing mask and VEKA orange accent border (`#FF6B00`).
    - Render username, global rank badge (`#1`, `#5`), level, and current streak (`🔥 7d`).
    - Rounded gradient progress bar showing current XP vs XP needed for next level.
    - Export into a high-quality PNG `BytesIO` buffer.
  - Run the CPU-bound Pillow drawing code inside `await asyncio.to_thread(...)` to prevent blocking the async event loop.
- **Command Integration:**
  - Slash command `/rank card [user]` and prefix `!rank card [user]`.
  - Downloads avatar via `aiohttp`, calls `generate_rank_card()`, and sends the image via `safe_send(interaction, file=nextcord.File(fp=buffer, filename='rank_card.png'))`.

#### 5. Leaderboard Overhaul & Seasonal Archive (`src/cogs/rpg/rpg_manager.py`)
- **Category Leaderboards:**
  - Slash command `/leaderboard [category]` and `!leaderboard [category]` with choices:
    - `xp` (Total XP), `chat` (Messages), `voice` (Voice minutes), `gaming` (Gaming minutes), `streaming` (Streaming minutes), `coding` (Coding minutes).
- **Interactive Button Pagination:**
  - Replace static truncation with an interactive `PaginationView` (`nextcord.ui.View`):
    - `◀ Previous` button, `Page X/Y` indicator button (disabled), and `Next ▶` button.
    - 10 entries per page with medal badges (`🥇`, `🥈`, `🥉`) on page 1.
    - Auto-disable buttons after 120 seconds of inactivity.
- **Monthly Season Reset & Archives:**
  - Slash command `/leaderboard season`:
    - Shows current monthly standings and previous season podium winners.
  - Automated Monthly Cron Loop (`@tasks.loop` running at start of each calendar month):
    - Archives top 25 users for each category into `leaderboard_snapshots`.
    - Automatically sends a celebratory end-of-season announcement embed in `guild_settings.leaderboard_channel_id` highlighting the top 3 champions with trophy awards.

#### 6. Verification & Quality Gates
- **Format & Lint:** `ruff check . --fix && ruff format .`
- **Type Checking:** `mypy src/ main.py --explicit-package-bases`
- **Pre-commit:** `pre-commit run --all-files`
- **Functional Validation:**
  - Verify streak increments on consecutive days and resets if a day is skipped.
  - Verify `/activity summary` renders 7-day sparkline characters cleanly on desktop and mobile.
  - Verify `/rank card` returns a crisp PNG image with no loop lag.
  - Verify leaderboard pagination switches pages seamlessly without timeout errors.

### Phase 5: Community, Marketplace, Directory & Utilities

> **Status:** Completed (2026-09-05)  
> **Target files:** `migrations/021_community_and_utilities_schema.sql` (new), `src/cogs/marketplace/marketplace.py`, `src/cogs/marketplace_enhanced.py`, `src/services/directus_service.py`, `src/cogs/networking/networking.py`, `src/cogs/resources/feeds.py`, `src/services/rss_service.py`, `src/cogs/stats.py`, `src/cogs/mentorship.py`, `src/cogs/status.py`, `src/utils/card_generator.py`, `src/cogs/admin/welcome.py` (new).  
> **Rule:** Do not edit bot code unless executing this specification. Follow all project conventions (dual prefix + slash commands, safe wrappers, ruff, mypy).

#### 1. Database Schema Additions (`migrations/021_community_and_utilities_schema.sql`)
- **Marketplace Listing Enhancements:**
  ```sql
  ALTER TABLE marketplace_listings
  ADD COLUMN IF NOT EXISTS last_bumped_at TIMESTAMPTZ DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS is_expired BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';

  CREATE INDEX IF NOT EXISTS idx_marketplace_active_listings
  ON marketplace_listings(status, is_expired, last_bumped_at DESC);
  ```
- **Dynamic RSS Feeds & Deduplication Tables:**
  ```sql
  CREATE TABLE IF NOT EXISTS feed_subscriptions (
      id BIGSERIAL PRIMARY KEY,
      guild_id BIGINT NOT NULL,
      channel_id BIGINT NOT NULL,
      feed_url TEXT NOT NULL,
      feed_name VARCHAR(64) NOT NULL,
      poll_interval_minutes INT DEFAULT 30,
      last_polled_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE(guild_id, feed_url)
  );

  CREATE TABLE IF NOT EXISTS feed_seen_items (
      id BIGSERIAL PRIMARY KEY,
      feed_url TEXT NOT NULL,
      item_guid TEXT NOT NULL,
      seen_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE(feed_url, item_guid)
  );

  CREATE INDEX IF NOT EXISTS idx_feed_seen_lookup ON feed_seen_items(feed_url, item_guid);
  ```
- **Server Stats Daily Tracking:**
  ```sql
  CREATE TABLE IF NOT EXISTS server_stats_daily (
      id BIGSERIAL PRIMARY KEY,
      guild_id BIGINT NOT NULL,
      stat_date DATE NOT NULL DEFAULT CURRENT_DATE,
      total_members INT NOT NULL,
      joins INT DEFAULT 0,
      leaves INT DEFAULT 0,
      max_online INT DEFAULT 0,
      boost_level INT DEFAULT 0,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE(guild_id, stat_date)
  );
  ```
- **Profile Enhancements & Mentorship Matches:**
  ```sql
  ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS skills TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS timezone VARCHAR(64);

  CREATE TABLE IF NOT EXISTS mentorship_matches (
      id BIGSERIAL PRIMARY KEY,
      guild_id BIGINT NOT NULL,
      mentor_id BIGINT NOT NULL,
      mentee_id BIGINT NOT NULL,
      category VARCHAR(64) NOT NULL,
      status VARCHAR(32) DEFAULT 'active',
      started_at TIMESTAMPTZ DEFAULT NOW(),
      ended_at TIMESTAMPTZ,
      outcome TEXT,
      last_checkin_at TIMESTAMPTZ DEFAULT NOW()
  );

  ALTER TABLE guild_settings
  ADD COLUMN IF NOT EXISTS welcome_message_template TEXT DEFAULT 'Welcome {user} to {server}!',
  ADD COLUMN IF NOT EXISTS welcome_card_enabled BOOLEAN DEFAULT TRUE;
  ```

#### 2. Marketplace Overhaul (`src/cogs/marketplace/` & `src/cogs/marketplace_enhanced.py`)
- **Listing Bumps:**
  - Slash command `/market bump <listing_id>` and prefix `!market bump <listing_id>`.
  - Enforce a strict 24-hour cooldown based on `last_bumped_at`.
  - Sets `last_bumped_at = NOW()`, moving the listing to the top of feed queries.
- **Search with Autocomplete:**
  - Slash command `/market search <query>` with dynamic autocomplete suggestions matching active listing titles and tags.
  - Automatically filter out expired listings (`WHERE is_expired = FALSE AND status = 'active'`).
- **Automated Listing Expiration:**
  - Daily background loop (`@tasks.loop(hours=24)`):
    - Flags listings older than 30 days as `is_expired = TRUE`.
    - DMs sellers informing them their listing has expired with advice on how to re-list or renew.
    - If `DIRECTUS_SYNC_ENABLED`: updates the Directus CMS record to status `expired`.
- **Marketplace Analytics:**
  - Slash command `/market stats`:
    - Displays total active listings, most active category, average listing price, and total transactions in a styled embed.

#### 3. Welcome System & Visual Cards (`src/utils/card_generator.py` & event listeners)
- **On Member Join:**
  - When a user joins a guild, check `guild_settings.welcome_channel_id`.
  - Render `welcome_message_template` with `{user}`, `{server}`, `{member_count}`.
  - If `welcome_card_enabled`:
    - Generate a visual welcome card using Pillow in `card_generator.py`:
      - Server icon background, user avatar, welcome greeting, and member join count badge (`Member #X,XXX`).
    - Send the welcome card and embed directly to the configured welcome channel.
- **Preview Command:**
  - Staff command `/welcome test` and `!welcome test` to generate and send a preview card for the calling user.

#### 4. Dynamic RSS Feeds (`src/cogs/resources/feeds.py` & `src/services/rss_service.py`)
- Replace hardcoded RSS lists with database-backed feeds from `feed_subscriptions`.
- **Feed Management Commands:**
  - `/feed add <url> <channel> [name] [interval_minutes]`: validates RSS endpoint via `feedparser`, records subscription in DB.
  - `/feed remove <feed_name_or_url>`: deletes feed subscription.
  - `/feed list`: lists all registered guild RSS feeds with configured posting channels and polling intervals.
  - `/feed test <feed_url>`: fetches the single latest entry and renders an embed preview.
- **Robust Deduplication:**
  - Use `feed_seen_items` to record `(feed_url, item_guid)` so bot reboots never re-announce previously posted entries.

#### 5. Server Analytics & Demographic Reports (`src/cogs/stats.py`)
- **Daily Stats Collector:**
  - Background task at UTC midnight snapshots current server metrics into `server_stats_daily`.
  - Listeners for `on_member_join` and `on_member_remove` increment daily join/leave counters.
- **`/stats server` Command:**
  - Displays: Total member count, 7-day join count, 7-day leave count, current online count, server boost level, most active channel (from `user_activity_daily`), and most active member.
  - Generates a 7-day member growth trend visualized using Unicode sparkline bars (` ▂▃▅▆▇█`).
- **`/stats demographics` Command:**
  - Visualizes member distribution based on activity tiers (Active vs Inactive vs New members based on XP and recent messages).

#### 6. Profile System & Member Directory (`src/cogs/networking/networking.py`)
- **Profile Customization Commands:**
  - `/profile set bio <text>`
  - `/profile set links [github] [linkedin] [website] [twitter]`
  - `/profile set skills <comma_separated_skills>`
  - `/profile set timezone <timezone_string>`
- **Full Profile Card:**
  - `/profile [user]` displays avatar, bio, clickable social icons/links, verified skills tags, local time calculated from timezone, XP level, and streak badge.
- **Member Directory Search:**
  - `/directory search [skill] [timezone]`:
    - Queries community profiles by matching skills (e.g. `Python`, `React`, `DevOps`) or timezone offset to connect collaborators.

#### 7. Mentorship Matching Engine (`src/cogs/mentorship.py`)
- **Mentor Registration & Matching:**
  - `/mentor apply <skills> <bio>`: registers user as an available mentor in their categories.
  - `/mentee request <category> <desired_skills>`: scans available mentors with overlapping skills, creates a pairing in `mentorship_matches`, and sends intro DMs to both parties.
- **Automated Check-in DMs:**
  - Weekly task checks active matches where `last_checkin_at < NOW() - INTERVAL '7 days'`.
  - Dispatches automated check-in DMs asking how the mentorship is progressing.
- **`/mentor end <match_id> <outcome>`:**
  - Closes an active mentorship session, records the outcome, and awards bonus XP to both mentor and mentee.

#### 8. Dynamic Status Rotator Expansions (`src/cogs/status.py`)
- Expand status definition templates to support live server metrics:
  - `{online}`: count of online/active members.
  - `{boosts}`: server Nitro boost count.
  - `{active_radio_station}`: active station name and emoji if radio is currently streaming.
  - `{open_listings}`: count of active marketplace listings.
  - `{season}`: current competitive RPG season month.

#### 9. Verification & Quality Gates
- **Format & Lint:** `ruff check . --fix && ruff format .`
- **Type Checking:** `mypy src/ main.py --explicit-package-bases`
- **Pre-commit:** `pre-commit run --all-files`
- **Functional Validation:**
  - Verify `/market bump` respects the 24h cooldown.
  - Verify `/feed add` polls entries and logs duplicates in `feed_seen_items`.
  - Verify `/welcome test` generates and posts the Pillow welcome image card.
  - Verify `/directory search` successfully filters profiles by skill tag.

### Phase 6: Automated Testing & QA Suite

> **Status:** Pending implementation (Execute after Phase 5)  
> **Target files:** `pyproject.toml`, `tests/conftest.py` (new), `tests/test_embeds.py` (new), `tests/test_safety.py` (new), `tests/test_runtime_state.py` (new), `tests/test_guild_settings.py` (new), `tests/test_migrations.py` (new), `tests/test_cog_loading.py` (new).  
> **Rule:** Do not edit bot code unless executing this specification. Follow all project conventions (dual prefix + slash commands, safe wrappers, ruff, mypy).

#### 1. Test Dependencies & Configuration (`pyproject.toml`)
- Add testing dependencies to `[project.optional-dependencies] dev`:
  ```toml
  dev = [
      "ruff>=0.11.0",
      "mypy>=1.15.0",
      "pre-commit>=4.2.0",
      "pytest>=8.0.0",
      "pytest-asyncio>=0.23.0",
      "pytest-mock>=3.12.0",
  ]
  ```
- Configure pytest in `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  testpaths = ["tests"]
  python_files = ["test_*.py"]
  filterwarnings = [
      "ignore::DeprecationWarning",
  ]
  ```

#### 2. Shared Test Fixtures (`tests/conftest.py`)
- Create `tests/conftest.py` providing reusable async fixtures:
  - `mock_db`: Async mock simulating `Database` pool methods (`fetch`, `fetch_one`, `execute`, `execute_many`).
  - `mock_bot`: Headless `commands.Bot` instance initialized with `get_intents()` and `runtime_state`.
  - `mock_interaction`: Mocked `nextcord.Interaction` with fake user, guild, response, and followup objects.
  - `mock_context`: Mocked `commands.Context` with mocked `send()` and `reply()` helpers.

#### 3. Core Unit Tests
- **`tests/test_embeds.py`:**
  - Test all embed helpers: `veka_embed`, `success_embed`, `error_embed`, `info_embed`, `alert_embed`.
  - Assert correct brand color codes: VEKA Orange (`0xFF6B00`), Success Green (`0x2ECC71`), Error Red (`0xE74C3C`).
  - Assert author header format: `"VEKA Bot"` linked to `"https://veka.gg"`.
  - Assert footer attribution: validates static map resolution with fallback to `"Contributor: shifu"`.
- **`tests/test_safety.py`:**
  - `@safe_command(requires_db=True)` & `@safe_slash_command(requires_db=True)`:
    - When `runtime_state.db_available = False`: verify the command aborts execution and sends a degraded-mode error embed without raising an unhandled exception.
    - When `runtime_state.db_available = True`: verify the command callback executes normally.
  - `@safe_background_task`:
    - Verify that 3 consecutive task exceptions trigger the admin notifier alert hook.
  - Rate limiting:
    - Verify token consumption per user and assert that requests exceeding the limit receive a rate-limit notice.
- **`tests/test_runtime_state.py`:**
  - Verify tracking of loaded cogs, failed cogs, and degraded features.
  - Verify `last_db_error` is populated on failure and cleared on recovery.
- **`tests/test_guild_settings.py`:**
  - Test cache hit: calling `get_settings(guild_id)` twice queries DB only once.
  - Test fallback: returns default values when guild settings row is absent.
  - Test invalidation: `update_settings(guild_id)` refreshes the in-memory cache.

#### 4. Database Migration Tests (`tests/test_migrations.py`)
- Scan all `.sql` files in `migrations/`:
  - Assert all filenames strictly follow three-digit formatting: `^[0-9]{3}_[a-z0-9_]+\.sql$`.
  - Assert no duplicate numeric prefixes exist.
  - Assert migrations are strictly sequential starting from `001` with zero gaps.
  - Parse SQL files to detect syntax errors before running in production.

#### 5. Cog Loading Integration Tests (`tests/test_cog_loading.py`)
- Iterate over the `EXTENSIONS` list from `src/core/app.py`:
  - Test dynamic extension loading (`bot.load_extension(ext)`).
  - Verify all 20+ cogs load without import errors, syntax errors, or circular dependencies.
  - Unload each extension cleanly (`bot.unload_extension(ext)`).

#### 6. Verification & Quality Gates
- Run test suite: `pytest tests/ -v`
- Assert all unit and integration tests pass cleanly in under 5 seconds with zero network or external database dependencies.
- Verify pre-commit hook runs tests alongside `ruff` and `mypy`.

