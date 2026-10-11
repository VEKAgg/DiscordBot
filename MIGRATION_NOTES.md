# Migration notes

What deploying `overhaul/discord-bot-2026-10` (2026-10-11) changes, and what to do before and after. Migrations 001–028 were deployed earlier; this release adds 029–037.

## Deploy checklist

1. **Back up the production database** (`pg_dump --format=custom --file=veka-pre-overhaul.dump "$DATABASE_URL"`). Migrations 029–037 run on first start; 032 rewrites the gaming/coding totals and 037 changes the tracking default.
2. Check `SELECT filename FROM schema_migrations ORDER BY filename;` shows 001–028 before deploying.
3. After the bot is up, in the main server:
   - `/setup option presence_tracking on` — game/coding/streaming tracking is now off until a server turns it on.
   - `/setup set marketplace #market` — marketplace posts no longer use `MARKETPLACE_CHANNEL_ID`.
   - `/setupleaderboard #channel` if the auto-leaderboard should continue (it posts one new message, then edits it).
   - Optional: `/setup option inactivity_dms on`, `/setup option bump_reminder on` (both off by default).
4. Delete the old auto-leaderboard message by hand if you want.

## Outbound safety — stop the bot getting quarantined

Discord quarantined the bot during a mass unban: it DMed the same apology to every unbanned user every 1.5 s (most share no server with the bot, so most DMs failed) and posted a log embed per skipped user. This branch puts every bot-initiated message behind one guard and makes unsolicited DMs opt-in.

### New migrations

| File | What it does | Data impact |
|---|---|---|
| `029_outbound_safety.sql` | `massunban_jobs`: `notify_users` (default false), `dm_sent`, `dm_failed`, `rate_limit_hits`, `progress_channel_id/message_id`. `guild_settings.inactivity_dm_enabled` (default false). Index `audit_logs(guild_id, action, created_at)`. | Additive. |
| `030_marketplace_publications.sql` | `guild_settings.marketplace_channel_id`; `marketplace_listings.price` nullable (unknown forum prices), condition `unknown`, `source`, `thread_id` (unique), `guild_id`; `marketplace_publications`, `marketplace_cms_publications`. | Additive; no listings deleted. Existing bot-created forum threads have no stored publication ID, so `!marketplace_sync` may post them once more. |
| `031_marketplace_images.sql` | `marketplace_listing_images` (≤4 WebP per listing, ≤2 MB each, BYTEA) and `marketplace_listings.image_missing`. | DB/backup size grows by the stored images. |

### Configuration

- `MARKETPLACE_CHANNEL_ID` is no longer used; each server sets `/setup set marketplace` (no global fallback).
- New optional env vars: `RETENTION_ACTIVITY_LOG_DAYS` (90), `RETENTION_HONEYPOT_EVENTS_DAYS` (180), `RETENTION_MASSUNBAN_ITEMS_DAYS` (180), `RETENTION_WITHDRAWN_LISTING_IMAGES_DAYS` (30). No new required variables, secrets or services.

### Behaviour changes

- **Mass unban:** apology DMs only with `notify_users:true` / `--notify` (max 50/job, users who still share a server, 5 s apart, stop after 5 failures). One edited progress message in the log channel + one summary DM to the runner; no per-user log embeds, no resume/rate-limit DMs. One API call per user (the separate `fetch_ban` is gone). The command defers and the job runs in the background.
- **Honeypot:** first trigger per server alerts (with ping); more triggers within 60 s become one digest without a ping.
- **Welcome:** more than 5 joins/min → one batched welcome, no cards.
- **Inactivity:** one daily digest instead of an embed per member; DMs opt-in per server.
- **Squad ping:** once per server per 10 minutes.
- **Marketplace:** posts only to the invoking server's channel; member forum posts become listings; images stored durably; sync/push bot-operator only (max 25/run); manual forum posts are not mirrored to Directus.
- **Expiry/check-in/offer/connection DMs:** batched per user, capped, only to users who share a server.
- **Permissions:** a role *named* "Founder" grants founder powers only in the main server (elsewhere at most admin). `/setup` guards follow the project convention and are covered by the permission test.
- **Retention:** nightly at 03:30 UTC (see AGENTS.md "Maintenance").

### Tracking accuracy and privacy (migration 032)

| File | What it does | Data impact |
|---|---|---|
| `032_tracking_accuracy.sql` | `users.total_coding_minutes`, `users.presence_opt_in` (default changed to true by 037), `user_activity_daily.commands`, `guild_settings.leaderboard_message_id`, indexes, unique `leaderboard_snapshots(guild, month, category, user)`. | **Rewrites** `total_gaming_minutes` and fills `total_coding_minutes` from `user_activity_details` for users with detail rows (the old totals were double-counted and mixed with coding). Deletes duplicate snapshot rows before adding the unique index. Streaming totals stay inflated (no source to repair from). |

Behaviour after deploy:
- Game/coding/streaming tracking follows the server opt-in / member opt-out model from migration 037 (below). Message/voice/command XP continues for everyone.
- Command XP and `total_commands` start counting (they never did).
- Voice minutes are real (no 60-minute cap); XP per continuous session is still capped at 60. AFK channel/deafened members earn nothing; members alone earn minutes but no XP.
- All leaderboards inside a server, `/serverstats` and `/stats demographics` are per server. Per-server history only exists from when `user_activity_daily` started being written, so early months may look small.
- The auto-leaderboard posts **one new message** after deploy (its ID wasn't stored before) and edits it from then on. The old message can be deleted by hand.
- `/most listened` and all listening/Spotify tracking are gone.
- Manual verification: `docs/VERIFY_TRACKING.md`.

### Dashboard API (migration 033) — dev only for now

| File | What it does | Data impact |
|---|---|---|
| `033_api_bridge.sql` | `bot_status`, `bot_guild_snapshot` (written by the bot), mass-unban dashboard columns (`source`, `include_unaudited`, confirm token hash/step/expiry, `claimed_at`), `massunban_jobs.status` widened to `VARCHAR(32)`, unique `(job_id, target_user_id)` on job items. | Additive. |

- The bot starts writing its status/guild snapshots and listening on `veka_cache` immediately; nothing else changes for users.
- The API runs only in `docker-compose.dev.yml` (`api` service, port 8080). **Production wiring is not done** (needs: an `api` service in the prod compose with `UV_EXTRAS=--extra api`, `API_SERVICE_TOKEN`/`API_CORS_ORIGINS` secrets/variables, a reverse proxy with TLS, and `API_TRUSTED_PROXIES`). That is a deploy change for the owner to approve.
- **Moving the SvelteKit dashboard off direct DB reads** (we did not edit `veka`): (1) deploy the API on the internal network and give the web app `VEKA_API_URL`; (2) pass the user's Discord OAuth access token (scopes `identify guilds`, already used for the guild picker) as the bearer token; (3) replace Drizzle reads page by page — guild picker → `/v1/me/guilds`, settings → `/v1/guilds/{gid}/settings` (send `If-Match`), moderation → `/warnings` + `/audit-log`, mass unban → `/massunban/jobs` flow, privacy → `/v1/me/privacy`, leaderboards/profile XP → `/leaderboards` + `/members/{uid}/activity`, server charts → `/stats/daily`, feeds → `/feeds`, honeypots → `/honeypots`, marketplace → the marketplace endpoints; (4) remove the web app's credentials for the bot's tables; (5) later swap Discord bearer tokens for VEKA sessions inside the API's auth dependency only.
- **Container still runs as root.** Making it non-root needs the deploy to stop mounting `.env` with mode 600 owned by the runner (e.g. pass variables via `env_file:` or make the file group-readable by a fixed GID) — a deploy change, so not done.

### Multi-server readiness (migration 037) — owner/partner decision 2026-10-11

The bot is meant to be added to other servers, configured by their Manage Server admins in the dashboard.

| File | What it does | Data impact |
|---|---|---|
| `037_presence_server_opt_in.sql` | `guild_settings.presence_tracking_enabled` (default **off**), `users.presence_opt_in` default **TRUE** (now means "tracking allowed"), `guild_settings.inactivity_alerts_enabled` (default on), `inactivity_notices`, `season_announcements`, index on daily rollups. | Members who never chose become "allowed"; explicit opt-outs stay out. |

Behaviour:
- **Game/coding/streaming tracking runs only in servers whose admins turn it on** (`/setup option presence_tracking on` or the dashboard). Members can `/privacy optout` (and `/privacy optin` to allow again). Music/Spotify is never tracked. **To keep tracking in the main VEKA server, turn it on there after deploy.**
- Leaderboards inside a server show that server's activity only (all time = since per-server tracking began). `/level`, `/rank` keep global XP, labelled "all servers".
- Each server gets its own auto-leaderboard (`/setupleaderboard` now works in any server, Manage Server), activity roles (if it has roles with those names; privileged roles are skipped), daily inactivity digest (on by default where a log channel is set; `/setup option inactivity_alerts off`), and season announcement.
- Inactivity is now "no activity *in this server*" (members who never posted count from when they joined), with per-server notified markers; the old global flags on `users` are no longer used.

### Mentorship (migration 035) and bump reminder (migration 036)

- Mentorship is one guild-scoped model: mentors opt in (`/mentor register`/`apply`), requests → active → completed/cancelled, the mentor certifies completion, 50/25 XP once per completed engagement. Old mentorships stay as unbound history; `mentorship_matches` is a read-only archive. **`/mentor end` now takes an M-prefixed ID** (e.g. `M123`). Reminders are opt-in (`/mentor reminders`).
- The daily bump reminder runs in every server that turns it on (`bump_reminder`, off by default) and has a public commands channel.
- The dashboard API requires Manage Server for every server route.

### Data decisions (delegated to the agents by the owner on 2026-10-11)

Recorded in the agent notes (`DECISIONS.md`). Existing listening/presence rows are not deleted automatically; if the owner wants them gone:

```sql
DELETE FROM user_activity_details WHERE activity_type = 'listening';
UPDATE users SET total_listening_minutes = 0;
```
