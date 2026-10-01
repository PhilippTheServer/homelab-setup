# daily2

daily — daily 2.0, the event-journal health and diet app: frontend, backend, database, a
public MCP endpoint for claude.ai, and a sync from gym-bro.

## Overview

Deploys the [daily](https://github.com/PhilippTheServer/daily) repository (named `daily2`
until 2026-09-30) as the `daily2` stack: an Angular
frontend served by nginx, a FastAPI backend (REST at `/api/v2` and an MCP server at
`/mcp`), and a dedicated Postgres. The backend also pulls workouts from `gym-bro`'s
`/export` route.

daily 2.0 replaced daily v1 on 2026-09-30 and serves daily's hosts
(`daily.{{ internal_subdomain }}.{{ domain }}` and `daily-mcp.{{ domain }}`) with v1's
Keycloak clients. The role, stack, containers and volume keep the name `daily2`.

The images are built from source and published to Harbor through the shared
[`harbor_image`](../harbor_image/README.md) role, then deployed with `compose_stack`:

1. `harbor_image` ensures the Harbor project `daily2` exists, asks Harbor whether
   `daily2_version` is published for each component, and if not ships the source to the
   Mini PC, builds `backend/` and `frontend/` there and pushes them to
   `registry.home.example.com/daily2/`
2. the retired daily v1 stack is taken down if it is still there (see "daily v1" below)
3. `compose_stack` deploys the stack and waits until every container is healthy

Unlike every other service, `daily2-backend` is reachable directly from the public
internet: `daily-mcp.{{ domain }}` is routed through Traefik with an IP allowlist and a
rate limit, not through the LAN/VPN-only model the rest of the stack uses. See "The
public MCP endpoint" below.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination, public port forward, ddclient host `daily-mcp`)
- `keycloak` role running — the `daily-app`, `daily-mcp` and `daily-gymbro-sync`
  clients exist in the `homelab` realm (`services/keycloak/realm-homelab.json.j2`)
- `harbor` role running (image registry)
- `pihole` role running — resolves `daily.{{ internal_subdomain }}.{{ domain }}` and
  `daily-mcp.{{ domain }}` internally without hairpinning through the public IP
  (`pihole_dns_hosts`)
- `gym-bro` role running — the sync calls its `/export` route
- A Namecheap host record `daily-mcp` (see `docs/ddns.md`). ddclient updates it but
  cannot create it
- The application source checked out on the control machine, at the released version:

  ```
  ~/code/homelab
  ~/code/daily2          ← git clone git@github.com:PhilippTheServer/daily.git daily2
  ```

  Override with `-e daily2_source_dir=/path/to/daily2` if it lives elsewhere.

## Containers

| Container | Image | Purpose |
|---|---|---|
| `daily2-frontend` | `registry.home.example.com/daily2/frontend` | nginx — serves the Angular bundle, writes `assets/runtime-config.json` from its env at start, proxies `/api/` to the backend; healthcheck `/healthz` |
| `daily2-backend` | `registry.home.example.com/daily2/backend` | FastAPI; runs `alembic upgrade head` at start; healthcheck `/health`; serves `/api/v2`, the public MCP endpoint and the gym-bro sync |
| `daily2-db` | `postgres` | Application database (volume `daily2_db`) |

`daily2-backend` is on `proxy`, `internal` and `db`: `proxy` carries the Traefik route for
the MCP endpoint, reaches `gym-bro-backend` for the sync, and gives egress (Keycloak JWKS,
Open Food Facts); `internal` (`daily2_internal`) has no egress and is shared with the
frontend; `db` (`daily2_db_net`) has no egress and is the only way to the database.
`daily2-frontend` is on `proxy` (its route) and `internal` (to reach the backend), so it
cannot reach Postgres. The browser talks to `/api/v2` on the same origin, so there is no
CORS configuration and no API hostname baked into the bundle.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `daily2_version` | `0.1.0` (in `group_vars`) | Image tag to build/deploy; must equal `backend/pyproject.toml` |
| `daily_owner_sub` | (in `group_vars`) | Keycloak `sub` of the sole owner; every query is scoped to it |
| `daily2_source_dir` | `{{ playbook_dir }}/../../daily2` | Application source on the control machine |
| `daily2_registry` | `registry.home.example.com` | Harbor CLI endpoint |
| `daily2_harbor_project` | `daily2` | Harbor project holding the images |
| `daily2_components` | `[backend, frontend]` | Components built and published |
| `daily2_build_dir` | `/opt/homelab/build/daily2` | Where the source is unpacked and built |
| `daily2_force_build` | `false` | Rebuild and overwrite an existing tag |
| `daily2_mcp_allowed_sources` | `{{ mcp_allowed_sources }}` (`group_vars`) | CIDR ranges allowed through the MCP router: Anthropic, LAN, Headscale VPN mesh |

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/daily2/docker-compose.yml` | The stack definition |

Keycloak is not configured by this role — the clients live in
`services/keycloak/realm-homelab.json.j2` and are applied by the `keycloak` role.

## Secrets

All secrets live in HashiCorp Vault at `secret/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `daily2_db_password` | `vault_daily2_db_password` | Application Postgres password |
| `daily_mcp_oidc_secret` | `vault_daily_mcp_oidc_secret` | Client secret of the `daily-mcp` Keycloak client, entered in the claude.ai connector (used by the `keycloak` role) |
| `daily_gymbro_sync_secret` | `vault_daily_gymbro_sync_secret` | Secret of `daily-gymbro-sync`, used for the client-credentials token for gym-bro's `/export` |

Via `harbor_image`, the role also reads `vault_harbor_admin_password` (owned by the
`harbor` role).

v1's `daily_db_password` and the retired `daily2_mcp_oidc_secret` are still in Vault, but
nothing reads them any more.

## URL

`https://daily.{{ internal_subdomain }}.{{ domain }}` — the browser app, LAN/VPN only.

`https://daily-mcp.{{ domain }}/mcp` — the public MCP endpoint for the claude.ai connector.

## Deploy

Dry run first. Don't add `--diff`: the template tasks would print the rendered compose
file, including secrets.

```bash
ansible-playbook ansible/site.yml --tags daily2 --check -e daily2_source_dir=~/Schreibtisch/self/daily2
ansible-playbook ansible/site.yml --tags daily2 -e daily2_source_dir=~/Schreibtisch/self/daily2
```

`daily2_source_dir` defaults to a `daily2` checkout next to this repo; pass it whenever
the checkout lives elsewhere. A plain `git clone` of the repo names the directory `daily`.

The deploy waits for all three containers to report healthy and fails the play if they
don't. Then check the running stack:

```bash
scripts/check-daily2.sh
```

It checks container health, the Alembic revision, backend health, the gym-bro sync, the
app, that the API refuses a request without a token, the MCP metadata, that the public
host routes nothing but `/mcp`, and the public DNS record. It also checks the switch-over
from v1: v1's containers are gone and its volume is kept, the backend takes tokens from
`daily-app` and `daily-mcp`, and the `daily2.*` hosts, their Pi-hole records and the
`daily2-app` / `daily2-mcp` Keycloak clients are gone. It exits 1 on any unexpected
result.

Rebuild without bumping the version:

```bash
ansible-playbook ansible/site.yml --tags daily2 -e daily2_source_dir=~/Schreibtisch/self/daily2 -e daily2_force_build=true
```

## Notes

**The public MCP endpoint.** `daily-mcp.{{ domain }}` is the only homelab hostname
reachable directly from the public internet besides `auth.{{ domain }}` and
`vpn.{{ domain }}`. The router only matches `/mcp` and
`/.well-known/oauth-protected-resource*`, so nothing else on `daily2-backend` is exposed.
`daily2-mcp-allowlist` (`ipallowlist`) admits only `mcp_allowed_sources` (Anthropic's
outbound range, the home LAN and the Headscale VPN mesh); everyone else gets a 403 before
the request reaches the container. `daily2-mcp-ratelimit` caps it at 20 requests/second,
burst 40. The metadata lives at `/.well-known/oauth-protected-resource/mcp` and names
the resource `https://daily-mcp.{{ domain }}/mcp`, the realm as authorization server and
`scopes_supported: ["openid"]`.

**Keycloak clients.** daily 2.0 uses v1's clients. `daily-mcp` is confidential
(`client-secret` auth), PKCE S256, has only the redirect
`https://claude.ai/api/mcp/auth_callback`, `fullScopeAllowed: false`, the optional scope
`offline_access` (the keycloak role maps and checks the `offline_access` role for it), and
an audience mapper for `MCP_RESOURCE_URL`. The backend accepts an MCP token only if its
`aud` contains that URL and its `azp` is `daily-mcp`. `daily-app` is a public PKCE client
for the browser, and the backend accepts REST tokens only with `azp` `daily-app`. Both
stay admin-only (not in `keycloak_open_clients`), and every token must carry
`OWNER_SUB`. Keeping v1's clients, audience and host at the switch-over is what let the
claude.ai connector carry on with its existing refresh token, without signing in again.

**claude.ai connector setup.** Add a custom connector pointing at
`https://daily-mcp.{{ domain }}/mcp`, with client ID `daily-mcp` and the secret from
`vault kv get -field=daily_mcp_oidc_secret secret/ansible`. Sign in with the owner
account. `OWNER_SUB` must match its Keycloak `sub`, or the backend rejects every
request.

**The gym-bro sync.** `daily2-backend` fetches a client-credentials token from Keycloak
using the confidential `daily-gymbro-sync` client, then calls `gym-bro-backend`'s
`/export` route directly over the shared `proxy` Docker network
(`GYM_BRO_URL=http://gym-bro-backend:8000`), never through Traefik or the public
internet. `daily-gymbro-sync` has no interactive flows and only
`serviceAccountsEnabled: true`, so the client-credentials grant is the only way to use
it. `fullScopeAllowed: false` and `defaultClientScopes: ["basic"]` keep role, profile and
email claims out of the token, and its access tokens expire after 300 seconds. gym-bro's
`/export` checks the token's `azp` against `EXPORT_CLIENT_ID` (`daily-gymbro-sync`),
which takes exactly one client. The first sync runs 30 seconds after the backend starts,
then every 15 minutes. Its state is in the `sync_state` table.

**daily v1.** Before deploying, the role takes down the v1 stack (`daily-frontend`,
`daily-backend`, `daily-db`) if its compose file is still on the host, and removes
`/opt/homelab/services/daily` and `/opt/homelab/build/daily`. The `daily_db` volume is
kept, because it holds the last copy of v1's data; nothing uses it. The Harbor project
`daily` still holds v1's images. v1's source is archived as
[PhilippTheServer/daily-v1](https://github.com/PhilippTheServer/daily-v1).

**Single worker.** The entrypoint runs `WORKERS` uvicorn workers (default 1). The stack
leaves it at 1.
