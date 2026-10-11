# Deploying the dashboard API

The dashboard API (`src/api/`) runs as a second container, `veka-api`, next to the bot. It is deployed by the same `Deploy` workflow on every push to `main`. It uses the bot's database and never connects to the Discord gateway.

## How it is wired

```
Admin's browser ──> website (veka) ──server-side──> https://api.veka.gg ──> Traefik ──> <bot host>:8080 ──> veka-api
                                                                                                │
                                                                                     PostgreSQL (same DB as the bot)
```

- Users never type a password into the API. The website sends the admin's **Discord OAuth token** (scopes `identify guilds`), and the API checks it with Discord.
- Every server page needs **Manage Server** in that server, and the bot must be in it.
- In production `/v1/docs` and `/v1/openapi.json` are switched off (set `API_DOCS=1` to turn them back on).

## 1. GitHub (repository → Settings → Secrets and variables → Actions, `production` environment or repo level)

### Secrets

| Name | Required | Value |
|---|---|---|
| `API_SERVICE_TOKEN` | Optional now | Shared secret for server-to-server calls from the website. Generate with `openssl rand -hex 32`. Only needed once the website uses service calls; leave unset until then. |

The existing `DATABASE_URL` and `DISCORD_TOKEN` secrets are reused; nothing else is needed.

### Variables

| Name | Default | Set to |
|---|---|---|
| `API_BIND_ADDRESS` | `127.0.0.1` | The **LAN IP of the machine the bot runs on** (the self-hosted runner), so Traefik can reach it. Keep `127.0.0.1` only if Traefik runs on the same host *outside* Docker. |
| `API_PUBLISHED_PORT` | `8080` | Change only if 8080 is taken on that machine. |
| `API_TRUSTED_PROXIES` | (empty) | Traefik's address as the API sees it, plus Cloudflare Tunnel's if the API is public. For the homelab: `192.168.1.97,172.16.0.0/12`. Used only for per-IP rate limiting. |
| `API_CORS_ORIGINS` | (empty) | Leave empty while the website calls the API from its server. Set to `https://veka.gg` only if browsers will call the API directly. |
| `API_RATE_LIMIT` | `120` | Requests per minute per signed-in user. |
| `API_PREAUTH_LIMIT` | `60` | Requests per minute per IP before sign-in. |

## 2. Traefik (homelab `traefik/config/dynamic.yml`, file provider, `watch: true`, no restart needed)

Add a router and a service. Replace `BOT_HOST_IP` with the value of `API_BIND_ADDRESS`.

```yaml
http:
  routers:
    veka-api:
      rule: "Host(`api.veka.gg`)"
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt
      service: veka-api
      middlewares:
        - secure-headers
        - internal-only   # remove only when the website runs outside the LAN/tailnet (see step 3)

  services:
    veka-api:
      loadBalancer:
        servers:
          - url: "http://BOT_HOST_IP:8080"
        healthCheck:
          path: /v1/ready   # 503 while the API can't reach the database
          interval: 30s
```

`*.veka.gg` already resolves to Traefik and the wildcard certificate covers `api.veka.gg`, so no DNS change is needed for LAN/tailnet access.

**Recommended for now: keep `internal-only`.** The dashboard is only for server admins, and the website calls the API from its own server, so the API does not need to be on the public internet.

## 3. Only if the website runs outside the LAN/tailnet: Cloudflare Tunnel

- Zero Trust → Tunnels → your tunnel → Public hostname: `api.veka.gg` → `https://192.168.1.97:443`.
- Under *Additional application settings → TLS*: set **Origin Server Name** to `api.veka.gg` and leave **No TLS Verify off**. Traefik serves the valid `*.veka.gg` certificate, so verification works, and this hop carries admins' Discord login tokens (unlike the other services, don't skip verification here).
- Remove `internal-only` from the router above.
- Make sure `API_TRUSTED_PROXIES` covers Traefik and the cloudflared container (`172.16.0.0/12` does for Docker networks).

## 4. Firewall on the bot host

If `API_BIND_ADDRESS` is the LAN IP, port 8080 is reachable from the LAN. Optionally restrict it to Traefik's host, e.g. `ufw allow from 192.168.1.97 to any port 8080 proto tcp`.

## 5. Check after deploy

- The `Deploy` run has a **Dashboard API health check** step (`/v1/ready`); it fails the run if the API can't reach the database within 60 s (the bot keeps running).
- On the bot host: `docker ps` shows `veka-api` as `healthy` (container check uses `/v1/ready`); `docker logs veka-api`.
- From the LAN/tailnet: `curl https://api.veka.gg/v1/ready` → `{"ready":true}`; `curl https://api.veka.gg/v1/health` → `{"api":"ok","db":"ok","bot":{"online":true,...}}`. `bot.online` becomes `true` within a minute of the bot starting.
- A signed-in check: `curl -H "Authorization: Bearer <your Discord OAuth token>" https://api.veka.gg/v1/me/guilds` lists the servers where you have Manage Server and the bot is present.

## Rolling back

Remove the `api` service from `docker-compose.yml` (or run `docker stop veka-api` on the host). The bot does not depend on the API.
