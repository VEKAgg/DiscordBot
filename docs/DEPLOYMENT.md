# Deployment

The runtime stack and complete operator runbook live in
[homelab-priv/stacks/veka-platform](https://github.com/VEKAgg/homelab-priv/tree/main/stacks/veka-platform).
In the multi-repo checkout: `../homelab-priv/stacks/veka-platform/README.md`.

## Workflows

- `ci.yml`: PR, manual and reusable checks; hosted runners, disposable fixtures, no runtime secrets.
- `release.yml`: `dev` / `main` pushes and manual releases; CI → publish → deploy.
- `build-image.yml`: reusable GHCR publisher; SHA tags, immutable digest output, Buildx cache, SBOM/provenance.
- `deploy.yml`: reusable deployment on apps; no checkout/build, calls installed deployment tooling.
- `rollback.yml`: manual known-good image rollback after confirming current schema compatibility.

Repository Actions variables (not secrets):
`STAGING_DEPLOY_ENABLED`, `PRODUCTION_DEPLOY_ENABLED`, `PRODUCTION_AUTO_DEPLOY`.
All start `false`. Enable staging after bootstrap; production only at coordinated cutover.
Production is manual by default: dispatch **Release** on `main`; set `PRODUCTION_AUTO_DEPLOY=true`
only if every successful main push should deploy.

VEKAgg's Free/private setup cannot use native GitHub Environments. No manual GitHub secret is required:
publishing/pulling uses the automatic job-scoped `GITHUB_TOKEN`. Private GHCR packages must grant
this repository Actions access. Runtime credentials belong in mode-600 server files under
`/srv/stacks/veka-platform/env/{staging,production}/`, never in Git or workflow output.
The runbook contains the exact credential matrix, bootstrap order, DNS/OAuth setup, backups,
restore procedure and production cutover. Production uses the existing DB server, not staging PostgreSQL.

Do not activate the new production stack alongside the old production bot token or duplicate
Traefik website routers. Container readiness is not real-provider/data-migration acceptance.
An image rollback never reverses database migrations or restores secrets/media.
