# Migration notes — `audit/modernization`

What changes when this branch is deployed, what to do before and after, and which open questions were decided by a default. Finding IDs (C-01, H-05, …) refer to `AUDIT_REPORT.md`.

## Before you deploy

1. **Back up the production database.** Five new migrations run on first start, and the migration runner, which had not applied anything since `005b` was added, starts working again:
   ```bash
   pg_dump --format=custom --file=veka-pre-audit.dump "$DATABASE_URL"
   ```
2. **Check what production has applied.** This decides which old migrations will run for the first time:
   ```sql
   SELECT filename, applied_at FROM schema_migrations ORDER BY filename;
   ```
   - The runner now treats a recorded `005_guild_and_rss_schema.sql` as `005b_guild_and_rss_schema.sql`, so 005b is not re-run.
   - Any of `006`–`021` missing from that table will be applied. They are idempotent (`IF NOT EXISTS`) except where noted in their headers.
   - If production was migrated by hand and `schema_migrations` is empty or partial, try the upgrade against a restored copy first:
     ```bash
     pg_restore -d veka_copy veka-pre-audit.dump
     VEKA_TEST_DATABASE_URL=… python -c "…run_migrations…"
     ```
     Or send me a `pg_dump --schema-only` (audit Open Question 1).
3. **Configure per-guild channels** with `/setup set` (or the now-working `/setup interactive`) in every server. Features no longer fall back to the main server's hardcoded channels from other servers (see "Behaviour changes").

## New migrations

| File | What it does | Data impact |
|---|---|---|
| `022_warnings_snowflake_ids.sql` | `warnings.user_id` / `moderator_id`: `INTEGER REFERENCES users(id)` → `BIGINT` Discord IDs. Existing rows are mapped through `users.discord_id`. | Fixes `/warn` (H-05). Rows whose user can't be mapped get `NULL`. |
| `023_honeypot_updated_by_and_log_action.sql` | Adds `honeypots.updated_by`; allows `action_type = 'log'`. | Fixes `/honeypot enable/disable/edit` and "Log Only" honeypots (M-13). |
| `024_feed_seen_per_subscription.sql` | `feed_seen_items.subscription_id` (FK, cascade) and unique `(subscription_id, item_guid)`. Seeded from `rss_cache` so existing subscriptions don't re-post. | Per-guild RSS dedupe (H-12). |
| `025_mentor_registrations.sql` | Self-matches (`mentor_id = mentee_id`) become `status = 'registered'`, duplicates are removed, and a unique index is added. | Stops repeatable XP farming via `/mentor end` (M-18). Deletes duplicate registration rows. |
| `026_listing_expiry_warning.sql` | `marketplace_listings.expiry_warned_at`. | Expiry DMs are sent once per listing (M-10). |

Edited in place (safe because the runner records them by filename):

- **`005b_guild_and_rss_schema.sql`** only drops `rss_cache` if it still has the incompatible 005 shape. Its indexes are now `IF NOT EXISTS`.
- **`017_timestamptz_conversion.sql`** also tolerates `undefined_column`. Previously it failed on a fresh database (C-03).

**Rollback:** restore the dump. 022 and 025 are not reversible in SQL.

## Behaviour changes users and staff will notice

### Permissions (C-01, C-02, H-07)

**Guards now enforced on slash commands.** These guards were silently ignored on slash commands and are now enforced:

- **Admin only:** `/massunban *`, `/radio station|start|stop|move`, `/setupleaderboard`, `/exportchat`.
- **Staff only:** `/admin featurestatus|startupchecks|detailedstatus`.
- **Main-server members, or the owner in other servers:** `/memberinfo`, `/serverinfo`.

**Restrictions tightened beyond the old intent:**

- `/admin reloadcog` is now restricted to **bot operators** (`OWNER_IDS`, `ADMIN_IDS`, or administrators of the main guild), not all staff. It only accepts entries from the `EXTENSIONS` allowlist.
- `/exportchat`:
  - Requires administrator.
  - Exports only channels that **both** the bot and the invoker can read.
  - `/exportstop` only works for the user who started the export, or an admin of the exporting guild.
- `/feed add|remove|test` require **Manage Server**.
- `/setupleaderboard` works only in the main guild.

**Discord-level permissions:**

- `default_member_permissions` is set on `/massunban` (Ban Members), `/exportchat` (Administrator) and `/setupleaderboard` (Manage Server). These commands are hidden from other members. Server admins can override this under Server Settings → Integrations.
- `/admin`, `/radio`, `/feed`, `/massunban`, `/setup`, `/exportchat` and `/exportstop` are now server-only (not available in DMs).

**Guild owners:**

- **FOUNDER (Q5 default):** owning a server only grants FOUNDER in the **main** guild. Owners of other servers get ADMIN in their own server.

**Moderation:**

- `/warn` refuses to target:
  - yourself
  - bots
  - the owner
  - administrators, unless the warner is the owner
  - members whose top role is not below the warner's

  Auto-escalation is skipped when the bot can't outrank the member.

### Cross-server fallbacks removed (H-07)

`!panic`, `/admin panic|lockdown|pingsquad`, the daily bump reminder, mass-unban logs and inactivity alerts now resolve channels **within the guild** via `/setup`. Unconfigured servers get a "not configured" message instead of posting into the main server. The lockdown alert pings `@everyone` in **that server's** staff channel only.

### Background jobs that now actually run (H-01)

nextcord never called `cog_load`, so these never started before. They start on the first deploy:

- **Activity roles** (main guild, every 6 h): adds and removes "Active Member" / "Active+" / "Active Star" roles by XP. Members inactive for 14+ days lose these roles. *If these roles were assigned by hand, expect changes.*
- **Inactivity alerts** (daily 09:00 IST):
  - Posts 1-week notices to the main guild's log channel.
  - DMs members inactive for 30+ days.
  - DMs are capped at **25 per day** (`INACTIVITY_MAX_DMS_PER_RUN`), so the backlog drains gradually instead of mass-DMing on day one.
- **Auto-updating leaderboard** in the main guild's leaderboard channel.
- **Monthly season archive:** now a daily 00:05 UTC tick that acts on the 1st. It covers the main guild only.
- **Activity-detail flush.**
- **Radio auto-join and stream monitor.** The radio also plays audio now instead of noise (H-09).
- **Rotating status**, now every 60 s (was 10 s).
- **Mass-unban job resume** after a restart.

### Mass unban (H-02, H-03, Q3 default)

- Bans with no audit record are **excluded** by default; previously they were always included. Use `include_unaudited:true` on `/massunban run|preview` to include them. This isn't possible with a moderator filter, and the prefix commands always exclude them.
- Every ban is now recorded via `on_member_ban`, so date filters become useful for bans placed from now on.
- A 429 pauses the job and leaves the item pending (previously marked failed), and only one worker runs per job.
- Per-user log posts are only sent for failures and skips.
- `/massunban status|cancel <id>` only see jobs from the current server.

### Honeypot (H-08, Q4 default)

- The action happens first. Bans and softbans purge messages server-side; `delete_days` is clamped to 0–7 and timeout hours to at most 28 days.
- Members with Manage Messages or Administrator, the owner, and members at or above the bot's top role are **exempt**. They are logged with the result `exempt`.
- If the guild's notification role is configured, honeypot alerts ping it explicitly.

### Other fixes

- **Marketplace:** `/bump` works, using the same `last_bumped_at` as `/marketplace bump`.
  - Bumping un-expires a listing.
  - Expiry counts from the last bump.
  - Expired listings no longer appear in `/marketplace browse`.
  - The "expiring soon" DM goes out once, around day 27, instead of every 6 h.
  - `/marketplace search` autocomplete works.
- **Mentorship:** `/mentor accept|complete` find requests. `/mentor end` grants XP only for `successful` outcomes on real matches.
- **`/modstats`** works, based on `warnings` plus audit rows; bans are counted from the canonical `ban_executed` event, not duplicated escalation records.
- **Feed delivery:** entries are marked seen only after a successful send; entries beyond the three-post polling cap remain eligible for later delivery.
- **Lifecycle:** all cog loops start after database initialization; exports and mass-unban workers are cancelled on cog unload. Export state is released even on failure.
- **Atomic writes:** mentorship completion and XP awards execute together once, even under concurrent requests. Listing expiry and warning selection are atomic and respect concurrent bumps.
- **Lockdown copy:** explicitly states that this is an alert, not a permission change.
- **Cleanup:** removed the unused featured-cache loop, obsolete rate-limiter cleanup task, and unused cancellation view.
- **`/stats server`** shows "Most Active Member (7d)" instead of failing; the bot stores no per-channel data.
- **`/connect request`** uses Discord's searchable member picker; previously only the first 25 members were listed. Accept/decline now notifies the requester from DMs.
- **Squad pings and the daily bump reminder** actually notify the role.
- **`/setup interactive`** applies settings through channel and role pickers.
- **Voice XP** is credited on leave; previously only channel moves counted.
- **Live role** is removed when streaming stops.
- **Rate limits** work on slash commands. The marketplace bucket is 2 actions per 5 minutes.
- **Raw DB errors:**
  - Hidden from non-staff in `/health`.
  - SQL errors now show "unexpected error" instead of "database unavailable".
  - Error logs no longer include query argument values.

## Configuration

- **`MAIN_GUILD_ID`** is now read from the environment, as `.env.example` documented. The default is unchanged. It isn't set by the deploy workflow, so the default applies.
- **`INACTIVITY_MAX_DMS_PER_RUN`** (in `config.py`) defaults to 25.
- **No new secrets.**

## Dependencies

- `aiohttp` 3.14.1 → **3.14.3**; `soupsieve` → **2.10** (advisories fixed).
- **PyNaCl stays at 1.5.0 (accepted risk).**
  - `nextcord[voice]==3.2.0` is the latest release and pins `PyNaCl<1.6`.
  - PYSEC-2026-1448 and PYSEC-2026-3002 affect libsodium's `crypto_core_ed25519_is_valid_point`. nextcord only uses `nacl.secret` for voice, so the vulnerable path isn't reachable.
  - CI ignores these two IDs explicitly. Remove the ignore when nextcord allows PyNaCl ≥ 1.6.2.
- **`requirements.txt`** is regenerated from `uv.lock`.

## Build and CI

- **Dockerfile:**
  - Multi-stage build that installs exactly `uv.lock` (`uv sync --locked`).
  - The runtime image has only `ffmpeg` and `libopus0`: no gcc, git or python3-dev.
  - It still runs as **root**, because `./logs` is bind-mounted and must stay writable. To switch to a non-root user, `chown` the host `logs/` to the container UID first, then add `USER`.
- **New `.github/workflows/ci.yml`:** ruff, format check, mypy, pytest with PostgreSQL 17 (migrations plus a SQL `prepare()` of every static query), pip-audit, and a Docker build.
- **Deploy check (Q10 default):** it still requires `is ready. DB available=True`, and now adds a warning annotation when the ready line says `migrations=degraded`. It does not fail the deploy.
- **Pre-commit:** pins aligned with the lockfile (ruff v0.15.20, mypy v2.1.0, aiohttp 3.14.3, plus Pillow and psutil for mypy).

## Defaults taken for open questions

| Q | Decision applied | Reversible by |
|---|---|---|
| 2 | Multi-guild scoping unchanged (XP, leaderboards, marketplace and profiles stay global); only cross-guild channel fallbacks were removed | Product decision (M-14) |
| 3 | Unaudited bans excluded unless `include_unaudited:true` | Change the default in `massunban_run_slash` |
| 4 | Staff exempt from honeypots | `_is_exempt` in `honeypot.py` |
| 5 | FOUNDER via ownership only in the main guild | `rbac.get_user_role` |
| 6 | `/exportchat` kept, admin-only, limited to channels the invoker can read | — |
| 7 | Lockdown stays an alert, now per guild; no channel permission changes | M-16 |
| 8 | Presence tracking unchanged | M-14 |
| 9 | Radio stays a single global stream controlled from the main guild | — |
| 10 | Deploy warns, doesn't fail, on degraded migrations | `deploy-discord-bot.yml` |
| 11 | User authorized review, fixes, and commit on 2026-10-05 | — |
