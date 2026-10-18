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
| `ADMIN_IDS`, `OWNER_IDS`, `FOUNDER_IDS`, `STAFF_IDS`, `INTERN_IDS`, `DONATOR_IDS`, `ACTIVE_PRO_IDS` | Comma-separated Discord user IDs |
| `ADMIN_ALERT_CHANNEL_ID` | Channel for operational alerts |
| `MAIN_GUILD_ID`, `MAIN_SERVER_INVITE_URL` | The main VEKA server |
| `DIRECTUS_URL`, `DIRECTUS_SERVICE_TOKEN` | Optional marketplace mirror to Directus |
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

- Secrets: `DISCORD_TOKEN`, `DATABASE_URL`, optional `DIRECTUS_URL`, `DIRECTUS_SERVICE_TOKEN`, `API_SERVICE_TOKEN`
- Variables: the ID lists, `ADMIN_ALERT_CHANNEL_ID`, and optional `LOG_LEVEL`, `MAIN_SERVER_INVITE_URL`, `FEED_MAX_*`, `API_CORS_ORIGINS`, `API_TRUSTED_PROXIES`, `API_RATE_LIMIT`, `API_PREAUTH_LIMIT`

### Dashboard API

The API container publishes no host port. It joins Traefik's external `proxy-network`, and Traefik routes `https://api.veka.gg` to it using the labels in `docker-compose.yml`. The `internal-only` middleware limits it to the LAN and tailnet; only `/v1/health` is public, for status.veka.gg. The website runs on the same network and can call `http://veka-api:8080` directly.

`api.veka.gg` is a Cloudflare Tunnel hostname (origin `https://<traefik host>:443`, TLS verification on). To make the whole API public, remove `internal-only@file` from the router labels.

Check it with `curl https://api.veka.gg/v1/ready` (`/v1/health` also reports the database and bot status). OpenAPI docs are disabled in production unless `API_DOCS=1`.

## License

No license file is included; all rights reserved.
