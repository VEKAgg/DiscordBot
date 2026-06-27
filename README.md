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

---

## Tech Stack

- **Python** `>=3.13` (nextcord 3.x supports 3.12–3.14)
- **nextcord 3.2.0** — Discord API wrapper
- **asyncpg 0.31.0** — async PostgreSQL driver (the only datastore; no MongoDB, no Redis)
- **aiohttp / feedparser / beautifulsoup4** — RSS resource feeds
- **python-dotenv / validators** — config and input validation

Dependencies are pinned in `requirements.txt` (the canonical install used by
Docker and CI). `pyproject.toml` mirrors the same pins for `uv`/`pip install .`.

---

## Features

Loaded modules (see `EXTENSIONS` in `src/core/app.py`):

- 🤝 **Networking** — professional profiles, connection requests, and connections (`/profile`, `/connect`, plus `!` prefix equivalents)
- 🛒 **Marketplace** — listings and reviews
- 📚 **Resource Feeds** — curated RSS (tech news, jobs, dev blogs) refreshed every 15 minutes
- 🛠️ **Admin / Health** — administrative commands, help, and health/diagnostics

Additional cogs exist in `src/cogs/` (quiz, mentorship, fun, gamification,
portfolio, workshops, enhanced marketplace) but are **not loaded** until added to
`EXTENSIONS`. Gamification is an intentional disabled stub.

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
│   ├── admin/              → basic.py, help.py, health.py
│   ├── networking/         → networking.py (profiles, connections)
│   ├── marketplace/        → marketplace.py, reviews.py
│   └── resources/feeds.py  → RSS (@tasks.loop every 15 min)
├── services/               → networking, mentorship, quiz, rss
└── utils/
    ├── safety.py           → safe_command / safe_send / safe_background_task
    ├── embeds.py           → VEKA embed builders
    ├── security/           → rbac.py, rate_limiter.py, audit.py, validation.py
    └── marketplace/        → fraud_detection.py
migrations/                 → SQL files, auto-applied on startup
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
and the security tables (`audit_logs`, `user_security`, `security_events`).

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

**RBAC** — hierarchy `USER < VERIFIED < MODERATOR < ADMIN < OWNER`, mapped from
Discord role names (`everyone`, `verified`, `mod`/`moderator`,
`admin`/`administrator`, and guild owner). Gate commands with `@require_mod()`,
`@require_admin()`, `@require_verified()`, or check `rbac.get_user_role(ctx)`.

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
| `ADMIN_ALERT_CHANNEL_ID` | — | none | Channel for operational alerts |
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
pip install -r requirements.txt
cp .env.example .env          # then fill in DISCORD_TOKEN and DATABASE_URL
python main.py                # needs a reachable PostgreSQL
```

### Docker

`docker-compose.dev.yml` is a fully self-contained local stack (bot + a bundled
PostgreSQL). `docker-compose.yml` (production) runs **only the bot** and expects
an external/managed PostgreSQL reachable via `DATABASE_URL`.

```bash
# Local: bot + bundled postgres
docker-compose -f docker-compose.dev.yml up -d --build

# Production: bot only (set DATABASE_URL to your managed DB)
docker-compose up -d --build

docker logs veka-discord-bot
```

Podman is also supported — build the image and run the bot in a pod, providing
`DATABASE_URL` via the mounted `.env` (see `.github/workflows/deploy-discord-bot.yml`).

---

## Commands

Both slash commands and `!`-prefix commands are provided, often side by side for
the same feature — keep them in sync when changing behavior.

| Command | Description |
|---|---|
| `/profile [@user]` / `!profile` | View a professional profile |
| `!setupprofile` | Set up your profile |
| `/connect @user` / `!connect @user [message]` | Send a connection request |
| `/help` / `!help [command]` | List commands / command detail |

---

## Development

- **No tests, linters, or formatters are configured** (no pytest/black/flake8).
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
merged PRs). It runs on a self-hosted runner (`self-hosted, X64, Linux, Veka`),
supports Docker or Podman via the `CONTAINER_ENGINE` secret (default `docker`),
injects `DISCORD_TOKEN`/`DATABASE_URL` from secrets, and gates success on the log
line `"is ready. DB available"` appearing within 60s.

> Production uses an external/managed database — ensure the `DATABASE_URL` secret
> points at a reachable host (not `@postgres:5432`).

---

## License

MIT — see the LICENSE file.
