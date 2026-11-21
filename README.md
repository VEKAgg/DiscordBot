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
| `VEKA_CORE_URL`, `VEKA_CORE_SERVICE_KEY`, `VEKA_CORE_INSTALLATION_ID` | Canonical marketplace service origin, scoped installation key and stable service-key name |
| `FEED_MAX_*` | RSS feed limits |
| `RETENTION_*_DAYS` | Data retention overrides |
| `LOG_LEVEL`, `ENVIRONMENT` | Logging and environment |
| `API_*` | Dashboard API settings (API process only) |

Channels and roles are configured per server with `/setup` or the dashboard. Access is not configured through the environment: **operators = Developer Portal team members with the Admin/Developer role**, each server's admin/staff/perk roles come from `/setup roles` or the dashboard, and the alert channel is set with `/operator alerts`.

## Development

```bash
uv run --extra dev ruff check . --fix && uv run --extra dev ruff format .
uv run --extra dev mypy src/ main.py --explicit-package-bases
uv run --extra dev pytest tests/
```

`tests/test_schema_postgres.py` runs only when `VEKA_TEST_DATABASE_URL` points at an empty, disposable database.

Work on `dev` and open a pull request to `main`. Coding conventions are in [`AGENTS.md`](AGENTS.md).

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and the linked shared platform runbook for staging and production. `release.yml` calls separate reusable CI, GHCR image publishing and deployment workflows. `dev` auto-deploys staging after activation; production `main` deployment is manual by default, with explicit opt-in to auto-deploy.

Runtime secrets belong in restricted server files, not GitHub secrets. Repository variables `STAGING_DEPLOY_ENABLED`, `PRODUCTION_DEPLOY_ENABLED` and `PRODUCTION_AUTO_DEPLOY` control activation. The automatic job token handles GHCR authentication. The existing `docker-compose.yml` describes the pre-cutover manual deployment; new workflows use the installed shared platform stack instead. Follow the cutover runbook to stop old containers before replacing production routes or using the same bot token.

Operators come from the Discord Developer Portal team, so an empty team disables operator commands with one startup warning; there is no default guild/owner or legacy owner/founder environment fallback. Containers run as UID:GID `10001:10001`, with read-only root filesystems, dropped capabilities, no-new-privileges and bounded temporary storage. The platform stack reads host-owned mode-600 `bot.env` via literal `env_file` and injects it; it does not mount secrets or host logs into the unprivileged process. Logs go to stdout (`docker logs`); local file logging is opt-in with `VEKA_LOG_TO_FILE=1`.

### Dashboard API

The API publishes no host port. The website calls the environment-specific private backend alias (`http://veka-staging-bot-api:8080` or `http://veka-production-bot-api:8080`). Staging has no public API router. Production retains only `https://api.veka.gg/v1/health` for status.veka.gg; authenticated dashboard endpoints remain private.

Member names: `POST /v1/guilds/{guild_id}/members/lookup` with `{"user_ids":["123", "456"]}` (1–25 string snowflakes, duplicates coalesced). Requires the signed-in Discord user's Manage Server permission and a fresh bot-presence snapshot; service credentials/acting-user headers cannot use it. Returns `{items:[{id,username,display_name,avatar_url,found}]}`, private/no-store. Only current members of that guild are looked up (no global user fallback); 404 from Discord becomes a null-name `found:false` item, and provider failures/rate limits are retryable 503. Uses the API process's `DISCORD_TOKEN` server-side, caches minimal fields per guild/member for 60 seconds, and bounds lookup requests separately. The dashboard may batch missing names while retaining copyable IDs as fallback.

`api.veka.gg` remains a Cloudflare Tunnel hostname. Check the public `/v1/health`; `/v1/ready` is checked inside the API container and is not publicly routed by the platform stack. Rollout also requires a fresh heartbeat matching the deployed bot revision and a successful scoped core-integration probe. OpenAPI docs are disabled in production unless `API_DOCS=1`.

## License

No license file is included; all rights reserved.
