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
- **Extensions loaded from explicit allowlist** (`EXTENSIONS` in `src/core/app.py` — 19 entries):
  `src.cogs.admin.basic`, `src.cogs.admin.help`, `src.cogs.admin.health`, `src.cogs.admin.moderation`, `src.cogs.admin.notifications`, `src.cogs.admin.honeypot`, `src.cogs.networking.networking`, `src.cogs.marketplace.marketplace`, `src.cogs.marketplace.reviews`, `src.cogs.resources.feeds`, `src.cogs.mentorship`, `src.cogs.marketplace_enhanced`, `src.cogs.portfolio.portfolio_manager`, `src.cogs.radio.radio`, `src.cogs.rpg.rpg_manager`, `src.cogs.stats`, `src.cogs.external.info`, `src.cogs.external.export`, `src.cogs.status`.
  Add a cog's dotted module path to `EXTENSIONS` to enable it. Unloaded stubs: `gamification/` (intentionally disabled), `quiz.py`, `workshops/`.
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

1. **`rss_service.py` queries a column that does not exist in the correct schema** (`src/services/rss_service.py:99`). The service calls `SELECT 1 FROM rss_cache WHERE feed_url = $1 AND entry_id = $2` and later inserts with both columns. However, migration `005_community_additions.sql` creates an incompatible `rss_cache` with only `feed_url` as primary key and no `entry_id` column. Migration `005_guild_and_rss_schema.sql` drops and recreates it with the correct schema including `entry_id` — but **only if `005_community_additions.sql` runs first**. If the migration runner applies them alphabetically, `005_community_additions` and `005_guild_and_rss_schema` share the same `005_` prefix and their ordering is filesystem-dependent. The `DROP TABLE IF EXISTS rss_cache` in the second file is the fix, but it depends on run order. Fix: rename `005_guild_and_rss_schema.sql` to `006a_...` or higher to guarantee ordering, then reconcile the numbering with existing higher migrations.

2. **`bot.loop.create_task()` is deprecated in Python 3.10+ and removed in future asyncio** (`src/cogs/admin/massunban.py:198,221,943`). `bot.loop` returns the event loop but using `.create_task()` on it directly is deprecated in favour of `asyncio.create_task()`. Should be `asyncio.create_task(...)` throughout. Current code will emit `DeprecationWarning` in Python 3.13 runtime.

3. **`on_disconnect` closes the database pool on every gateway disconnect** (`src/core/app.py:190-195`). Discord bots experience frequent transient reconnections (voice region switches, gateway resumption). Closing the pool on every disconnect means the DB pool is destroyed and must be fully re-established, causing `DatabaseUnavailableError` during the reconnect window. The `db_health_check` loop handles pool recovery, but there is a gap window between disconnect and recovery. Fix: remove the `db.close()` from `on_disconnect` and rely solely on the health-check loop to detect and recover broken connections.

### HIGH

4. **Widespread use of `datetime.utcnow()` (deprecated since Python 3.12)** — found in 11+ files: `src/utils/embeds.py:98`, `src/services/admin_notifier.py:36`, `src/cogs/radio/radio.py:140,234`, `src/cogs/marketplace/marketplace.py:97,159`, `src/cogs/marketplace/reviews.py:340,341`, `src/cogs/portfolio/portfolio_manager.py:51,272`, `src/utils/security/audit.py:70`, `src/cogs/marketplace_enhanced.py:243`. Python 3.12 deprecated `datetime.utcnow()` and it will be removed in a future version. All usages should be replaced with `datetime.now(UTC)` (importing `UTC` from `datetime`). The `admin_notifier.py` case is especially important because it controls deduplication logic in `_should_alert`.

5. **`MASSUNBAN_LOG_CHANNEL_ID` is not documented in `.env.example`**. `src/config/config.py` reads it, `massunban.py` imports it, and `README.md` lists it — but `.env.example` has no entry for it. Operators deploying fresh will not know to set it, and mass unban logs will silently fall back to `LOGS_CHANNEL_ID` (or nowhere if that is also unset).

6. **`rss_cache` migration creates naive `TIMESTAMP` columns without timezone** (`migrations/005_guild_and_rss_schema.sql:36`, plus `001`, `003`, `004`, `008`, `010`, `013`). Most older migrations use `TIMESTAMP DEFAULT NOW()` (no timezone) while newer ones (`014`, `015`, `016`) correctly use `TIMESTAMPTZ`. The bot's Python code mixes `datetime.utcnow()` (naive) and `datetime.now(UTC)` (aware). Comparing aware datetimes fetched from TIMESTAMPTZ columns against naive timestamps from TIMESTAMP columns will raise `TypeError` in asyncpg comparisons. Fix: add a migration to `ALTER TABLE ... ALTER COLUMN ... TYPE TIMESTAMPTZ USING ... AT TIME ZONE 'UTC'` for the affected columns.

### MEDIUM

7. **Radio `_started_at` uses `datetime.utcnow()` (naive) then computes `_get_uptime()` with `datetime.utcnow()` subtraction** (`radio.py:140,234`). This is safe as long as both calls use naive UTC, but mixing with any aware datetime in the future will break silently. Additionally, `_started_at` is not reset to `None` after disconnection (`_disconnect()` does not clear it), so `/uptime` will show stale uptime after a radio disconnect/reconnect.

8. **`feeds.py` sends subsequent feed embeds to `interaction.channel` instead of using followup** (`src/cogs/resources/feeds.py:124`). For the first entry, it uses `interaction.followup.send()`, but subsequent entries use `interaction.channel.send()`. If the channel is None (DMs, certain thread types) this will raise `AttributeError`. It also bypasses ephemeral state — the first embed may be ephemeral but subsequent ones are always public.

9. **`safe_background_task` decorator only fires the alert on exactly 3 consecutive failures** (`src/utils/safety.py:261`). The alert fires when `count == 3`, not `count >= 3`, meaning if failures continue beyond 3 they will be logged but no additional alerts are sent. Once a cooldown expires (30 min), a repeat alert won't fire either because the counter is cumulative (not reset between cooldown windows). Fix: change `count == 3` to `count >= 3`.

10. **Honeypot in-memory cache (`_honeypot_cache`) is never invalidated on bot reconnect** (`src/cogs/admin/honeypot.py:32-45`). The cache is loaded once via `_load_cache()` with `_cache_loaded` as a guard flag. If the DB is temporarily unavailable during initial load, `_cache_loaded` remains `False` and will retry — good. However, after a successful load, if a honeypot is added/modified by a different cog reload or external DB change, the cache goes stale indefinitely (only `_invalidate_cache()` on explicit cog commands clears it). This is acceptable for normal usage but should be noted.

### LOW

11. **`_update_job_progress` in `massunban.py` uses an f-string SQL query with a whitelisted column** (`massunban.py:878-886`). Although there is a `_VALID_COUNTER_COLS` whitelist check immediately before the f-string, the `counter_col` value originates from a dict literal keyed by `result['status']` (not user input), making SQL injection practically impossible. However, it violates the project's own convention of "parameterized queries only". Fix: use separate `execute` calls for each counter column.

12. **`runtime_state.startup_time` is set at module import time**, not at `on_ready`. If the bot takes a long time to connect, `/uptime` and status embeds will show inflated uptime. Consider setting `startup_time` inside `on_ready` for accuracy.

13. **`migrate rss_cache` has two `005_` numbered migrations with different schemas**. If a new developer or CI runs migrations on a clean DB, the sort order between `005_community_additions.sql` and `005_guild_and_rss_schema.sql` is not guaranteed and could create an inconsistent schema state. The `DROP TABLE IF EXISTS` guard in the latter file helps, but the situation is fragile. Document this prominently or renumber the files.

### CRITICAL (Second Pass — 2026-07-21)

14. **Audit log time-based filtering is completely broken** (`src/utils/security/audit.py:113,128`). Both `get_recent` and `get_user_actions` build SQL like `INTERVAL '$2 hours'` where the `$2` is **inside a SQL string literal** — asyncpg will not substitute it. PostgreSQL receives the literal string `$2 hours` and either errors or returns wrong results. Fix: use `INTERVAL '1 hour' * $N` pattern or build the interval string in Python.

15. **Rate limiter decorator never actually consumes a token** (`src/utils/security/rate_limiter.py:162-192`). The `rate_limit` decorator calls `is_rate_limited()` (read-only check) instead of `check()` (consume + check). This means the rate limiter as applied to commands never enforces limits — a user can exceed the limit on every request as long as no other code path calls `check()`. Fix: replace `is_rate_limited()` with `check()` in the decorator.

16. **`on_command_error` calls `ctx.send()` without `safe_send()`** (`src/core/app.py:198-234`). If the channel is a DM or the user has DMs disabled, `ctx.send()` raises `nextcord.Forbidden`, which would crash the error handler itself — a secondary unhandled exception in the error path. Fix: wrap with `safe_send()`.

17. **`assert DISCORD_TOKEN is not None` is stripped in `-O` mode** (`src/core/app.py:314`). If Python runs with optimizations (`python -O main.py`), the assert is removed and `bot.run(None)` is called, producing a confusing error. Fix: use an explicit `if` check with `raise SystemExit`.

18. **`get_user`/`create_user` has a race condition** (`src/database/database.py:214-231`). `get_user` does `SELECT` then `INSERT` if not found. Between the two queries, a concurrent request for the same `discord_id` can insert first, causing a `UniqueViolationError` that is misreported as `DatabaseUnavailableError`. The `create_user` function already has `ON CONFLICT DO UPDATE` — fix `get_user` to use it directly instead of the SELECT-then-INSERT pattern.

19. **Tool config targets wrong Python version** (`pyproject.toml`). `requires-python = ">=3.13"` but `[tool.ruff] target-version = "py312"` and `[tool.mypy] python_version = "3.12"`. Ruff won't flag 3.13-specific issues, and mypy checks against 3.12 semantics. Fix: set both to `py313` / `"3.13"`.

20. **`asyncio.create_task()` without storing the reference in `rss_service.py`** (`src/services/rss_service.py:65-71,84-92`). Fire-and-forget tasks can be garbage-collected before they complete. The Python docs warn: "Save a reference to the result of this function, to avoid a task disappearing mid-execution." Fix: store task references in a set and remove on completion.

### HIGH (Second Pass — 2026-07-21)

21. **Rate limiter `buckets` dict grows unboundedly** (`src/utils/security/rate_limiter.py`). There is no eviction/TTL mechanism. Every unique `user_id:command` combination creates an entry that is never removed. Over weeks, this is a memory leak. Fix: add periodic cleanup or LRU eviction with a TTL.

22. **`AdminNotifier._get_channel` caches the channel reference forever** (`src/services/admin_notifier.py:16-30`). Once `self._channel` is set (including to `None` on failure), it is never refreshed. If the channel ID changes or the initial fetch fails, the notifier is permanently broken until restart. Fix: add TTL or re-fetch on failure.

23. **`feeds.py` sends subsequent embeds to `interaction.channel` instead of `followup`** (`src/cogs/resources/feeds.py:124`). The first entry uses `interaction.followup.send()`, but subsequent entries use `interaction.channel.send()`. If channel is None (DMs, threads), this raises `AttributeError`. Also bypasses ephemeral state. Fix: use `interaction.followup.send()` consistently.

24. **`mentorship_service.get_user_stats` always reports 0 active mentorships** (`src/services/mentorship_service.py:175-186`). `get_completed_mentorships` filters by `status = 'completed'`, so the returned list never contains active entries. The loop counting `status == 'active'` will always yield 0. Fix: query for active mentorships separately or remove the filter.

25. **`runtime_state._load_git_metadata()` runs `subprocess.check_output` at module import time** (`src/core/runtime_state.py:9-14,20-30`). Every import of `runtime_state` spawns a `git` subprocess. If git is absent, the exception is caught but the spawn adds latency to every cold start. Fix: make lazy/cached with `@functools.lru_cache`.

26. **`sanitize_text` uses `html.escape()` which is wrong for Discord** (`src/utils/security/validation.py:47`). Discord uses Markdown, not HTML. HTML-escaping produces visible `&amp;`, `&lt;`, `&gt;` in chat. Fix: use Discord-specific escaping (backslash-escape special chars) or simply strip dangerous content.

27. **RBAC `require_role` and `require_permission` decorators don't work with slash commands** (`src/utils/security/rbac.py:197`). They extract `ctx` from `args[1]` and call `ctx.send()`. For slash commands, `args[1]` is an `Interaction` which has a different API (`interaction.response.send_message`). Fix: detect the context type and use the appropriate API, or split into separate decorators.

28. **`setup_logging()` ignores the `LOG_LEVEL` env var** (`src/utils/logger.py:35`). The function defaults to `'INFO'` and is called from `app.py` with no arguments. The `LOG_LEVEL` config variable is never read. Fix: read `LOG_LEVEL` from config and pass it.

### MEDIUM (Second Pass — 2026-07-21)

29. **Directus `_rehost_image` downloads entire images into memory** (`src/services/directus_sync.py:52`). No size limit on the download. Large images could cause memory pressure. Fix: add a `Content-Length` check or stream to a temp file.

30. **`guild_gate.py` uses `asyncio.ensure_future()` inside a synchronous check predicate** (`src/utils/guild_gate.py`). The `commands.check` predicate is synchronous but fires coroutines via `ensure_future`. These responses may fail silently. Fix: use `commands.check()` with an async predicate (nextcord supports this).

31. **No log rotation** (`src/utils/logger.py`). `bot.log` grows unboundedly via a plain `FileHandler`. Fix: use `RotatingFileHandler` or `TimedRotatingFileHandler`.

32. **`.env.example` has `POSTGRES_USER=veka_user` but `docker-compose.dev.yml` uses `POSTGRES_USER=veka_bot_user`**. Deploying with the example file will create a user mismatch. Fix: align the two files.

33. **`MASSUNBAN_LOG_CHANNEL_ID` missing from `.env.example`** (already in existing issue #5, also affects `.env.example` consistency).

34. **`alert_state_cache` mixes heterogeneous data without type safety** (`src/core/runtime_state.py`). At least 5 subsystems write to it with different key patterns (healthy_count, failure counts, dedup timestamps, RSS counters). A wrong key could interfere. Fix: use dedicated typed fields or separate caches per subsystem.

35. **`.github/workflows/deploy-discord-bot.yml` is documented in AGENTS.md but does not exist in the repository**. Either it was removed, renamed, or the documentation is stale.

### LOW (Second Pass — 2026-07-21)

36. **Massive duplicated error-handling logic in `app.py`** (`src/core/app.py:198-286`). `on_command_error` and `on_application_command_error` are near-identical `isinstance` chains. Fix: extract into a shared helper.

37. **`bot.runtime_state` and `bot.notifier` are monkey-patched with `# type: ignore`** (`src/core/app.py`). Bypasses type checking. Fix: use a typed `Bot` subclass with properly typed attributes.

38. **`error_embed` uses orange color instead of red** (`src/utils/embeds.py:111-115`). It calls `veka_embed` which defaults to `ORANGE`. Fix: default to `nextcord.Color.red()`.

39. **`admin_only()`/`staff_only()` in `safety.py` bypass the RBAC system** (`src/utils/safety.py`). Two parallel auth systems (ID-list checks vs. RBAC role hierarchy) can return different results. Fix: consolidate to use RBAC exclusively.

40. **`runtime_state.last_db_error` is never cleared** (`src/core/runtime_state.py`). Once set, stale error text persists for the process lifetime. Fix: clear on successful recovery.

41. **`rate_limit` decorator only handles prefix commands** (`src/utils/security/rate_limiter.py:162-192`). Extracts `ctx` from `args[1]` which assumes cog method signature `(self, ctx, ...)`. Does not handle slash commands at all. Fix: add a slash command variant or detect context type.

42. **`rss_service.py` `datetime.strptime` with fixed format fails on many RSS date formats** (`src/services/rss_service.py:142`). The format `'%a, %d %b %Y %H:%M:%S %z'` only matches RFC 2822. ISO 8601 and other formats silently fail, leaving entries unsorted. Fix: use `email.utils.parsedate_to_datetime` or `dateutil.parser`.

43. **Missing `src/utils/marketplace/__init__.py`**. The `fraud_detection.py` module may not be importable as a package depending on how Python resolves it. Fix: add the `__init__.py`.

44. **Duplicated unique constraint on `profiles.user_id`** across migrations `005_community_additions` (`profiles_user_id_unique`) and `006_profiles_and_requests` (`unique_profile_user_id`). Two constraints on the same column. Harmless but wasteful.

45. **`_is_staff_user` in `safety.py` creates a `SimpleNamespace` to fake a context** (`src/utils/safety.py:103-106`). Fragile coupling — if `rbac.get_user_role` changes its context expectations, this breaks silently.

