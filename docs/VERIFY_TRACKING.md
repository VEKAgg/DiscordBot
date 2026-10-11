# Verifying activity tracking

How tracking works now: messages and commands are counted as they happen (message XP has a 10 s
per-user cooldown). Voice and presence minutes are **sampled once a minute** from Discord's live
state, so a restart loses at most a minute. Totals record real minutes; only XP is capped
(60 continuous minutes per kind). Games, coding apps and streaming are tracked only for members who
ran `/privacy optin`. Music/Spotify is not tracked.

Voice rules: the AFK channel and deafened members (self or server) count nothing; a member alone in
a channel counts minutes but earns no XP.

Most of this is covered by automated tests (`tests/test_tracking.py`, and the PostgreSQL tests in
`tests/test_schema_postgres.py`). This script checks the live bot with a test account.

## Setup

Use a test Discord account (`TEST_ID` below) in a server where the bot runs (`GUILD_ID`), and a
`psql` session on the bot's database. Take a baseline before each step:

```sql
\set uid '''TEST_ID'''
\set gid GUILD_ID

SELECT total_messages, total_commands, total_voice_minutes, total_gaming_minutes,
       total_coding_minutes, total_streaming_minutes, points, level, current_streak, presence_opt_in
FROM users WHERE discord_id = :uid;

SELECT activity_date, messages, commands, voice_minutes, gaming_minutes, coding_minutes, xp_earned
FROM user_activity_daily
WHERE user_id = :uid::bigint AND guild_id = :gid AND activity_date = (NOW() AT TIME ZONE 'UTC')::date;
```

## 1. Messages — expect `total_messages` +2

Send 5 messages within 10 seconds, wait 15 seconds, send 1 more. Re-run the baseline queries:
`total_messages` and today's `messages` are each **+2**; `points` +2 (more with a streak or role bonus).

## 2. Commands — expect `total_commands` +1

Run `/level`. `total_commands` and today's `commands` are **+1**. (Before this fix command XP was
never counted.) `!help` counts too.

## 3. Voice — expect +3 minutes

Join a voice channel **with a second (non-bot) account**, stay ~3 minutes, leave.
`total_voice_minutes` and today's `voice_minutes` are **+3** (±1: the bot samples once a minute).
Alone in a channel: minutes still count, XP doesn't. Deafened or in the AFK channel: nothing.

Long session: stay over an hour. Minutes keep growing past 60; XP from that session stops at 60.

```sql
SELECT total_voice_minutes, points FROM users WHERE discord_id = :uid;
```

## 4. Games — opted-in only, counted once

1. Without opting in, play a game for 2 minutes: nothing changes in `total_gaming_minutes` or
   `user_activity_details`.
2. Run `/privacy optin`, play for 2 minutes:

```sql
SELECT activity_type, activity_name, duration_minutes
FROM user_activity_details WHERE user_id = :uid ORDER BY last_seen DESC LIMIT 5;
SELECT total_gaming_minutes FROM users WHERE discord_id = :uid;
```

The game row is about **2** minutes and `total_gaming_minutes` is **+2** (not +4: the double count
is gone). A coding app (e.g. "Visual Studio Code") goes to `total_coding_minutes` / `coding`, not gaming.

## 5. Restart mid-session — still counted

While in voice (with company) or playing (opted in), restart the bot
(`docker compose -f docker-compose.dev.yml restart bot`). Stay 3 more minutes. The minutes keep
increasing after the restart without rejoining; at most ~1 minute is lost.

## 6. Commands match the SQL

| Command | Source | Check |
|---|---|---|
| `/rank`, `/level` | `users.points` (global, all servers) | `SELECT points, level FROM users WHERE discord_id = :uid;` |
| `/activity stats` | `users.total_*` (global) | baseline query above |
| `/activity summary` | `user_activity_daily`, this server, last 7 UTC days | `SELECT activity_date, messages, voice_minutes FROM user_activity_daily WHERE user_id = :uid::bigint AND guild_id = :gid AND activity_date >= (NOW() AT TIME ZONE 'UTC')::date - 6 ORDER BY 1;` |
| `/leaderboard show period:alltime` | `users` (global) | `SELECT discord_id, points FROM users ORDER BY points DESC LIMIT 10;` |
| `/leaderboard show category:chat period:week` | this server, last 7 days | `SELECT user_id, SUM(messages) FROM user_activity_daily WHERE guild_id = :gid AND activity_date >= (NOW() AT TIME ZONE 'UTC')::date - 6 GROUP BY 1 ORDER BY 2 DESC LIMIT 10;` |
| `/leaderboard season` | this server, calendar month (UTC) | same with `activity_date >= date_trunc('month', NOW() AT TIME ZONE 'UTC')::date` and `SUM(xp_earned)` |
| `/serverstats`, `/stats demographics` | this server's rollups | `SELECT COUNT(DISTINCT user_id) FROM user_activity_daily WHERE guild_id = :gid AND activity_date >= (NOW() AT TIME ZONE 'UTC')::date - 6;` |
| `/most played users` | opted-in members only | `SELECT discord_id, total_gaming_minutes FROM users WHERE presence_opt_in ORDER BY 2 DESC LIMIT 10;` |

Per-server rollups only exist from when they started being written; all-time per-server figures
can be lower than the global totals.

## 7. Privacy

`/privacy optout` → presence tracking stops at the next minute. `/privacy delete` → confirm; then:

```sql
SELECT points, total_gaming_minutes, presence_opt_in FROM users WHERE discord_id = :uid;  -- 0, 0, false
SELECT COUNT(*) FROM user_activity_daily WHERE user_id = :uid::bigint;                     -- 0
SELECT COUNT(*) FROM user_activity_details WHERE user_id = :uid;                           -- 0
```
