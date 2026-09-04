# VEKA Discord Bot

A professional networking and community-development Discord bot built with
[nextcord](https://github.com/nextcord/nextcord) and backed by PostgreSQL. It
provides profile/networking tools, a marketplace, curated RSS resource feeds,
and operational tooling designed to keep running in a degraded state when its
database or any single feature is unavailable.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Features](#features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Database](#database)
- [Security](#security)
- [Configuration](#configuration)
- [Setup](#setup)
- [Commands](#commands)
- [Development](#development)
- [CI/CD](#cicd)
- [Known Issues](#known-issues)
- [License](#license)

---

## Tech Stack

- **Python** `>=3.13` (nextcord 3.x supports 3.12–3.14)
- **nextcord 3.2.0** — Discord API wrapper
- **asyncpg 0.31.0** — async PostgreSQL driver (the only datastore; no MongoDB, no Redis)
- **aiohttp / feedparser / beautifulsoup4** — RSS resource feeds
- **python-dotenv / validators** — config and input validation

Package management is done via **`uv`** — `uv.lock` is the lockfile.
`pyproject.toml` is the source of truth for dependencies. A `requirements.txt`
is kept for Docker images that don't have `uv`.

---

## Features

Loaded modules (see `EXTENSIONS` in `src/core/app.py`):

- 🤝 **Networking** — professional profiles, connection requests, connections, and profile search (`/profile`, `/connect`, `/networking search`)
- 🛒 **Marketplace** — listings, reviews, offers, transactions, fraud detection, and enhanced marketplace features (`/marketplace`, `/reviews`)
- 📚 **Resource Feeds** — curated RSS (tech news, jobs, dev blogs) refreshed every 15 minutes (`/feeds`)
- 🎮 **RPG / Leveling** — XP from messages, voice time, and commands; level-up system; activity role evaluation; background tasks for leaderboard auto-update, inactivity monitoring, and activity role assessment (`/rpg`)
- 📊 **Leaderboard & Stats** — auto-updating leaderboard embed (`/setupleaderboard`), `/leaderboard [stat]`, `/level [@user]`, `/most streamed|played|listened|coded` activity leaderboards, server statistics
- 🔍 **Activity Tracking** — streaming, gaming, listening, and coding activity duration tracking with detailed activity logging (game names, songs, coding apps)
- 🛠️ **Admin / Health** — administrative commands, help, health/diagnostics, moderation (warns, kicks, bans), notifications, and honeypot anti-spam
- 🚫 **Honeypot Anti-Spam** — trap channels that catch spam bots with configurable actions (softban, ban, timeout, role assignment) (`/honeypot`)
- 🔥 **Mass Unban** — resumable bulk-unban jobs with double confirmation, per-user tracking, adaptive rate limiting, and DM apology on failure (`/massunban`)
- 📋 **Mentorship** — mentorship matching, categories, accept/complete/cancel workflow (`/mentorship`)
- 💼 **Portfolio** — portfolio management, project display, and search (`/portfolio`)
- 📻 **Radio** — voice channel radio/audio streaming with stability monitoring, auto-recovery, and stream refresh (`/radio`)
- 🔗 **External** — info, export commands (`/info`, `/export`)
- 📡 **Status** — bot status, system information, and runtime health (`/status`)
- 🖼️ **Directus CMS Sync** — automatic profile sync from Directus CMS with image rehosting (enabled via `DIRECTUS_URL` + `DIRECTUS_SERVICE_TOKEN`)

Additional cogs exist in `src/cogs/` (quiz, gamification, workshops) but are **not loaded** until added to `EXTENSIONS`. Gamification is an intentional disabled stub.

---

## Architecture

The entrypoint chain is `main.py` → `src/core/app.py:run_bot()`, which loads
`.env`, configures logging, builds the bot, registers events, and starts it.

**Degraded-mode design is the central theme** — the bot is built to keep running
when the database, a cog, or a background task fails, rather than crashing:

- **`src/core/runtime_state.py`** — a single global `runtime_state` dataclass
  (attached as `bot.runtime_state`) tracking `db_available`, `loaded_cogs`,
  `failed_cogs`, `degraded_features`, startup-check results, and an alert cache.
  This is the source of truth for health/observability.
- **DB failures don't abort boot** — `initialize_database()` catches errors, sets
  `db_available = False`, and marks `database` degraded.
- A 1-minute `db_health_check` loop pings the DB, flips `db_available`, and fires
  admin alerts on lost/recovered transitions.
- Cog load failures are isolated per-extension and recorded in `failed_cogs`;
  other cogs still load.

**Layering:** `cogs/` (thin Discord command handlers) → `services/` (business
logic) → `database/` (data access). Keep logic in services.

**Safety wrappers (`src/utils/safety.py`)** carry the degraded-mode contract into
command code:

- `@safe_command(requires_db=True)` / `@safe_slash_command(requires_db=True)` —
  short-circuit with `DatabaseUnavailableError` when the DB is down, catch
  unexpected exceptions, log with context, and reply with an error embed.
- `safe_send(target, ...)` — unified reply helper for both `commands.Context` and
  `nextcord.Interaction`. Prefer it over raw `ctx.send` / `interaction.response`.
- `@safe_background_task(name=...)` — wrap `@tasks.loop` bodies; tracks
  consecutive failures and alerts admins after 3, with recovery notices.
- Domain exceptions (`DatabaseUnavailableError`, `ValidationError`,
  `ExternalRequestError`) map to user-facing messages centrally in `app.py`'s
  error handlers.

**Embeds (`src/utils/embeds.py`)** — all user-facing output uses `veka_embed`,
`success_embed`, `error_embed`, `info_embed`, `alert_embed`. Pass
`contributor_source=__name__` from a cog so attribution resolves.

---

## Project Structure

```
main.py                     → entrypoint (delegates to src.core.app:run_bot)
src/
├── core/
│   ├── app.py              → bot bootstrap, EXTENSIONS allowlist, event handlers
│   ├── runtime_state.py    → global runtime_state (health/observability)
│   └── checks.py           → StartupChecks run on on_ready
├── config/config.py        → all env vars, constants, RSS feeds, rate limits
├── database/
│   ├── database.py         → asyncpg pool, global `db` singleton, run_migrations()
│   └── migrations.py       → migration file discovery (schema_migrations table)
├── cogs/
│   ├── admin/
│   │   ├── basic.py        → ping, hello, commands, server info
│   │   ├── help.py         → custom help command
│   │   ├── health.py       → health/diagnostics commands
│   │   ├── moderation.py   → warn, kick, ban, audit log commands
│   │   ├── notifications.py→ notification management
│   │   ├── honeypot.py     → anti-spam honeypot trap channels
│   │   └── massunban.py    → resumable bulk-unban system
│   ├── networking/         → networking.py (profiles, connections, search)
│   ├── marketplace/        → marketplace.py, reviews.py
│   ├── marketplace_enhanced.py → enhanced marketplace features
│   ├── resources/feeds.py  → RSS feeds (@tasks.loop every 15 min)
│   ├── mentorship.py       → mentorship matching and management
│   ├── portfolio/          → portfolio_manager.py (portfolio CRUD, projects, search)
│   ├── radio/radio.py      → voice channel radio/audio streaming
│   ├── rpg/rpg_manager.py  → RPG/leveling/activity tracking
│   ├── stats.py            → server statistics
│   ├── status.py           → bot status and runtime info
│   └── external/
│       ├── info.py         → info/help commands
│       └── export.py       → data export
├── services/               → business logic (networking, mentorship, quiz, rss, inactivity, admin_notifier, directus_sync)
└── utils/
    ├── safety.py           → safe_command / safe_send / safe_background_task
    ├── embeds.py           → VEKA embed builders
    ├── logger.py           → logging setup (RotatingFileHandler)
    ├── http.py             → shared aiohttp client
    ├── footer.py           → embed footer helpers
    ├── guild_gate.py       → guild membership gate checks
    ├── security/           → rbac.py, rate_limiter.py, audit.py, validation.py
    └── marketplace/        → fraud_detection.py
migrations/                 → SQL files (001–016), auto-applied on startup
```

---

## Database

- **PostgreSQL via asyncpg.** Access goes through the global singleton:
  `from src.database.database import db`. Use the `$1`, `$2` (asyncpg) parameter
  style.
- All `db` methods (`fetch`, `fetch_one`/`fetchrow`, `fetchval`, `execute`,
  `execute_many`) raise `DatabaseUnavailableError` on failure and flip
  `runtime_state.db_available = False`. Never assume a query succeeded.
- **Migrations** are plain `.sql` files in `migrations/`, applied automatically on
  connect by `db.run_migrations()` and tracked in the `schema_migrations` table.
  Add a new one as `migrations/00N_name.sql`; it runs on next startup.

Key tables: `users`, `profiles`, `connections`, `connection_requests`,
`mentorships`, `quizzes`, `quiz_attempts`, `workshops`, `portfolios`,
`resources`, `rss_cache`, `guild_config`, `marketplace_listings`,
`marketplace_offers`, `marketplace_reviews`, `marketplace_transactions`,
`massunban_jobs`, `massunban_job_items`, `honeypots`, `honeypot_logging_config`,
`honeypot_events`, `warnings`, `user_activity_log`, `user_rpg_roles`,
`user_activity_details`, `user_active_activities`, `user_security`,
`security_events`, `audit_logs`, and `directus_profiles`.

---

## Security

Security utilities live in `src/utils/security/` and are exported from the
package:

```python
from src.utils.security import (
    rate_limit, rate_limiter,            # rate limiting
    InputValidator, sanitize, is_safe, validate_id,   # input validation
    audit_log, audit_action,             # audit logging
    rbac, Role, require_mod, require_admin, require_verified,  # RBAC
)
```

**Rate limiting** — `@rate_limit('marketplace')` on a command; named buckets
(`default`, `quiz`, `marketplace`, `mentorship`, `admin`). Manual check via
`await rate_limiter.is_rate_limited(user_id, 'quiz')`.

**Input validation** — `sanitize(text, max_length=...)`, `is_safe(text)`,
`InputValidator.validate_discord_id/validate_url/validate_marketplace_item(...)`.

**Audit logging** — `@audit_action('quiz_completed')` decorator, or
`await audit_log.record(user_id=..., action=..., details={...}, severity=...)`.
Persisted to `audit_logs`; `user_security` and `security_events` track
warnings/blocks. Suspicious-activity detection:
`await audit_log.detect_suspicious_activity(user_id)`.

**RBAC** — hierarchy `USER < VERIFIED < INTERN < DONATOR < ACTIVE_PRO < STAFF < ADMIN < FOUNDER`,
mapped from Discord role names. Gate commands with `@require_mod()` (aliased to
`require_staff()`), `@require_admin()`, `@require_verified()`, or check
`rbac.get_user_role(ctx)`.

> Note: `safety.py` also exposes a simpler `admin_only()` check keyed off
> `ADMIN_IDS`/`OWNER_IDS` from config — two parallel auth mechanisms exist.

**Checklist for new commands:** apply rate limiting where resource-intensive,
validate and length-limit all user input, add an RBAC gate if restricted, and
audit-log security-relevant actions.

---

## Configuration

Create a `.env` in the project root (see `.env.example`). Variables actually read
by `src/config/config.py`:

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Bot token |
| `DATABASE_URL` | ✅* | composed from `POSTGRES_*` | Full PostgreSQL DSN |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | ✅* | `localhost`/`5432`/`veka_bot`/`veka_bot_user`/`example` | Used to compose `DATABASE_URL` if it isn't set |
| `ADMIN_IDS` | — | empty | Comma-separated Discord user IDs |
| `OWNER_IDS` | — | empty | Comma-separated Discord user IDs |
| `FOUNDER_IDS` | — | empty | Comma-separated Discord user IDs (highest RBAC tier) |
| `STAFF_IDS` | — | empty | Comma-separated Discord user IDs |
| `INTERN_IDS` | — | empty | Comma-separated Discord user IDs |
| `DONATOR_IDS` | — | empty | Comma-separated Discord user IDs |
| `ACTIVE_PRO_IDS` | — | empty | Comma-separated Discord user IDs |
| `ADMIN_ALERT_CHANNEL_ID` | — | none | Channel for operational alerts |
| `MASSUNBAN_LOG_CHANNEL_ID` | — | none | Dedicated channel for per-user mass-unban audit logs |
| `LEADERBOARD_CHANNEL_ID` | — | none | Channel for auto-updating leaderboard embed |
| `RADIO_STREAM_URL` | — | Lofi Girl live | Stream URL for the radio feature |
| `RADIO_VOICE_CHANNEL_ID` | — | none | Voice channel for radio playback |
| `MAIN_GUILD_ID` | — | `1088553066334273537` | Primary guild ID (hardcoded) |
| `MAIN_SERVER_INVITE_URL` | — | `https://discord.gg/veka` | Server invite URL |
| `DIRECTUS_URL` | — | empty | Directus CMS instance URL (enables profile sync) |
| `DIRECTUS_SERVICE_TOKEN` | — | empty | Directus API service token |
| `BOT_VERSION` | — | `1.0.0` | |
| `LOG_LEVEL` | — | `INFO` | |
| `ENVIRONMENT` | — | `development` | |

\* Provide either `DATABASE_URL` directly, or the individual `POSTGRES_*` vars.
The command prefix is hardcoded to `!` in `config.py` and is **not** read from
the environment.

---

## Setup

### Local

```bash
git clone <repo> && cd discord-bot
cp .env.example .env          # then fill in DISCORD_TOKEN and DATABASE_URL

# Install all deps (runtime + dev) via uv
uv sync --extra dev

# Activate pre-commit hooks (once after clone)
pre-commit install

python main.py                # needs a reachable PostgreSQL
```

### Docker

`docker-compose.dev.yml` is a fully self-contained local stack (bot + a bundled
PostgreSQL). `docker-compose.yml` (production) runs **only the bot** and expects
an external/managed PostgreSQL reachable via `DATABASE_URL`.

```bash
# Local: bot + bundled postgres
docker compose -f docker-compose.dev.yml up -d --build

# Production: bot only (set DATABASE_URL to your managed DB)
docker compose up -d --build

docker logs veka-discord-bot
```

The bot does not require Docker — `python main.py` runs it directly against any
reachable PostgreSQL. Docker is simply how it is packaged and deployed.

---

## Commands

Both slash commands and `!`-prefix commands are provided, often side by side for
the same feature — keep them in sync when changing behavior.

### General

| Command | Description |
|---|---|
| `/ping` / `!ping` | Check bot latency |
| `/hello` / `!hello` | Greeting / info |
| `/commands` / `!commands` | List available commands |
| `/help [command]` / `!help [command]` | List commands or show command detail |
| `/status` | Bot status and system information |

### Networking & Profiles

| Command | Description |
|---|---|
| `/profile [@user]` / `!profile` | View a professional profile |
| `!setupprofile` | Set up your profile |
| `/connect @user` / `!connect @user [message]` | Send a connection request |
| `/networking search` | Search for users by skills/interests |

### Marketplace

| Command | Description |
|---|---|
| `/marketplace` / `!marketplace` | Browse, create, and manage marketplace listings |
| `/reviews` / `!reviews` | View and leave reviews |
| `/marketplace_enhanced` | Enhanced marketplace features |

### RPG & Leveling

| Command | Description |
|---|---|
| `/leaderboard [stat]` / `!leaderboard` | View leaderboard (xp, messages, voice, streaming, gaming, listening, coded) |
| `/level [@user]` / `!level` | View your or another user's level and XP |
| `/most streamed\|played\|listened\|coded` | Activity-specific leaderboards |
| `/setupleaderboard` | (Admin) Configure the auto-updating leaderboard channel |
| `/rpg` | RPG/leveling commands |

### Resource Feeds

| Command | Description |
|---|---|
| `/feeds list` / `!feeds list` | List configured RSS feeds |
| `/feeds check` / `!feeds check` | Force-check all feeds now |
| `/feeds add <url>` / `!feeds add <url>` | Add a new RSS feed |
| `/feeds remove <id>` / `!feeds remove <id>` | Remove an RSS feed |

### Mentorship

| Command | Description |
|---|---|
| `/mentorship request` | Request a mentor |
| `/mentorship accept` | Accept a mentorship request |
| `/mentorship complete` | Mark a mentorship as completed |
| `/mentorship cancel` | Cancel an active mentorship |
| `/mentorship status` | View your mentorship status |
| `/mentorship categories` | Browse mentorship categories |

### Portfolio

| Command | Description |
|---|---|
| `/portfolio view [@user]` | View a user's portfolio |
| `/portfolio add` | Add a project to your portfolio |
| `/portfolio remove <id>` | Remove a project from your portfolio |
| `/portfolio edit <id>` | Edit a portfolio project |
| `/portfolio project <id>` | View a specific project |
| `/portfolio search` | Search portfolios |

### Radio

| Command | Description |
|---|---|
| `/radio join` / `!radio join` | Join your voice channel and start playing |
| `/radio leave` / `!radio leave` | Leave voice channel and stop |
| `/radio start` / `!radio start` | Start radio playback |
| `/radio stop` / `!radio stop` | Stop radio playback |
| `/radio np` / `!radio np` | Show now playing |
| `/radio skip` / `!radio skip` | Skip current track |
| `/radio uptime` / `!radio uptime` | Show radio uptime |
| `/radio seturl <url>` / `!radio seturl <url>` | Change the stream URL |

### Admin

| Command | Description |
|---|---|
| `/admin featurestatus` | View status of all features |
| `/admin startupchecks` | View startup check results |
| `/admin reloadcog <name>` | Reload a cog |
| `/admin unloadcog <name>` | Unload a cog |
| `/admin loadcog <name>` | Load a cog |
| `/admin dbstatus` | Check database status |
| `/admin serverinfo` | View server information |
| `/admin guildgate` | Configure guild gate settings |
| `/admin testmail` | Test email delivery |
| `/admin testnotifications` | Test notification system |
| `/admin testradio` | Test radio connection |
| `/admin testdm` | Test DM delivery |
| `!honk` | Fun admin command |

### Moderation

| Command | Description |
|---|---|
| `/mod warn @user <reason>` | Issue a warning |
| `/mod warnings @user` | View a user's warnings |
| `/mod warnings-user @user` | View warnings for a user |
| `/mod warningsclear @user` | Clear all warnings for a user |
| `/mod setlogchannel` | Set the moderation log channel |

### Honeypot Anti-Spam

| Command | Description |
|---|---|
| `/honeypot setchannel #channel` | Register a channel as a honeypot trap |
| `/honeypot config` | Configure honeypot settings |
| `/honeypot stats` | View honeypot statistics |
| `/honeypot test` | Test honeypot detection |

### Mass Unban

| Command | Description |
|---|---|
| `/massunban execute` | Start a bulk unban job with filters |
| `/massunban status <job_id>` | Check status of a mass-unban job |
| `/massunban jobs` | List recent mass-unban jobs |
| `/massunban cancel <job_id>` | Cancel a pending or running job |
| `/massunban pause <job_id>` | Pause a running job |
| `/massunban resume <job_id>` | Resume a paused job |
| `/massunban simulate` | Simulate a mass-unban without executing |
| `/massunban dmtest` | Test DM delivery to a user |
| `/massunban config` | Configure mass-unban settings |
| `/massunban setlogchannel` | Set the mass-unban log channel |

### External

| Command | Description |
|---|---|
| `/info` | Bot information |
| `/export` | Export your data |

---

## Development

### Lint, Format, Typecheck

Run these before every push:

```bash
ruff check .                  # lint (no auto-fixes)
ruff check --fix . && ruff format .  # auto-fix then format
mypy src/ main.py --explicit-package-bases  # static type check
pre-commit run --all-files    # all checks (ruff + mypy + misc)
```

Pre-commit hooks run automatically on `git commit`. Config in
`.pre-commit-config.yaml`. Install them once with `pre-commit install`.

All tool config lives in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`).

### Guidelines

- Every module logs via `logging.getLogger('VEKA.<area>')`, configured by
  `setup_logging()` in `src/utils/logger.py`.
- To enable an unloaded cog, add its module path to `EXTENSIONS` in
  `src/core/app.py`. Each cog module needs a top-level `setup(bot)`.
- Startup health checks (`src/core/checks.py`) run from `on_ready`; results are
  stored in `runtime_state.startup_check_results`. Admin alerts and startup
  summaries go through `src/services/admin_notifier.py` (`bot.notifier`).
- `CLAUDE.md` contains condensed architecture guidance for AI coding agents.

---

## CI/CD

`.github/workflows/deploy-discord-bot.yml` deploys on push to `main`/`production`,
but **only when the commit message starts with `Merge pull request`** (i.e.
merged PRs). It runs on a self-hosted runner (`self-hosted, X64, Linux, Veka`)
using Docker (`docker compose up -d --build`), writes a `.env` from GitHub
secrets/variables, and gates success on the log line `"is ready. DB available"`
appearing within 60s.

Configure these in the repository's GitHub settings:

- **Secrets** (sensitive): `DISCORD_TOKEN`, `DATABASE_URL`
- **Variables** (non-sensitive): `ADMIN_IDS`, `OWNER_IDS`, `ADMIN_ALERT_CHANNEL_ID`, `LOG_LEVEL` (optional)

`BOT_VERSION` is set automatically to the commit SHA and `ENVIRONMENT` to
`production`.

> Production uses an external/managed database — ensure the `DATABASE_URL` secret
> points at a reachable host (not `@postgres:5432`).

---

## Known Issues

1. **HIGH — Leaderboard auto-update requires setup.** `LEADERBOARD_CHANNEL_ID` defaults to `None`. Must set the env var or run `/setupleaderboard` (admin-only).
2. **MEDIUM — Radio `_started_at` not reset on disconnect.** `/uptime` shows stale time after radio disconnect/reconnect.
3. **LOW — Honeypot cache not invalidated on reconnect.** In-memory cache goes stale if DB is modified externally. Acceptable for normal usage.
4. **LOW — Duplicate `profiles.user_id` unique constraint** across migrations `005` and `006`. Harmless but wasteful.
5. **NOTE — `/massunban` `banned_by` filter** only works for bans logged by the bot after its moderation audit system was in place. Historical bans placed before the bot was running cannot be filtered by moderator — Discord's audit log API is ephemeral and not stored retroactively.
6. **NOTE — Old migrations create naive `TIMESTAMP` columns** (no timezone). Newer migrations and code use `TIMESTAMPTZ`. A future migration should convert affected columns to avoid potential comparison issues.

---

## License

MIT — see the LICENSE file.
