# VEKA Discord Bot — Audit Report

- **Branch:** `audit/modernization` (cut from `dev` @ `0dab564`).
- **Status:** Phases 1–3 (audit) approved; **Phases 4–5 (remediation) and follow-up diff review completed; user authorized committing the reviewed changes on 2026-10-05**. See **§8 Remediation log** for the status of every finding, and `MIGRATION_NOTES.md` for deployment.
- **Date:** 2026-10-05
- **Scope:** all 61 Python modules under `src/` + `main.py` (~18.7k LOC), 21 migrations, Docker/CI/tooling, tests.

## How findings were verified

Most findings come from reading the code. The ones marked **[verified]** were also reproduced:

| Probe | What it showed |
|---|---|
| Loaded all 22 extensions offline and walked every application command (110 slash leaves, 57 prefix commands) | **Every slash command has `checks == []`.** The `commands.check`-based decorators (`admin_only`, `staff_only`, `owner_in_external_only`, `main_server_only`) set `__commands_checks__`, which nextcord application commands never read. |
| `grep -rn cog_load` over the installed nextcord 3.2.0 | **Zero references.** `cog_load()` is never called, and `async def cog_unload()` is called without `await` (pytest itself warns: `coroutine 'RadioManager.cog_unload' was never awaited`). |
| Throwaway PostgreSQL 18, real `db.run_migrations()` against an empty DB | `RuntimeError: Duplicate migration prefix detected: prefix 005` → **0 tables created.** |
| Same DB, applying every migration in order and skipping past failures | `017_timestamptz_conversion.sql` **fails** (`UndefinedColumnError: column "cached_at" does not exist`). All the others apply. |
| `asyncpg.prepare()` on all 241 static SQL statements against that schema | 7 reference columns that don't exist (listed under H-11 / M-03 / M-04 / M-13). |
| Real insert into `warnings` with Discord IDs | `DataError: value out of int32 range` |
| FFmpeg run with the radio's exact argument order | Output starts with `OggS`, i.e. an Ogg container, not PCM. |
| `pytest`, `ruff`, `mypy`, `pip-audit` | 126 passed · ruff clean · **mypy: 27 errors** · **10 known vulns in 3 packages** |

Anything not reproduced is marked as reasoned, or is listed under Open Questions.

---

## 1. Executive summary

**Health score: 3.5 / 10 at audit → ~7 / 10 after Phase 4–5** (all Critical and High findings fixed except the PyNaCl pin, which is blocked upstream; mypy 27 → 0 errors; tests 126 → 176; schema and SQL are now checked against real PostgreSQL in CI).

The core is reasonable: a layered layout, a degraded-mode design, a DB health loop, parameterized SQL and a ruff/pytest baseline. But three systemic defects undercut most of the feature work:

1. **Slash-command authorization is a no-op** for every command guarded by `admin_only` / `staff_only` / `owner_in_external_only`. Any member of any guild the bot is in can mass-unban, export private channels, reload cogs, hijack the radio and repoint the global leaderboard.
2. **`cog_load` doesn't exist in nextcord.** RPG background jobs (leaderboard, activity roles, inactivity alerts, season archive, detail flush), the radio auto-join and monitor, the rotating status and mass-unban resume have never run.
3. **A fresh database cannot be provisioned.** The runner refuses to start because of `005`/`005b`, and migration 017 fails even when forced. The deploy health check still passes, because it only greps `DB available=True`.

In addition, several advertised features are broken against the actual schema: warnings, `/modstats`, reviews, `/bump`, mentorship accept/complete, `/stats server`, and honeypot enable/disable/edit.

**Top 5 risks**

| # | Risk | IDs |
|---|---|---|
| 1 | Any user can run privileged slash commands (`/massunban run`, `/exportchat`, `/admin reloadcog`, `/radio *`, `/setupleaderboard`) | C-01 |
| 2 | `/exportchat` DMs the full history of every channel the **bot** can read, including staff-only channels | C-02 |
| 3 | Mass-unban "date range" is a no-op, so a run unbans essentially every ban, and rate-limit handling spawns duplicate workers | H-02, H-03 |
| 4 | Fresh deploy or DB restore yields an empty schema while CI reports success | C-03 |
| 5 | SSRF: any member can make the bot fetch arbitrary URLs (internal network, cloud metadata) via `/feed test` and `/resource latest` | H-04 |

**No hardcoded secrets found.** `.env` is git-ignored and untracked. A history scan for Discord tokens, DB URLs with passwords, webhooks and API keys found only placeholders. Rotation is not required on the evidence available.

---

## 2. Phase 1 — Discovery & architecture

### 2.1 Repository map

```
main.py                      → src.core.app.run_bot()
src/core/       app.py (bootstrap, EXTENSIONS allowlist, events, error handlers, DB health loop)
                checks.py (startup checks) · runtime_state.py (global health dataclass)
src/config/     config.py (env + many hardcoded IDs/constants)
src/database/   database.py (asyncpg pool wrapper + migration runner) · migrations.py
src/services/   guild_settings, admin_notifier, rss, networking, mentorship, inactivity,
                directus_sync, quiz (stub)
src/utils/      safety.py (wrappers, admin_only/staff_only), embeds.py, footer.py, guild_gate.py,
                card_generator.py (Pillow), http.py (shared aiohttp), logger.py,
                security/{rbac, rate_limiter, audit, validation}, marketplace/fraud_detection.py
src/cogs/       22 extensions (admin/*, networking, marketplace/*, marketplace_enhanced, mentorship,
                portfolio, radio, rpg, resources/feeds, stats, status, external/{info,export})
migrations/     001…021 (no 002; 005 + 005b)
tests/          6 files, 126 tests (all mocked)
Dockerfile · docker-compose.yml · docker-compose.dev.yml · .github/workflows/deploy-discord-bot.yml
```

Leftovers: `src/cogs/gamification/` and `src/cogs/workshops/` (only `__pycache__`), `src/discord_bot.egg-info/` (untracked build artefact), stale `requirements.txt`.

### 2.2 Stack & dependencies

| Item | Declared | Installed | Notes |
|---|---|---|---|
| Python | `>=3.13` (`.python-version` 3.13) | 3.13.15 | Docker `python:3.13-slim` |
| nextcord[voice] | ==3.2.0 | 3.2.0 | No `cog_load` hook (see H-01) |
| aiohttp | ==3.14.1 | 3.14.1 | **3 advisories**, fixed in 3.14.2/3.14.3 |
| asyncpg | ==0.31.0 | 0.31.0 | |
| Pillow | >=11 | 12.3.0 | |
| psutil | >=5.9 | 7.2.2 | Missing from `requirements.txt` |
| feedparser / bs4 / validators / dotenv | pinned | — | soupsieve 2.8.4 (transitive): **2 advisories**, fixed in 2.9.0 |
| PyNaCl (voice extra) | — | 1.5.0 | **2 advisories**, fixed in 1.6.2 |
| ruff / mypy (dev) | >=0.11 / >=1.15 | 0.15.20 / 2.1.0 | pre-commit pins ruff v0.11.0 and mypy v1.15.0, which drift from local |

`pip-audit` IDs: PYSEC-2026-3545/3546/3547 (aiohttp), PYSEC-2026-1448/3002 (pynacl), PYSEC-2026-4170/4171 (soupsieve). I did not review the advisory details offline.

### 2.3 Boot & data flow

1. `run_bot()` → `load_dotenv` → `setup_logging` → `build_bot()` (prefix `!`, intents: message_content, members, presences, guilds, voice_states).
2. `load_extensions()` iterates `EXTENSIONS`. Failures go to `runtime_state.failed_cogs`. Cog `__init__`s start some `tasks.loop`s (feeds, stats, mentorship, notifications, marketplace_enhanced).
3. `on_ready` (guarded to run once) does: notifier → `initialize_database()` (connect + migrations) → `StartupChecks` → startup summary alert → `db_health_check` (30 s) → logs `is ready. DB available=…` → `sync_all_application_commands()`.
4. Request path: cog handler → `safe_*` wrapper (DB gate + catch-all) → optional service → global `db` singleton → asyncpg pool (1–10).
5. State: PostgreSQL only. In-memory caches cover guild settings, the honeypot channel map, cooldown dicts, `runtime_state.alert_state_cache`, and radio/export/massunban job state.

### 2.4 Inventory

**Slash commands (110 leaves):** activity{stats,summary} · admin{broadcast,detailedstatus,featurestatus,lockdown,panic,pingsquad,reloadcog,startupchecks} · botinfo · bump · clearwarnings · connect{list,request} · directory search · exportchat · exportstop · featured · feed{add,list,remove,test} · health · hello · help · commands · honeypot{create,delete,disable,edit,enable,list,status,test,view} · leaderboard{season,show} · level · logging{clearrole,setchannel,setrole,view} · marketplace{browse,bump,helpful,mylistings,myoffers,offer,post,review,reviews,search,seller,stats,unwatch,view,watch,watchlist,withdraw} · marketstats · massunban{cancel,preview,recent,run,status} · memberinfo · mentor{accept,apply,complete,end,list,register,request,stats} · modstats · most{coded,listened,played,streamed} · ping · portfolio{add,delete,list,search,view} · profile{edit,set,setup,view} · radio{list,move,start,station,status,stop} · rank · resource{latest,sources} · serverinfo · serverstats · setup{interactive,reset,set,show} · setupleaderboard · stats{demographics,server} · uptime · warn · warnings · welcome test.

**Prefix commands (57):** broadcast, clearwarnings, connect, connections, health, hello, help, honeypot(+8), lockdown, logging(+4), marketplace_push, marketplace_sync, massunban(+5), mentor(+6), modstats, panic, ping, pingsquad, portfolio(+5), profile, radiolist, radiostation, setup(+3), setupprofile, warn, warnings.

> The "dual command surface" convention is only partly followed. Marketplace, feeds, RPG, stats, radio controls, export and info are slash-only.

**No context-menu commands. Autocomplete:** one handler (`marketplace.py:753`), never registered.

**Event listeners:** `on_ready`, `on_disconnect`, `on_command_error`, `on_application_command_error` (app.py); `on_message` (honeypot, rpg); `on_member_join` (welcome, stats); `on_member_remove` (stats); `on_voice_state_update`, `on_application_command`, `on_presence_update` (rpg). There is no `on_guild_remove` or `on_error`.

**Components:** massunban ConfirmFirst/ConfirmSecond (`CancelJobView` is unused) · Setup select · networking member-select + Accept/Decline (non-persistent, `timeout=None`) · RPG pagination.

**Background loops:**

| Loop | Interval | Starts? |
|---|---|---|
| `db_health_check` | 30 s | ✅ |
| feeds `feed_update` | 15 min | ✅ |
| stats `daily_stats_collector` | 30 min | ✅ |
| mentorship `check_in_loop` | 24 h | ✅ |
| notifications `daily_bump` | 1 min | ✅ |
| marketplace_enhanced ×3 | 6/12/24 h | ✅ |
| rpg ×5 (leaderboard, activity roles, inactivity, detail flush, season archive) | | ❌ only started in `cog_load` |
| radio ×2 (stability monitor, listener tracking) | | ❌ only started in `cog_load` |
| status rotation | 10 s | ❌ only started in `cog_load` |
| massunban resume | | ❌ only started in `cog_load` |

**External integrations:** Discord, PostgreSQL, RSS (arbitrary URLs), Directus CMS (optional, token), SomaFM/FluxFM/CDN Icecast streams via FFmpeg, Discord CDN downloads (avatars, attachments).

**Scaffolding & dead code:**

- `quiz_service.py` raises `NotImplementedError` and has no cog
- `update_featured_listings` is a stub that only logs (`marketplace_enhanced.py:582`)
- `mp_search_autocomplete` is unregistered and calls a nonexistent `response.autocomplete`
- `CancelJobView` is unused
- `/setup` interactive has no message listener
- `Moderation.panic_slash` / `lockdown_slash` are plain methods, not commands
- `RADIO_STREAM_URL` and `RADIO_REFRESH_INTERVAL` config is unused
- RBAC lists `quiz` / `workshops` permissions that nothing uses
- `audit_log` / `audit_action` are never called

---

## 3. Phase 2 — Feature completeness

Legend: ✅ complete · 🟡 partial · 🔴 not started · ⚫ broken · ❓ unverifiable. Multi-guild: **G** = guild-scoped, **X** = global/cross-guild, **M** = main-guild-only hardcoding. "Tests" reflects `tests/`.

| Feature / service | Status (audit) | After Phase 4–5 | Evidence | What's missing / wrong | Effort | Pri |
|---|---|---|---|---|---|---|
| Bootstrap & extension allowlist | 🟡 | ✅ | `app.py:23-46,85-94` | Loads fine; `cog_load` hooks dead (H-01) | S | P0 |
| DB wrapper & degraded mode | 🟡 | ✅ | `database.py:78-174` | Query errors reported as "DB unavailable"; OS/timeout errors unwrapped; no `command_timeout` | M | P1 |
| Migration runner | ⚫ | ✅ | `database.py:186-197`; `017_*.sql` | Fresh DB gets 0 tables; 017 fails fresh **[verified]** | S | P0 |
| DB health loop + admin alerts | ✅ | ✅ | `app.py:99-163`, `admin_notifier.py` | — (tested) | — | — |
| Startup checks / summary | ✅ | ✅ | `checks.py` | "Config Load" check is a constant PASS | S | P3 |
| Guild settings service + `/setup show/set/reset`, `!setup` | ✅ | ✅ | `guild_settings_service.py`, `setup.py:88-289` | G; slash usable in DMs → AttributeError | S | P2 |
| `/setup interactive` | ⚫ | ✅ | `setup.py:214-336` | Asks user to "mention in chat"; nothing listens | M | P2 |
| RBAC (function-wrapper `require_*`) | ✅ | ✅ | `rbac.py:185-255` | Works on prefix and slash; role-name based, so any guild can self-grant | — | P1 |
| `admin_only`/`staff_only`/guild-gate on slash | ⚫ | ✅ | `safety.py:127-150`, `guild_gate.py:21-91` | Ignored by nextcord app commands **[verified]** | S | **P0** |
| Rate limiting | ⚫ | ✅ | `rate_limiter.py:199-221` | `ctx.author` on Interaction → crash; checks key `user:marketplace` but consumes `user:<cmd name>` | S | P1 |
| Audit logging | 🔴 | 🟡 | `audit.py` | Never called anywhere | M | P1 |
| Input validation | 🟡 | 🟡 | `validation.py` | Used in 2 places only | M | P2 |
| `/help`, `/commands`, `!help` | ✅ | ✅ | `help.py` | — | — | — |
| `/health`, `/botinfo`, `/uptime`, `!health` | ✅ | ✅ | `health.py:89-362` | `/health` (public) shows raw `last_db_error` | S | P2 |
| `/admin featurestatus/startupchecks/detailedstatus` | 🟡 | ✅ | `health.py:187-229,364` | Works, but open to everyone (C-01) | S | P0 |
| `/admin reloadcog` | ⚫ | ✅ | `health.py:231-277` | Unauthenticated reload/load of any `src.cogs.*` | S | **P0** |
| Lockdown (`!panic`, `/admin panic`) | 🟡 | 🟡 | `moderation.py:36-82` | Only flips an unused flag + `@everyone` in hardcoded M channel | M | P2 |
| Warnings + auto-escalation | ⚫ | ✅ | `moderation.py:105-339`; `008_*.sql` | `warnings.user_id` is `INTEGER REFERENCES users(id)` but snowflakes are inserted **[verified]** | M | P1 |
| `/modstats` | ⚫ | ✅ | `moderation.py:373-386` | Queries `audit_logs.moderator_id/action_type` (don't exist) **[verified]** | S | P2 |
| Honeypot trigger/create/list/view/delete/status/test | 🟡 | ✅ | `honeypot.py:358-503,638-959` | Slow cross-channel purge before ban; no staff exemption; no input bounds | M | P1 |
| Honeypot enable/disable/edit | ⚫ | ✅ | `honeypot.py:842,900` | Column `updated_by` doesn't exist **[verified]** | S | P1 |
| Honeypot logging config | ✅ | ✅ | `honeypot.py:965-1065` | — | — | — |
| Mass unban | ⚫ | ✅ | `massunban.py` | Unauthenticated slash (C-01); filters no-op (H-02); duplicate workers (H-03); resume never runs | L | **P0** |
| Daily bump reminder / pingsquad / broadcast | 🟡 | ✅ | `notifications.py` | Role mention inside embed never pings; `bot.main_guild` doesn't exist; M channel fallback reachable cross-guild | S | P2 |
| Welcome message + card, `/welcome test` | ✅ | ✅ | `welcome.py` | G; template/card toggle have no command (DB-only) | S | P3 |
| Profiles (`/profile *`, `!profile`, `!setupprofile`) | ✅ | ✅ | `networking.py:346-598,703-727` | X (profiles are global) | — | — |
| Connections (`/connect *`, `!connect`) | 🟡 | 🟡 | `networking.py:16-178,459-537` | Picker lists only first 25 members; DM Accept can't notify requester (`guild` is None in DM); buttons die on restart | M | P2 |
| Directory search | ✅ | ✅ | `networking.py:611-700` | ❓ not runtime-verified | — | — |
| Portfolio | ✅ | ✅ | `portfolio_manager.py` | Second-resolution IDs → PK collisions | S | P3 |
| Mentor register (roles) | ✅ | ✅ | `mentorship.py:48-103` | Auto-creates roles | — | — |
| Mentor request/accept/complete/list/stats | ⚫ | ✅ | `mentorship.py:238,294,739`; `mentorship_service.py:62,85` | Compares int PK to snowflake string → never matches; mutates immutable `Record` | M | P1 |
| Mentor apply/end/check-ins | 🟡 | ✅ | `mentorship.py:393-605` | Self-match rows (mentor = mentee), no unique key → repeatable XP grant | S | P2 |
| Marketplace post/browse/view/mylistings/withdraw/bump/stats | ✅ | ✅ | `marketplace.py` | X; listing IDs collide per second; descriptions can overflow embeds; posts to one global channel | S | P2 |
| Marketplace search | ✅ | ✅ | `marketplace_enhanced.py:36-80,480-549` | Autocomplete dead | S | P3 |
| Watchlist | 🟡 | 🟡 | `marketplace_enhanced.py:82-180` | Promises price-change notifications; none exist | M | P3 |
| Offers | 🟡 | 🟡 | `marketplace_enhanced.py:182-343` | No accept/reject/counter flow | M | P2 |
| Transactions / "sold" | 🔴 | 🔴 | — | Nothing writes `marketplace_transactions` or `status='sold'` | L | P2 |
| Reviews & reputation (`review/seller/reviews/helpful`) | ⚫ | 🟡 | `marketplace.py:700`; `reviews.py:201,279` | `rate_limit` crash; ambiguous `id`; snowflake into int4; no transactions to review | M | P2 |
| `/bump` (listing) | ⚫ | ✅ | `reviews.py:310-353` | Column `bumped_at` doesn't exist **[verified]**; rate_limit crash; name clashes with Disboard `/bump` | S | P2 |
| `/featured`, `/marketstats` | ✅ | ✅ | `marketplace_enhanced.py:345-478` | Duplicates `/marketplace stats` | — | P3 |
| Marketplace background tasks | 🟡 | 🟡 | `marketplace_enhanced.py:552-633` | DMs every 30-day-old seller every 6 h indefinitely; featured is a stub; first expiry run happens before DB is up | S | P1 |
| Directus CMS mirror (`!marketplace_push`, sync on post) | ❓ | ❓ | `directus_sync.py` | Needs credentials; re-hosts any attachment type | — | P3 |
| Fraud detection (offers) | ❓ | ❓ | `fraud_detection.py` | Not runtime-verified | — | — |
| RSS feeds (`/feed *`, `/resource *`) | 🟡 | ✅ | `feeds.py`, `rss_service.py` | No authz; SSRF; dedupe shared across guilds | M | **P0** |
| Feed poller | 🟡 | ✅ | `feeds.py:34-86` | Same dedupe bug (H-12) | S | P1 |
| Radio | ⚫ | ✅ | `radio.py` | Never auto-starts; FFmpeg emits Ogg into PCM reader **[verified]**; controls unauthenticated; single global voice client | M | P1 |
| XP: messages / voice / commands, streaks | ✅ | ✅ | `rpg_manager.py:252-433,593-682` | X; voice capped at 60 min; coding minutes credited to gaming | S | P2 |
| `/level`, `/rank` (Pillow cards) | ✅ | ✅ | `rpg_manager.py:1263-1388` | ❓ visual output not verified | — | — |
| `/leaderboard show` | ✅ | ✅ | `rpg_manager.py:1409-1527` | X | — | — |
| `/leaderboard season` | 🟡 | ✅ | `rpg_manager.py:1529` | Archive task never runs | S | P2 |
| Auto-leaderboard, activity roles, inactivity alerts, detail flush, season archive | ⚫ | ✅ | `rpg_manager.py:216-227,919-1256` | Never started; also uses `bot.guilds[0]`; un-awaited `alert_embed` + `safe_send(channel)` no-op | M | P1 |
| `/setupleaderboard` | ⚫ | ✅ | `rpg_manager.py:1614-1646` | Anyone can repoint the **process-global** leaderboard channel | S | **P0** |
| Presence tracking / live role | 🟡 | 🟡 | `rpg_manager.py:684-742` | Live role never removed (`:709`); writes on every presence event | S | P2 |
| `/most *`, `/activity *`, `/serverstats`, `/stats demographics` | ✅ | ✅ | `stats.py`, `rpg_manager.py:1648-1877` | X (activity details have no guild_id) | — | P2 |
| `/stats server` | ⚫ | ✅ | `stats.py:847` | Column `user_activity_daily.channel_id` doesn't exist **[verified]** | S | P2 |
| Daily server stats collector | ✅ | ✅ | `stats.py:54-102` | G | — | — |
| Rotating status | ⚫ | ✅ | `status.py:86` | Never started | S | P3 |
| `/memberinfo`, `/serverinfo` | 🟡 | ✅ | `info.py` | Owner gate ignored (open to all) | S | P2 |
| `/exportchat`, `/exportstop` | ⚫ | 🟡 | `export.py` | C-02 | M | **P0** |
| Quiz | 🔴 | 🔴 | `quiz_service.py` | Stub only | — | — |
| Workshops / gamification | 🔴 | 🔴 | empty dirs; RBAC perms | Referenced only | — | — |
| `!hello`/`!ping`/`/hello`/`/ping` | ✅ | ✅ | `basic.py` | — | — | — |

**Completion summary (62 rows):**

| Status | At audit | After Phase 4–5 |
|---|---|---|
| ✅ Complete | 21 | 47 |
| 🟡 Partial | 17 | 10 |
| 🔴 Not started | 4 | 3 |
| ⚫ Broken | 18 | 0 |
| ❓ Unverifiable | 2 | 2 |

Weighted completion (✅ = 1, 🟡 = 0.5, others = 0): **≈ 48 % at audit → ≈ 84 % after remediation**. "After" ✅ means fixed and covered by tests or an offline probe. Nothing was exercised against live Discord, so radio playback in a voice channel, role changes and DMs still need a smoke test after deploy (see §8).

At the initial audit, coverage was limited to wrappers, embeds, guild settings, runtime state, migration naming, and cog imports. The reviewed remediation now includes handler regressions and real PostgreSQL schema/SQL/concurrency tests.

---

## 4. Phase 3 — Bug & risk register

Sorted by severity. Each entry gives the location, then the problem and its impact, then the fix.

### Critical

**C-01 · Security/Discord · Slash-command authorization bypass** **[verified]**

- **Where:** `safety.py:127-150` (`admin_only`, `staff_only` = `commands.check`), `guild_gate.py:21-91`. Used on:
  - `/massunban run|preview|status|cancel|recent` (`massunban.py:285-341`)
  - `/admin reloadcog|featurestatus|startupchecks|detailedstatus` (`health.py:187-366`)
  - `/radio station|start|stop|move` (`radio.py:383,445,495,524`)
  - `/setupleaderboard` (`rpg_manager.py:1614`)
  - `/exportchat` (`export.py:386`)
  - `/memberinfo`, `/serverinfo` (`info.py:26,84`)
- **Problem:** nextcord application commands only honour `application_checks` / `ApplicationCommand.checks`. `commands.check` stores predicates in `__commands_checks__`, which only prefix `Command` reads. None of these slash bodies re-check permissions, and no command sets `default_member_permissions`.
- **Impact:** Any member of any guild the bot is in can unban every banned user (the bot holds Ban Members), reload or disrupt cogs mid-job, move or stop the radio across guilds, and repoint the global leaderboard into their own server.
- **Fix:** Rewrite the guards as dual-mode decorators. For slash commands use `application_checks.check` (or a predicate inside the existing `safe_slash_command` wrapper). Add `default_member_permissions` (e.g. `ban_members` for massunban) and `dm_permission=False`. Add a test that asserts every privileged slash command has a non-empty `checks` list.

**C-02 · Security/Privacy · `/exportchat` reads past channel permissions** (`export.py:383-468`)

- **Problem:** The channel list is `guild.text_channels` filtered by **the bot's** `read_message_history` (`:436`), or a user-chosen channel, and files are DMed to the invoker. Even with C-01 fixed, the design deliberately lets *anyone* use it in the main guild (`guild_gate.py:71-73`), and it never checks the invoker's own permissions.
- **Impact:** Bulk exfiltration of staff and private channels. Also:
  - unbounded memory, since the whole channel history is held in a list (`:145-213`)
  - blocking `psutil.cpu_percent(0.1)` on the event loop (`:68`)
  - `/exportstop` can be run by anyone
  - fire-and-forget task (`:468`)
- **Fix:** Restrict to owner/admin by default. Intersect with `channel.permissions_for(invoker)`. Stream to a temp file in chunks. Run psutil in a thread. Track job ownership.

**C-03 · Data/Ops · Fresh DB cannot be provisioned** **[verified]** (`database.py:186-197`; `migrations/017_timestamptz_conversion.sql:98-99`)

- **Problem:**
  - The duplicate-prefix guard rejects `005` + `005b`, so `RuntimeError` is raised and zero tables are created. The bot boots with `'migrations'` degraded.
  - Migration 017 alters `rss_cache.cached_at`, which 005b dropped. It only catches `undefined_table`, so it raises `UndefinedColumnError`, and in the real runner that blocks 018–021.
  - The deploy check greps `DB available=True`, which is still logged.
  - `tests/test_migrations.py` asserts the opposite rule to the runtime check.
- **Impact:** Disaster recovery, a new environment or a dev compose stack gets no schema. Every DB feature fails at runtime while CI is green.
- **Fix:**
  - Allow letter suffixes in the guard (or rename `005b` → `005_1`/`022`; the history-table key is the filename, so renaming needs a mapping row).
  - Make 017 tolerant (`EXCEPTION WHEN undefined_table OR undefined_column`).
  - Add a CI job that applies migrations to an ephemeral Postgres and runs a `prepare()` SQL smoke test.
  - Fail the deploy check on `'migrations'` degraded.

### High

| ID | Category | Location | Description & impact | Fix |
|---|---|---|---|---|
| H-01 | Discord/lifecycle | `rpg_manager.py:216-240`, `radio.py:109-122`, `status.py:86-92`, `massunban.py:197-199` | nextcord 3.2.0 has no `cog_load` **[verified]**. Background loops, radio auto-join and job resume never run. `async def cog_unload` is called un-awaited, so no cleanup happens (pytest warns). | Start loops in `__init__` (with `before_loop` → `wait_until_ready`) or a one-shot `on_ready` listener. Make `cog_unload` sync and schedule async cleanup. |
| H-02 | Logic/Safety | `massunban.py:524-554, 1413-1439`; `audit.py` | Date and moderator filters use `audit_logs` rows with actions `ban_executed/honeypot_ban/moderation_ban`, but **nothing writes them** (`audit_log` is never called). Bans without audit rows are always included regardless of date. Any "date-ranged" run unbans *all* bans. | Write audit rows on every ban path. Exclude unaudited bans when a date filter is set (or require an explicit `include_unaudited` flag). Show the true count in the confirmation step. |
| H-03 | Concurrency | `massunban.py:897-934, 1084-1141` | On 429 the loop doesn't stop. It keeps processing, marks the rate-limited user `failed` (never retried), and schedules `_scheduled_resume`, which starts a **second** `_execute_job` on the same pending items. Per-user log message per unban spams the log channel. | Break the loop on 429 and requeue the item. Use one worker per job behind an `asyncio.Lock`. Summarize logs in batches. |
| H-04 | Security (SSRF/DoS) | `feeds.py:112,204,311,402`; `rss_service.py:23-30` | No permission checks on `/feed add/remove/test` or `/resource latest`. Arbitrary URLs are fetched from the bot host (internal Docker network, `169.254.169.254`, localhost). The body is read unbounded (`response.text()`). Any member can also add/remove guild subscriptions and point posts at any channel. Failing URLs create permanent `alert_state_cache` keys and admin alerts carrying attacker-controlled text. | Require Manage Server for add/remove. Allow only http(s), resolve the host and block private/link-local ranges (re-check after redirects), cap response size, and rate-limit test/latest. |
| H-05 | Data/schema | `moderation.py:122,138,244,321`; `migrations/008:6-12` | `warnings.user_id/moderator_id` are `INTEGER REFERENCES users(id)`; the code inserts Discord snowflakes **[verified DataError]**. `/warn`, `/warnings` and `/clearwarnings` always fail; auto-escalation never fires. | New migration: `BIGINT` snowflake columns (drop the FKs or add `discord_id` columns) and backfill. Add a regression test with a real Postgres. |
| H-06 | Authorization | `moderation.py:105-205`; `rbac.py:153-170` | Warn/auto-ban has no hierarchy checks (target vs moderator top role, self, owner, bot, admins). STAFF is granted by role *name* (`staff`, `mod`…), so a mod can warn an admin to the ban threshold and the bot bans them. | Enforce `moderator.top_role > target.top_role`. Forbid self/owner/bot targets. Check `guild.me.top_role > target.top_role` before escalating. |
| H-07 | Multi-guild abuse | `moderation.py:56-82` (`STAFF_CHANNEL_ID`, `@everyone`); `notifications.py:88-157` (`PUBLIC_BOT_COMMANDS_CHANNEL_ID` fallback); `rbac.py:153-155` (guild owner → FOUNDER) | Any guild owner who adds the bot is FOUNDER, so `!panic` / `/admin panic` posts `@everyone` into the **main server's** staff channel. Staff in any unconfigured guild can `/admin pingsquad <text>` into the main server's public channel. | Remove cross-guild fallbacks: resolve channels only within `ctx.guild`. Scope FOUNDER to `FOUNDER_IDS` or the main guild owner. |
| H-08 | Rate limits/Moderation | `honeypot.py:394-421, 455-503` | Before banning, it scans **every** text channel's history (`limit=None`) and deletes messages one at a time (1 API call each), even for `timeout`/`role` actions. The spammer stays in the guild during the scan, concurrent triggers multiply the scans, and `ban(delete_message_seconds=…)` already purges server-side. No staff/admin exemption. | Act first (ban/timeout). Rely on `delete_message_seconds` for bans, or use `channel.purge(check=…, bulk=True)` for the others. Exempt members with Manage Messages. Validate `delete_days` to 0–7. |
| H-09 | Voice | `radio.py:29-32,174-183` | `options='-vn -ar 48000 -ac 2 -f opus'` is appended *after* nextcord's `-f s16le`, so FFmpeg writes Ogg/Opus, which `FFmpegPCMAudio` sends as PCM **[verified `OggS`]**. Result: noise. A single global `VoiceClient` is shared across guilds and `/radio move` can drag it to any guild (C-01). | Drop the options (or use `FFmpegOpusAudio.from_probe`). Make the voice client per guild. |
| H-10 | Logic | `mentorship.py:238,294,739`; `mentorship_service.py:62,85` | `m['mentee_id']` (int FK) is compared to `str(mentee.id)` (snowflake), so accept/complete always say "no request". If reached, `Record['status']=` raises `TypeError` after the DB update. `/mentor list` relies on completed rows, so it's always empty. | Compare via the `users` join on `discord_id`. Return `dict(record)`. |
| H-11 | Schema drift | `reviews.py:201,279,316,353`; `marketplace.py:700` | Ambiguous `id` breaks `/marketplace seller`. `user_id` int4 receives a snowflake (`helpful`). `bumped_at` doesn't exist (`/bump`) **[verified]**. `@rate_limit` reads `Interaction.author` → `AttributeError` (`review`, `/bump`). | Fix the queries. Rewrite `rate_limit` for Interactions. Add the SQL `prepare()` test from C-03. |
| H-12 | Multi-guild | `rss_service.py:101-131` | Dedupe key is `(feed_url, entry_id)` in a shared `rss_cache`. If guild A polls first, guild B subscribed to the same URL **never** receives entries. `feed_seen_items` (021) is unused. | Key dedupe by `(subscription_id, guid)`. |
| H-13 | Supply chain | `pyproject.toml`, `uv.lock` | aiohttp 3.14.1, pynacl 1.5.0, soupsieve 2.8.4 have published advisories. | Bump to ≥3.14.3, ≥1.6.2, ≥2.9.0. Add `pip-audit` to CI. |

### Medium

| ID | Category | Location | Description | Fix |
|---|---|---|---|---|
| M-01 | Reliability | `database.py:78-174` | Every `PostgresError` (constraint, syntax, type) becomes `DatabaseUnavailableError`, so users see "database unavailable" for bugs. `OSError` / `TimeoutError` / `ConnectionRefusedError` from the pool aren't caught or flagged. No `command_timeout`. Five copies of the same try/except. | One `_run()` helper. Map connection-class errors → unavailable and others → `QueryError`. Set pool `command_timeout` and `timeout`. |
| M-02 | Privacy | `database.py:89,110,…,168` | Logs full query args on error (user content, IDs; `execute_many` logs every row). | Log the arg count/types only. |
| M-03 | Broken feature | `moderation.py:373-386` | `/modstats` queries nonexistent `audit_logs.moderator_id/action_type` and passes an int for a varchar `guild_id` **[verified]**. | Rewrite against `warnings` + real audit rows. |
| M-04 | Broken feature | `stats.py:847` | `/stats server` queries nonexistent `user_activity_daily.channel_id` **[verified]**. | Drop the field or add the column. |
| M-05 | Abuse | `rate_limiter.py:67-103,199-221` | Rate limiter is ineffective (key mismatch), crashes on slash, its `check()` replies in-channel, the cleanup loop is never started, and it is only applied to 3 commands. | Rewrite; keyed by bucket; Interaction-aware. |
| M-06 | Audit | `audit.py` | Destructive actions (unban, honeypot bans, setup changes, reloads) leave no audit trail. | Call `audit_log.record` in each path. |
| M-07 | Discord | all slash commands | No `default_member_permissions` or `dm_permission`. All 110 commands are visible to everyone and DM-invocable; several assume `interaction.guild` (`setup.py:77,93`, `networking.py:466`) → AttributeError. | Set per command or group. |
| M-08 | Discord limits | `moderation.py:202,265-275`; `info.py:55-66`; `networking.py:55,512-528`; `marketplace.py:63,203` | Unbounded user text in embed descriptions/fields (4096/1024 limits) → `HTTPException`. The 25-row warnings list can exceed 4096. | Truncate; `max_length` on SlashOptions; paginate. |
| M-09 | Data | `marketplace.py:118`, `portfolio_manager.py:68` | IDs from second-resolution timestamps → PK collisions under concurrency. | Use DB sequences or `secrets.token_hex`. |
| M-10 | UX/Spam | `marketplace_enhanced.py:552-633` | `check_price_drops` DMs every seller with a listing over 30 days old every 6 h with no dedupe, and points to broken `/bump` and nonexistent `/market bump`. `check_expiring_listings` has no `before_loop`, so its first run happens before the DB connects. Expiry ignores bumps; `/browse` shows expired listings. | Dedupe with a `notified_at` column. Fix copy. Make the expiry rule consistent. |
| M-11 | UX | `networking.py:16-41, 109-178` | Connect picker shows only the first 25 guild members (no search or user option). Accept/Decline in DM can't notify the requester (`interaction.guild` is None). Views are not persistent. | Use a `user` option or `UserSelect`. Fetch the requester via `bot.get_user`. Make persistent views with `custom_id`. |
| M-12 | Reliability | `rpg_manager.py:974,1071,1084,1111,709,368-372,634` | Activity roles and inactivity use `bot.guilds[0]` (an arbitrary guild). `alert_embed` isn't awaited and `safe_send(TextChannel)` silently does nothing, so alerts are dropped while users are marked notified. The live role is never removed. Coding minutes go into `total_gaming_minutes`. Voice join/leave branches are dead (`before is None`). | Fix each; use `MAIN_GUILD_ID` / guild_settings. |
| M-13 | Broken feature | `honeypot.py:842,900` | enable/disable/edit write nonexistent `honeypots.updated_by` **[verified]**. | Migration or remove the column from the query. |
| M-14 | Privacy/Multi-guild | `rpg_manager.py:449-464`; `stats.py:109-250`; `user_activity_details` | XP, leaderboards and `/most` stats are global. Usernames and activity from guild A show in guild B; presence-derived Spotify/game data is stored indefinitely with no opt-out. `on_presence_update` auto-appends stream URLs to user profiles (`:703-707`). | Per-guild scoping, retention policy, opt-out. |
| M-15 | Correctness | `notifications.py:41-80,104-112` | Squad "ping" puts the role mention inside an embed, so no notification fires. `self.bot.main_guild` doesn't exist. The minute-match loop can skip or double-fire. | Put the mention in `content` with explicit `AllowedMentions(roles=[role])`. Use `tasks.loop(time=…)`. |
| M-16 | Incomplete | `moderation.py:36-82` | "Lockdown" toggles an in-memory flag nothing reads; it isn't persisted and does nothing to channel permissions. | Implement it (overwrite `send_messages` on @everyone) or rename to an alert. |
| M-17 | Broken UX | `setup.py:214-336` | Interactive setup never applies anything. | Use `ChannelSelect` / `RoleSelect` components. |
| M-18 | Abuse | `mentorship.py:393-548` | `/mentor apply` inserts a mentor=mentee "active" match (no unique key). `/mentor end` grants 50 points to the same user twice; repeatable. The weekly check-in DMs about the self-match. | Separate mentor registry table; unique constraints; award only on `successful`. |
| M-19 | Security (web) | `directus_sync.py:55-84` | Re-hosts any attachment type (HTML/SVG) into public Directus assets → possible stored XSS on the web frontend. ❓ Depends on Directus serving config. | Restrict to `image/png|jpeg|webp|gif`, verify magic bytes, cap size when there's no Content-Length. |
| M-20 | Info leak | `health.py:119-121`; `massunban.py:1319-1362` | Public `/health` shows raw DB error text. `/massunban status <id>` isn't guild-scoped. | Staff-only detail; filter by `guild_id`. |
| M-21 | Quality/CI | `.github/workflows/`, `.pre-commit-config.yaml` | No CI for lint/type/test/audit; only deploy. mypy reports **27 errors** (`card_generator.py`, `rpg_manager.py:82-121,1526`, `setup.py`, `welcome.py`, `marketplace.py:756-782`), contradicting AGENTS.md. Pre-commit pins old ruff/mypy and lacks Pillow/psutil stubs. | Add a CI workflow; fix errors; align pins. |
| M-22 | Async hygiene | `massunban.py:199,222,1133`; `export.py:468`; `radio.py:201`; `honeypot.py` | Fire-and-forget tasks without references (can be GC'd; exceptions lost). | Keep a task set, as in `rss_service.py:16`. |

### Low

| ID | Location | Description |
|---|---|---|
| L-01 | `runtime_state.py:41` | `startup_time` is set at import (known). |
| L-02 | `massunban.py:1069`, `rpg_manager.py:388`, `guild_settings_service.py:126-141` | Column names f-string-interpolated (whitelisted, but breaks the convention). |
| L-03 | `config.py:30-33,101,127,135`; `019_*.sql:13` | Hardcoded guild/channel/user IDs. `MAIN_GUILD_ID` ignores the env var that `.env.example` documents. |
| L-04 | `config.py:56`; `docker-compose.dev.yml` | Default DB password `example`; dev Postgres published on 0.0.0.0:5432. |
| L-05 | `Dockerfile` | Runs as root; gcc/git/python3-dev in the final image; no multi-stage; `pip install .` builds an empty wheel (no `[build-system]`, only `pyproject.toml` copied). Deploy runs `compose down` before build, causing downtime. |
| L-06 | `requirements.txt`, `.env.example` | Stale requirements; dead `RADIO_STREAM_URL` (YouTube) and `RADIO_REFRESH_INTERVAL`. |
| L-07 | `footer.py` | Markdown links don't render in footers; user IDs printed in every footer; a DB read/write per embed. |
| L-08 | `setup.py:49`, `export.py:95,159-164` | `&{role_id}` is not a mention; `name#0` discriminators; logger calls missing args. |
| L-09 | `status.py:46` | Presence change every 10 s (once loops actually start) — use ≥60 s. |
| L-10 | `welcome.py:37,83` | `template.format()` KeyError on bad templates; new `ClientSession` per download instead of `utils.http`. |
| L-11 | various | Dead code: `CancelJobView`, `update_featured_listings`, `mp_search_autocomplete`, quiz stub, empty cog dirs, unused RBAC perms. |
| L-12 | `honeypot.py:26`, `rpg_manager.py:192-204`, `admin_notifier`/`alert_state_cache` | Unbounded in-memory dicts (cooldowns, voice joins, per-URL alert keys). |
| L-13 | `honeypot_events`, `user_activity_log` | No retention; message previews (PII) kept forever. One `user_activity_log` row per XP event plus 6–8 sequential queries per message (no transaction, read-modify-write on level). |
| L-14 | `app.py:250-265` | Shutdown closes the HTTP session but not the DB pool; no `on_guild_remove` cleanup. |
| L-15 | intents | All three privileged intents are used (presences for activity tracking). Verification is required past 100 guilds. Presence intent drives very high event volume. |
| L-16 | No global `AllowedMentions` | Most user text is in embeds (no pings), but there's no defence in depth. Set `AllowedMentions(everyone=False, roles=False, users=True)` on the bot. |

---

## 5. Modernization gap analysis

| Area | Current | Target |
|---|---|---|
| Authz | Two decorator families; one silently ineffective on slash | Single dual-mode guard + `default_member_permissions` + test that asserts checks exist |
| Command lifecycle | `cog_load` assumed (discord.py idiom) | nextcord-native: loops started in `__init__` with `before_loop`, or an `on_ready` setup hook |
| Config | Module-level `os.getenv` + hardcoded IDs; no validation | Typed settings (pydantic-settings or dataclass) validated at startup, fail fast; IDs via env/guild_settings |
| DB | Hand-rolled wrapper; schema drift vs code; numeric-prefix runner | Fix runner; schema CI (migrate + `prepare()` all SQL); transactions for multi-step writes; retention jobs |
| Errors | Catch-all wrappers; query errors masked as outages | Error taxonomy (Unavailable / Query / Validation / Permission); structured logs with command + guild context |
| Logging | Text format, rotating file | Keep text for humans + optional JSON; correlation by interaction id; no args in DB error logs |
| Tests | 126 unit tests on utilities; 0 on commands/SQL | Command-handler tests with mocked Interaction; Postgres integration job; coverage gate (~60 % to start) |
| CI/CD | Deploy-only workflow; deploy health check ignores migrations | `ci.yml`: ruff, mypy, pytest, migrations-on-Postgres, pip-audit, docker build. Deploy only after CI passes. Dependabot/Renovate |
| Docker | Single stage, root, build tools in image | Multi-stage (uv), non-root user, slim runtime with ffmpeg + libopus only, healthcheck |
| Docs | README (22 KB) + AGENTS.md; no CHANGELOG/CONTRIBUTING | README with intents/permissions/env table; CHANGELOG; CONTRIBUTING; MIGRATION_NOTES |

---

## 6. Proposed remediation roadmap

Each milestone is a set of small commits on `audit/modernization` (Conventional Commits, referencing audit IDs). Effort: S < ½ day, M ≈ 1–2 days, L > 2 days.

| # | Milestone | Items | Effort | Breaking? |
|---|---|---|---|---|
| 0 | **Safety net** | CI workflow (ruff, mypy, pytest, pip-audit); Postgres-backed migration + SQL-prepare test; slash-checks assertion test; fix 27 mypy errors | M | No |
| 1 | **Stop the bleeding** | C-01 (guards + `default_member_permissions` + `dm_permission=False`), C-02 (export authz, streaming), H-04 (feed authz + SSRF guard), H-07 (no cross-guild fallbacks, FOUNDER scope), `/setupleaderboard` scoping | M | **Yes:** privileged commands become hidden or denied for non-admins; `/exportchat` restricted; FOUNDER no longer granted to every guild owner |
| 2 | **Schema & migrations** | C-03 (runner + 017), H-05 (warnings columns), M-13, H-11/M-03/M-04 query fixes, H-12 per-subscription dedupe | M | **DB migration** (new 022+); needs prod schema confirmation first (Q1) |
| 3 | **Lifecycle & destructive ops** | H-01 (start loops properly), H-02/H-03 (massunban filters + single worker + audit rows), H-06 (hierarchy), H-08 (honeypot ordering/exemptions), M-06 audit trail, M-22 task refs | M–L | Behaviour change: massunban stops including unaudited bans when filtered (Q3) |
| 4 | **Repair broken features** | H-09 radio, H-10 mentorship, H-11 reviews/bump, M-10, M-11, M-12, M-15, M-17, M-18 | L | Minor UX changes |
| 5 | **Medium/Low hardening** | M-01, M-02, M-05, M-07, M-08, M-09, M-14 (needs decision), M-16, M-19, M-20, L-* | M | M-14 changes leaderboard semantics (Q4) |
| 6 | **Modernization (Phase 5)** | Typed config, error taxonomy, Docker multi-stage, deps bump (H-13), docs (README, CHANGELOG, CONTRIBUTING, MIGRATION_NOTES), dead-code removal | L | Env var additions (documented) |

Not built without approval (🔴): marketplace transactions/"sold" flow, offer accept/reject, watchlist price alerts, quiz, workshops, welcome-template config command. Proposed designs will follow on request.

---

## 7. Open questions

1. **Production schema.** The migration runner has been refusing to run since `005b` was added. How was the production DB created and migrated (manually, an older runner)? Can I get a `pg_dump --schema-only` (no data) so fixes target the real schema? Otherwise "verified" schema bugs (H-05, M-03, M-04, M-13, H-11) may differ in prod.
2. **Multi-guild intent.** Is the bot meant to serve many guilds, or VEKA plus a few owner-only external servers? This decides scoping for XP/leaderboards/marketplace/profiles (global vs per-guild) and whether hardcoded main-guild fallbacks stay.
3. **Mass unban semantics.** When a date range is given, should bans with no audit record be **excluded** (safe default) or included?
4. **Honeypot exemptions.** Should members with Manage Messages / staff roles be exempt from honeypot punishment?
5. **FOUNDER role.** Should "guild owner → FOUNDER" apply only to the main guild? It currently grants founder powers to the owner of any server that adds the bot.
6. **`/exportchat`.** Keep it at all? If yes: owner-only everywhere, or admins limited to channels they can read?
7. **Lockdown.** Should `/admin panic` actually lock channels (permission overwrites), or just alert?
8. **Presence data.** Is storing Spotify/game/coding activity per user acceptable for your community and its privacy expectations? Is retention or opt-out needed?
9. **Radio.** One global stream (main guild only) or per-guild?
10. **Deploy check.** OK to fail the deploy when `'migrations'` is degraded? With today's runner that would immediately fail production until C-03 is fixed.
11. **Commit policy.** Your standing rule is "commit only when told". For Phase 4, do you want me to commit per logical unit (as this brief asks) without asking each time, or stage changes for you to commit?

---

## 8. Remediation log (Phases 4–5)

Status: ✅ fixed · 🟡 partly fixed (remainder listed) · ⏸ open (needs a decision or is out of scope) · ⛔ blocked.
Tests are under `tests/`; probes are scripts run against a throwaway PostgreSQL 18 and real FFmpeg.

### Critical and High

| ID | Status | What changed | Verified by |
|---|---|---|---|
| C-01 | ✅ | `permission_guard()` in `safety.py` enforces checks on prefix **and** slash (callback wrapper / `application_checks`); `admin_only`, `staff_only`, guild gates, new `manage_guild_only`, `bot_operator_only`. `default_member_permissions` on massunban/exportchat/setupleaderboard; `contexts=[guild]` on guild-only groups. | `test_permissions.py` walks all 110 slash commands and asserts the privileged ones are guarded; behavioural deny/allow tests |
| C-02 | 🟡 | `/exportchat` is admin + owner-gated, exports only channels the bot **and** invoker can read, `/exportstop` is limited to the starter or an admin, task is tracked, psutil is non-blocking. **Open:** history is still buffered in memory per channel. | Code review |
| C-03 | ✅ | Full-prefix duplicate check (`005` ≠ `005b`); `LEGACY_MIGRATION_NAMES` so prod's old `005_guild_and_rss_schema.sql` record isn't re-run; 005b only drops an incompatible `rss_cache`; 017 tolerates `undefined_column`; ready line reports `migrations=`; deploy warns. | `test_schema_postgres.py` (fresh DB, idempotent re-run); upgrade probe (legacy name, data kept) |
| H-01 | ✅ | `cog_ready()` hooks called from `on_ready` after the DB is up and after reload (`src/core/lifecycle.py`); `cog_unload` made sync. | `test_lifecycle.py` (no `cog_load`, no async `cog_unload`, hook runs once) |
| H-02 | ✅ | `on_member_ban` writes `ban_executed` audit rows; `match_bans()` excludes unaudited bans unless `include_unaudited`. | `test_massunban.py` |
| H-03 | ✅ | One worker per job (lock); 429 leaves item pending and stops the worker; one scheduled resume; per-user logs only for failures; guild-local log channel. | Code review |
| H-04 | ✅ | Feed add/remove/test require Manage Server; all RSS fetches go through `fetch_public_url` (scheme check, `PublicOnlyResolver`, manual redirects re-validated, 2 MB cap). **Residual:** `/resource latest` remains public (SSRF-guarded); per-URL alert keys are unbounded (L-12). | `test_http_safety.py`; live: loopback hostname and redirect to 127.0.0.1 blocked, public feed fetched |
| H-05 | ✅ | Migration 022: snowflake `BIGINT` columns, legacy rows mapped. | Postgres test inserts snowflakes; upgrade probe |
| H-06 | ✅ | `_hierarchy_refusal()` (self, bot, owner, admins, top role); escalation only if the bot outranks the target. | Code review |
| H-07 | ✅ | FOUNDER-by-ownership only in the main guild; panic, pingsquad, bump reminder, massunban and inactivity logs resolve channels inside the guild; `/setupleaderboard` main-guild only; `MAIN_GUILD_ID` honours env. | Code review |
| H-08 | ✅ | Act first; server-side purge for bans; bounded background bulk purge for timeout/role; staff/owner/above-bot exempt; inputs clamped. | `test_honeypot.py` |
| H-09 | ✅ | FFmpeg options `-vn` only; restart callback scheduled thread-safely. **Unchanged:** a single global voice client (Q9). | Probe with nextcord's exact argv: 2 s → 384,000 bytes s16le |
| H-10 | ✅ | Compare via joined `discord_id`; services return `dict`s. | SQL prepare test |
| H-11 | ✅ | `/bump` uses `last_bumped_at`; qualified columns; helpful vote maps to `users.id`; `rate_limit` is Interaction-aware. | SQL prepare test; `test_rate_limiter.py` |
| H-12 | ✅ | Migration 024 plus per-subscription dedupe (`subscription_id`). | Postgres test with two guilds on one URL |
| H-13 | 🟡⛔ | aiohttp 3.14.3, soupsieve 2.10. **Blocked:** PyNaCl 1.5.0, because nextcord 3.2.0 (latest) pins `<1.6`. The advisory's code path (`crypto_core_ed25519_is_valid_point`) isn't used by nextcord voice (`nacl.secret` only); it is ignored in CI with a comment. | `pip-audit`: 10 → 2 (both PyNaCl) |

### Medium and Low

| ID | Status | Notes |
|---|---|---|
| M-01 | ✅ | `Database._run`; `DatabaseQueryError` (SQL error, DB stays available) vs `DatabaseUnavailableError` (connection/OSError/timeout); pool `command_timeout`. `test_database_wrapper.py` |
| M-02 | ✅ | Only argument types are logged. |
| M-03 | ✅ | `/modstats` reads `warnings` + real `audit_logs` actions. |
| M-04 | ✅ | `/stats server` shows the most active member (no per-channel data exists). |
| M-05 | ✅ | Rate limiter rewritten: atomic `acquire`, same bucket checked and consumed, inline stale purge. **Open:** still applied to only a few commands. |
| M-06 | 🟡 | Bans (all paths), auto-mute and auto-ban are audited. **Open:** setup changes, reloads and unbans (these are in `massunban_job_items`). |
| M-07 | 🟡 | Guild-only contexts on the groups that assume a guild; default perms on three commands. Others unchanged. |
| M-08 | 🟡 | Warnings list fits 4096; squad message capped. **Open:** other free-text embeds. |
| M-09 | ✅ | Random suffix on listing and portfolio IDs. |
| M-10 | ✅ | One expiry warning per age cycle (migration 026); bump-aware expiry; bump un-expires; browse hides expired; `before_loop` on every task. |
| M-11 | 🟡 | Native searchable `UserSelect`; DM accept/decline notifies the requester. **Open:** buttons are not persistent across restarts. |
| M-12 | ✅ | Main guild instead of `guilds[0]`; awaited `alert_embed`; real `channel.send`; live role removed; voice join/leave detected; DM cap. **Unchanged:** coding minutes are stored in the gaming column. |
| M-13 | ✅ | Migration 023. |
| M-14 | ⏸ | Global XP / presence retention needs a product decision (Q2, Q8). |
| M-15 | ✅ | Role mention in `content` with explicit `AllowedMentions`; `tasks.loop(time=…)`. |
| M-16 | ⏸ | Lockdown remains an alert (Q7), now per guild. |
| M-17 | ✅ | Channel/Role selects + Reset. |
| M-18 | ✅ | Registrations separated (migration 025); XP only for successful real matches. |
| M-19 | ✅ | Discord CDN hosts only; image MIME + magic bytes; streamed 8 MB cap. |
| M-20 | ✅ | Raw DB error staff-only; massunban status/cancel guild-scoped. |
| M-21 | ✅ | `ci.yml` (ruff, format, mypy, pytest + Postgres, pip-audit, docker build); mypy 27 → 0; pre-commit pins aligned. |
| M-22 | ✅ | `spawn()` everywhere; thread-safe radio restart. |
| L-01 | ✅ | `startup_time` set in `on_ready`. |
| L-03 | 🟡 | `MAIN_GUILD_ID` env honoured; other hardcoded IDs remain as fallbacks. |
| L-05 | 🟡 | Multi-stage build from `uv.lock`, no build tools in runtime. **Open:** still root (bind-mounted logs); deploy still does `down` before `up`. |
| L-06 | 🟡 | `requirements.txt` regenerated from the lock. **Open:** dead radio vars in `.env.example`. |
| L-08 | 🟡 | Role mention format fixed in `/setup`. |
| L-09 | ✅ | Status rotation every 60 s. |
| L-10 | ✅ | Safe placeholder substitution; shared HTTP session. |
| L-11 | 🟡 | Marketplace autocomplete wired up. Other dead code is still present. |
| L-14 | 🟡 | DB pool closed on shutdown. **Open:** no `on_guild_remove` cleanup. |
| L-16 | ✅ | Bot-wide `AllowedMentions(everyone=False, roles=False)`; explicit opt-in where pings are intended. |
| L-02, L-04, L-07, L-12, L-13, L-15 | ⏸ | Not addressed in this pass. |

### New defects found and fixed during remediation

| ID | Where | Defect | Fix |
|---|---|---|---|
| N-01 | `014_honeypot_schema.sql` | CHECK constraint rejected the `'log'` action that `/honeypot create` offers | Migration 023 |
| N-02 | `radio.py` `_on_play_end` | `asyncio.ensure_future` called from the voice player thread (no loop there), so stream restarts never ran | `run_coroutine_threadsafe(…, bot.loop)` |
| N-03 | `rpg_manager.py` leaderboard | `followup.send()` without `wait=True` returns `None`, so pagination buttons were never disabled on timeout | `wait=True` |
| N-04 | `rpg_manager.py` season archive | Hourly loop with a 5-minute window missed most months; for every guild it posted into the main guild's fallback channel | Daily `time=` loop; main guild only; guild-local channel |
| N-05 | Migration rename `005` → `005b` | Once the runner worked, prod would try to re-apply 005b (non-idempotent index, then a block on every later migration) | `LEGACY_MIGRATION_NAMES` + idempotent 005b |
| N-06 | `honeypot.py` (new code) | `TextChannel.purge(reason=…)` isn't a nextcord parameter (caught by mypy before shipping) | Removed |
| N-07 | `!setup` prefix group | Usable in DMs, where it crashed on `ctx.guild` | `@commands.guild_only()` |
| N-08 | `card_generator.py` | Font fallback `load_default()` ignored sizes (tiny text without system fonts, e.g. in the Docker image) | `load_default(size=…)` |
| N-09 | Honeypot alert | With the new bot-wide mention default, the notification-role ping would have been silenced | Explicit `allowed_mentions` |

### Verification summary

| Check | At audit | Now |
|---|---|---|
| pytest | 126 passed, 0 handler/SQL tests | **188 passed** (181 unit + 7 PostgreSQL tests that run when `VEKA_TEST_DATABASE_URL` is set) |
| ruff check / format | clean | clean |
| mypy | 27 errors | **0** |
| pip-audit (runtime) | 10 vulns in 3 packages | 2 (PyNaCl, accepted, see H-13) |
| Fresh DB via real runner | 0 tables | full schema; re-run is a no-op |
| Static SQL vs schema | 7 failing | 0 |
| Upgrade from legacy `005_` record | would re-run 005b | 005b recorded as applied, data kept |

### Follow-up diff review (2026-10-05)

- Fixed feed delivery acknowledgements: failed sends, missing channels, and entries beyond the per-poll cap no longer consume dedupe state. Polling resolves channels within the subscription's guild.
- Made mentorship completion and both XP awards one atomic SQL statement; concurrent completion is covered against real PostgreSQL.
- Export cancellation is guild-scoped; failure/cancellation always releases state, and unload cancels the export task.
- All background loops now start from `cog_ready`, avoiding pre-initialization queries and task leaks during sync import tests. Mass-unban workers and delayed resumes are cancelled on unload.
- Added explicit pool-acquisition timeout, preserved honeypot zero-day deletion, and prevented double-counted bans in modstats.
- Made listing expiry/warning selection atomic, restricted Directus image downloads to HTTPS without redirects, and validated the WebP container marker.
- Removed unused featured-cache loop, cancellation view, and obsolete rate-limiter cleanup task. Lockdown messages now explicitly describe alert-only behavior.
- Verified: 188 tests passed including PostgreSQL integration; ruff, mypy, pre-commit, Docker build passed; dependency audit reports no unignored vulnerabilities (two existing PyNaCl exceptions remain).

### Still needs a live smoke test after deploy

These can't be exercised offline:

- Radio audio in a voice channel
- Activity-role add/remove
- Inactivity DMs (capped)
- The auto-leaderboard message
- `/connect` user picker and DM buttons
- `/setup interactive` pickers
- Honeypot actions on a test account
- `/massunban preview` with `include_unaudited`

### Open questions still awaiting answers

Q1 (production schema dump), Q2/Q8 (global vs per-guild data, presence retention), Q7 (real lockdown), Q9 (per-guild radio). Defaults applied for Q3–Q6 and Q10–Q11 are listed in `MIGRATION_NOTES.md`.
