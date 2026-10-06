# VEKA Discord Bot

A professional networking and community bot built with
[nextcord](https://github.com/nextcord/nextcord) and backed by PostgreSQL. It
provides profiles and connections, a member directory, a marketplace, portfolios,
mentorship, RSS feeds, XP/activity leaderboards, a 24/7 radio, and moderation
tooling. It is designed to keep running in a degraded state when its database or
any single feature is unavailable.

Contributor and agent guidance (conventions, architecture details, known issues)
lives in [`AGENTS.md`](AGENTS.md). Audit status per finding: [`AUDIT_REPORT.md`](AUDIT_REPORT.md);
deployment notes: [`MIGRATION_NOTES.md`](MIGRATION_NOTES.md).

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Features](#features)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Setup](#setup)
- [Commands](#commands)
- [Development](#development)
- [CI/CD](#cicd)
- [Known Issues](#known-issues)

---

## Tech Stack

- **Python** `>=3.13`, **nextcord 3.x**
- **PostgreSQL** via **asyncpg** — the only datastore (no Redis, no MongoDB)
- **aiohttp / feedparser** — RSS feeds; **Pillow** — rank and welcome cards; **FFmpeg** — radio audio
- **uv** for dependencies — `pyproject.toml` + `uv.lock` are the source of truth;
  `requirements.txt` is generated from the lockfile

---

## Features

Loaded modules are listed in `EXTENSIONS` in `src/core/app.py` (22 cogs).

- 🤝 **Networking** — professional profiles, connection requests with a searchable member picker, and a member directory (`/profile`, `/connect`, `/directory`)
- 🛒 **Marketplace** — listings, browsing/search, bumps, watchlist, offers, seller reputation and reviews, featured listings and stats (`/marketplace`, `/featured`, `/marketstats`, `/bump`); listings can be mirrored to a Directus CMS when `DIRECTUS_URL`/`DIRECTUS_SERVICE_TOKEN` are set
- 💼 **Portfolio** — add, list, view, delete and search projects (`/portfolio`)
- 🎓 **Mentorship** — register/apply as a mentor, request, accept, complete or end mentorships, weekly check-ins (`/mentor`)
- 📚 **Feeds & resources** — per-guild RSS subscriptions with dedupe, plus a resource browser (`/feed`, `/resource`)
- 🎮 **XP & activity** — XP from messages and voice with streak multipliers, levels, Pillow rank cards, category leaderboards with periods and monthly seasons, auto-updating leaderboard message, activity tracking (streaming, gaming, listening, coding) (`/level`, `/rank`, `/leaderboard`, `/activity`, `/most`)
- 📊 **Server stats** — server overview, growth trend and activity tiers (`/stats`, `/serverstats`)
- 📻 **Radio** — 24/7 streaming of fixed Icecast/SHOUTcast stations via FFmpeg, with stability monitoring and auto-recovery (`/radio`)
- ⚙️ **Per-guild setup** — channels and roles configured per server (`/setup`)
- 👋 **Welcome cards** — generated on member join (`/welcome test`)
- 🛡️ **Moderation** — warnings with auto-escalation to mute/ban, role-hierarchy checks, moderation stats (`/warn`, `/warnings`, `/clearwarnings`, `/modstats`)
- 🚫 **Honeypot** — trap channels that softban/ban/timeout/role-assign posters, with logging config (`/honeypot`, `/logging`)
- 🔓 **Mass unban** — resumable, rate-limit-aware bulk unbans with preview and double confirmation (`/massunban`)
- 🩺 **Health & admin** — health, uptime, feature status, startup checks, cog reload, broadcast, lockdown (`/health`, `/uptime`, `/botinfo`, `/admin`)
- 📤 **Chat export** — export channel history to `.txt` (`/exportchat`)

**Not implemented** (planned, pending approval — see `AUDIT_REPORT.md`): marketplace
transactions / "sold" flow, accepting or rejecting offers, watchlist price alerts,
quizzes, workshops. `src/services/quiz_service.py` has no cog. XP, leaderboards,
profiles and the marketplace are currently **global across guilds**.

---

## Architecture

`main.py` → `src/core/app.py:run_bot()` loads `.env`, configures logging, builds
the bot, registers events and loads extensions. Layers: `src/cogs/` (thin Discord
handlers) → `src/services/` (business logic) → `src/database/` (data access).

**Degraded mode is the central design theme:**

- `src/core/runtime_state.py` holds the global health state (`db_available`,
  `loaded_cogs`, `failed_cogs`, `degraded_features`, …).
- A database failure at boot doesn't abort startup; the `database` feature is
  marked degraded.
- A 30-second `db_health_check` loop pings the DB, flips `db_available`, alerts
  admins on lost/recovered transitions and, once the DB is back, applies deferred
  migrations and retries any cog `cog_ready()` startup hook that failed.
- Extension load failures are isolated per cog.
- Commands use `@safe_command` / `@safe_slash_command(requires_db=True)` and
  `safe_send` from `src/utils/safety.py`.

**Database:** migrations are plain `.sql` files in `migrations/` (001–026),
applied in filename order on connect and tracked in `schema_migrations`. Query
errors are logged with the SQLSTATE, schema object names and a primary message
(except for data exceptions and PL/pgSQL errors) — never parameter values or
PostgreSQL `DETAIL` text.

---

## Configuration

Copy `.env.example` to `.env`. Variables read by `src/config/config.py`:

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Bot token |
| `DATABASE_URL` | ✅* | composed from `POSTGRES_*` | Full PostgreSQL DSN |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | ✅* | `localhost`/`5432`/`veka_bot`/`veka_bot_user`/`example` | Used if `DATABASE_URL` is unset |
| `ADMIN_IDS`, `OWNER_IDS`, `FOUNDER_IDS`, `STAFF_IDS`, `INTERN_IDS`, `DONATOR_IDS`, `ACTIVE_PRO_IDS` | — | empty | Comma-separated Discord user IDs |
| `ADMIN_ALERT_CHANNEL_ID` | — | none | Channel for operational alerts |
| `MASSUNBAN_LOG_CHANNEL_ID` | — | none | Per-user mass-unban log channel |
| `MARKETPLACE_CHANNEL_ID` | — | none | Fallback channel for new-listing posts |
| `LEADERBOARD_CHANNEL_ID` | — | hardcoded main-server channel | Fallback; prefer `/setupleaderboard` or `/setup` |
| `RADIO_VOICE_CHANNEL_ID` | — | none | Fallback radio voice channel; prefer `/setup` |
| `LIVE_ROLE_ID` | — | none | Role given to members while streaming |
| `MAIN_GUILD_ID` | — | `1088553066334273537` | The main VEKA server |
| `MAIN_SERVER_INVITE_URL` | — | `https://discord.gg/veka` | |
| `DIRECTUS_URL`, `DIRECTUS_SERVICE_TOKEN` | — | empty | Enable the marketplace → Directus mirror |
| `LOG_LEVEL` | — | `INFO` | |
| `ENVIRONMENT` | — | `development` | |
| `BOT_VERSION`, `COMMIT_SHA`, `GIT_BRANCH` | — | — | Set by the deploy workflow |

\* Provide either `DATABASE_URL` or the `POSTGRES_*` variables. The command
prefix is hardcoded to `!`. `RADIO_STREAM_URL` is still read but unused — radio
stations are fixed in `src/cogs/radio/radio.py`.

Channel and role IDs in `.env` are fallbacks only; configure each server with
`/setup interactive` (or `/setup set`).

---

## Setup

### Local

```bash
cp .env.example .env          # fill in DISCORD_TOKEN and DATABASE_URL
uv sync --extra dev           # runtime + dev deps
pre-commit install            # once after clone
python main.py                # needs a reachable PostgreSQL (and FFmpeg for radio)
```

### Docker

```bash
docker compose -f docker-compose.dev.yml up -d --build   # bot + bundled PostgreSQL
docker compose up -d --build                             # production: bot only, external DB via DATABASE_URL
docker logs veka-discord-bot
```

---

## Commands

Most features have both a slash command and a `!` prefix command. Permission
notes: *Staff* = staff role or `STAFF_IDS`; *Admin* = Administrator/`ADMIN_IDS`;
*owner outside main* = in other servers only the bot owner may use it; *main server only* = unavailable elsewhere.

### General

| Command | Description |
|---|---|
| `/ping`, `!ping` | Bot latency |
| `/hello`, `!hello` | Greeting |
| `/help [command]`, `!help [command]` | Help on commands and categories |
| `/commands` | List available commands |
| `/health`, `!health` | Bot health status |
| `/uptime` | Uptime and service status |
| `/botinfo` | Bot information and runtime data |
| `/memberinfo [member]`, `/serverinfo` | Member and server details |

### Networking

| Command | Description |
|---|---|
| `/profile setup` / `edit` / `set` | Create or edit your profile |
| `/profile view [member]`, `!profile [member]` | View a profile |
| `!setupprofile` | Set up your profile (prefix flow) |
| `/connect request [message]` | Pick a member from a searchable menu and send a request |
| `!connect [@member] [message]` | Send a request directly, or open the picker if no member is given |
| `/connect list`, `!connections` | Pending requests and connections |
| `/directory search [skill] [timezone]` | Search the member directory |

### Marketplace

| Command | Description |
|---|---|
| `/marketplace post` / `browse` / `view` / `search` | Create, browse, view and search listings |
| `/marketplace mylistings` / `withdraw` / `bump` | Manage your listings (`/bump` also works) |
| `/marketplace watch` / `unwatch` / `watchlist` | Watchlist |
| `/marketplace offer` / `myoffers` | Make offers and view them |
| `/marketplace review` / `seller` / `reviews` / `helpful` | Reviews and seller reputation |
| `/marketplace stats`, `/marketstats`, `/featured` | Marketplace analytics and featured listings |
| `!marketplace_push`, `!marketplace_sync` | (Admin) Directus backfill / sync |

### Portfolio & Mentorship

| Command | Description |
|---|---|
| `/portfolio add` / `list` / `view` / `delete` / `search` (also `!portfolio …`) | Manage and browse projects |
| `/mentor register` / `apply` / `list` / `request` / `accept` / `complete` / `end` / `stats` | Mentorship (most also as `!mentor …`) |

### XP, Activity & Stats

| Command | Description |
|---|---|
| `/level [user]`, `/rank [user]` | Level, XP and rank card |
| `/leaderboard show [category] [period]`, `/leaderboard season` | Leaderboards and seasons |
| `/activity stats [user]`, `/activity summary [user]` | Activity details and 7-day summary |
| `/most streamed` / `played` / `listened` / `coded` | Activity leaderboards |
| `/stats server`, `/stats demographics`, `/serverstats` | Server analytics |
| `/setupleaderboard <channel>` | (Admin, main server only) Auto-updating leaderboard channel |

### Feeds & Resources

| Command | Description |
|---|---|
| `/feed add <url> <channel> [name] [interval_minutes]` | (Manage Server) Subscribe a channel to an RSS feed |
| `/feed remove <feed_url>` / `test <feed_url>` | (Manage Server) Remove or preview a feed |
| `/feed edit <feed_url> [channel] [name] [interval_minutes]` | (Manage Server) Change settings without losing delivery history |
| `/feed pause <feed_url>` / `resume <feed_url>` | (Manage Server) Stop or restart automatic posting |
| `/feed list [page]` | Paginated subscriptions, health, and next retry |
| `/resource sources`, `/resource latest` | View subscriptions or preview a URL |

Feeds are optional, dynamically added **per server**, and stored in PostgreSQL. No code change or restart is needed to manage them. The `feed_url` option of edit/pause/resume/remove autocompletes from the server's subscriptions. Only members with **Manage Server** (or Administrator/server ownership) can manage subscriptions; a staff role alone does not grant access. Use a public RSS/Atom URL, not an ordinary web page. The destination must be a text channel in the same server where the bot has View Channel, Send Messages, and Embed Links.

The scheduler checks due subscriptions every minute; configured intervals are **10–1440 minutes**. Defaults in `.env` (also available as GitHub deployment variables):
- `FEED_MAX_SUBSCRIPTIONS=25`: maximum subscriptions per server, including paused feeds. Existing subscriptions above the limit are preserved; updating them is allowed.
- `FEED_MAX_POSTS_PER_POLL=3`: maximum entries posted per feed per poll (1–10).
- `FEED_MAX_POSTS_PER_GUILD_PER_CYCLE=15`: maximum total automatic posts per server per one-minute cycle. Remaining due feeds wait for the next cycle.

After three failed polls, one warning is sent. Retries back off up to daily, and a successful fetch sends one recovery notice. State survives restarts. Pausing/resuming and editing retain outage backoff and article delivery history; a resume does not force an immediate retry. New subscriptions can post up to the posting limit from the latest available entries. `/feed add` updates an existing URL's settings but preserves its pause state. Lists show fetch health separately from unavailable-channel status; healthy means the latest fetch succeeded, not a guarantee of delivery.

Migration 028 removes only known historical default seeds that still have no destination channel. Configured subscriptions are not deleted, including obsolete URLs: staff can pause, replace, or remove those. Article previews do not produce outage alerts. Feed quotas are serialized in the single bot process; running multiple polling instances against the same database is not supported.

### Radio

| Command | Description |
|---|---|
| `/radio status`, `/radio list`, `!radiolist` | Status and station list |
| `/radio station <name>`, `!radiostation <name>` | (Admin, owner outside main) Switch station |
| `/radio start` / `stop` / `move <channel>` | (Admin, owner outside main) Control the stream |

### Server setup & Welcome

| Command | Description |
|---|---|
| `/setup show` / `set` / `reset` / `interactive` (also `!setup …`) | (Staff) Per-server channels and roles |
| `/welcome test` | Preview your welcome card |

### Moderation & Safety

| Command | Description |
|---|---|
| `/warn <user> <reason>`, `!warn` | (Staff) Warn a member; escalates automatically |
| `/warnings <user>`, `!warnings` | (Staff) View warnings |
| `/clearwarnings <user>`, `!clearwarnings` | (Staff) Clear warnings |
| `/modstats`, `!modstats` | (Staff) Moderation activity, last 30 days |
| `/honeypot status` / `create` / `list` / `view` / `edit` / `enable` / `disable` / `delete` / `test` (also `!honeypot …`) | (Admin) Honeypot traps |
| `/logging setchannel` / `setrole` / `clearrole` / `view` (also `!logging …`) | (Admin) Honeypot alert logging |
| `/massunban preview` / `run` / `status` / `cancel` / `recent` (also `!massunban …`) | (Admin) Bulk unbans; `include_unaudited` is slash-only |

### Admin

| Command | Description |
|---|---|
| `/admin featurestatus`, `/admin startupchecks`, `/admin detailedstatus` | (Staff) Runtime status |
| `/admin reloadcog <cog_name>` | (Bot operators) Reload a cog |
| `/admin pingsquad`, `!pingsquad` | (Staff) Ping the notification squad |
| `/admin broadcast`, `!broadcast` | (Founder) Announce to a channel |
| `/admin lockdown` / `panic`, `!lockdown` / `!panic` | (Founder) Toggle server lockdown |
| `/exportchat [channel] [limit]`, `/exportstop` | (Admin, owner outside main) Export chat history |

---

## Development

```bash
uv run --extra dev ruff check . --fix && uv run --extra dev ruff format .
uv run --extra dev mypy src/ main.py --explicit-package-bases
uv run --extra dev pytest tests/ -v
pre-commit run --all-files
```

Unit tests need no DB or network. `tests/test_schema_postgres.py` runs only when
`VEKA_TEST_DATABASE_URL` points at an **empty, disposable** PostgreSQL database.
See `AGENTS.md` for conventions.

---

## CI/CD

- **CI** (`.github/workflows/ci.yml`) runs on every push and PR: ruff, mypy,
  pytest against a PostgreSQL 17 service, `pip-audit`, and a Docker build.
- **Deploy** (`.github/workflows/deploy-discord-bot.yml`) runs only **after CI
  succeeds** for a push to `main`/`production` whose commit message starts with
  `Merge pull request`, and deploys exactly the commit CI tested. It runs on the
  self-hosted runner (`self-hosted, X64, Linux, Veka`), writes `.env` from
  repository secrets and variables, runs `docker compose up -d --build`, and
  passes only if `is ready. DB available=True` appears in the logs within 60s
  (with a warning if migrations are degraded).

Secrets: `DISCORD_TOKEN`, `DATABASE_URL`, optional `DIRECTUS_URL`,
`DIRECTUS_SERVICE_TOKEN`. Variables: the `*_IDS` lists, channel IDs and
`LOG_LEVEL`. Development happens on `dev`; open a PR `dev` → `main` to deploy.

---

## Known Issues

See `AGENTS.md` → *Known issues* and `AUDIT_REPORT.md` for the current list. Highlights:

- XP, leaderboards, profiles and the marketplace are global across guilds.
- Connection-request buttons don't survive a restart (not persistent views).
- `/exportchat` buffers history in memory.
- Mass-unban date/moderator filters only match bans the bot recorded.
- The container runs as root.

No license file is included; all rights reserved unless one is added.
