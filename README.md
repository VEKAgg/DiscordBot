# VEKA Discord Bot

Community bot for the VEKA professional network, built with [nextcord](https://github.com/nextcord/nextcord) and PostgreSQL.

## Features

- Profiles, connections and a member directory
- Marketplace with listings, offers, reviews and a forum channel that turns posts into listings
- Portfolios and mentorship
- RSS feeds per server
- XP, levels, rank cards and per-server leaderboards
- Moderation: warnings with escalation, honeypot channels, mass unban
- Per-server setup (`/setup`) and privacy controls (`/privacy`)
- Dashboard API for the web dashboard (`src/api/`)

Run `/help` in Discord for the full command list. Most commands exist as a slash command and a `!` prefix command.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- PostgreSQL

## Getting started

```bash
cp .env.example .env      # set DISCORD_TOKEN and DATABASE_URL
uv sync --extra dev
pre-commit install
python main.py
```

With Docker (bot, API and a local PostgreSQL):

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

Database migrations in `migrations/` run automatically when the bot starts.

## Configuration

All settings are environment variables; see `.env.example`.

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token (required) |
| `DATABASE_URL` | PostgreSQL DSN (or set `POSTGRES_HOST/PORT/DB/USER/PASSWORD`) |
| `BOT_OPERATOR_IDS` | Explicit bot-global operator allowlist. Empty disables operator commands and emits one startup warning; guild ownership/role names never grant operator powers. |
| `ADMIN_IDS`, `STAFF_IDS`, `INTERN_IDS`, `DONATOR_IDS`, `ACTIVE_PRO_IDS` | Comma-separated IDs for community capability/role tiers; not bot-global operator authority. |
| `ADMIN_ALERT_CHANNEL_ID` | Channel for operational alerts |
| `VEKA_CORE_URL`, `VEKA_CORE_SERVICE_KEY`, `VEKA_CORE_INSTALLATION_ID` | Canonical marketplace service origin, scoped installation key and stable service-key name |
| `FEED_MAX_*` | RSS feed limits |
| `RETENTION_*_DAYS` | Data retention overrides |
| `LOG_LEVEL`, `ENVIRONMENT` | Logging and environment |
| `API_*` | Dashboard API settings (API process only) |

Channels and roles are configured per server with `/setup` or the dashboard.

## Development

```bash
uv run --extra dev ruff check . --fix && uv run --extra dev ruff format .
uv run --extra dev mypy src/ main.py --explicit-package-bases
uv run --extra dev pytest tests/
```

`tests/test_schema_postgres.py` runs only when `VEKA_TEST_DATABASE_URL` points at an empty, disposable database.

Work on `dev` and open a pull request to `main`. Coding conventions are in [`AGENTS.md`](AGENTS.md).

## Deployment

Every push to `main` runs CI (`.github/workflows/ci.yml`) and then deploys (`.github/workflows/deploy.yml`) on the self-hosted runner: it writes `.env` from GitHub secrets and variables, builds the images and restarts the `veka-discord-bot` and `veka-api` containers with `docker compose`.

GitHub configuration (`production` environment or repository level):

- Secrets: `DISCORD_TOKEN`, `DATABASE_URL`, `VEKA_CORE_SERVICE_KEY`, optional `API_SERVICE_TOKEN`
- Variables: `VEKA_CORE_URL`, `VEKA_CORE_INSTALLATION_ID`, the ID lists, `ADMIN_ALERT_CHANNEL_ID`, and optional `LOG_LEVEL`, `FEED_MAX_*`, `API_CORS_ORIGINS`, `API_TRUSTED_PROXIES`, `API_RATE_LIMIT`, `API_PREAUTH_LIMIT`

Set `BOT_OPERATOR_IDS` explicitly before deploying. No default guild/owner or old owner/founder environment fallback is used. The startup warning clearly identifies an empty allowlist. Containers run as UID:GID `10001:10001`, with read-only root filesystems, dropped capabilities, no-new-privileges and bounded temporary storage. Compose reads the host-owned mode-600 `.env` via `env_file` and injects it; it does not mount secrets or host logs into the unprivileged process. Logs go to stdout (`docker logs`); local file logging is opt-in with `VEKA_LOG_TO_FILE=1`.

### Dashboard API

The API container publishes no host port. It joins Traefik's external `proxy-network`, and Traefik routes `https://api.veka.gg` to it using the labels in `docker-compose.yml`. The `internal-only` middleware limits it to the LAN and tailnet; only `/v1/health` is public, for status.veka.gg. The website runs on the same network and can call `http://veka-api:8080` directly.

Member names: `POST /v1/guilds/{guild_id}/members/lookup` with `{"user_ids":["123", "456"]}` (1–25 string snowflakes, duplicates coalesced). Requires the signed-in Discord user's Manage Server permission and a fresh bot-presence snapshot; service credentials/acting-user headers cannot use it. Returns `{items:[{id,username,display_name,avatar_url,found}]}`, private/no-store. Only current members of that guild are looked up (no global user fallback); 404 from Discord becomes a null-name `found:false` item, and provider failures/rate limits are retryable 503. Uses the API process's `DISCORD_TOKEN` server-side, caches minimal fields per guild/member for 60 seconds, and bounds lookup requests separately. The dashboard may batch missing names while retaining copyable IDs as fallback.

`api.veka.gg` is a Cloudflare Tunnel hostname (origin `https://<traefik host>:443`, TLS verification on). To make the whole API public, remove `internal-only@file` from the router labels.

Check it with `curl https://api.veka.gg/v1/ready` (`/v1/health` also reports the database and bot status). OpenAPI docs are disabled in production unless `API_DOCS=1`.

## License

No license file is included; all rights reserved.
