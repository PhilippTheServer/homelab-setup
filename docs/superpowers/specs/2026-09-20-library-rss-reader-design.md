# library — RSS Reader — Design

**Date:** 2026-09-20
**Status:** Draft — awaiting review

## Goal

A self-hosted RSS/Atom reader for the homelab that is genuinely pleasant to read in:
a modern, responsive UI that works on a phone, a laptop and a large display, built
around the act of reading an article rather than around managing a database of them.

The existing open-source readers were rejected on presentation, not capability —
their feed engines are fine, their interfaces are not. So this design keeps a proven
engine and replaces only the interface.

Reachable from **LAN + Headscale VPN only**, never the public internet. Single user,
authenticated through Keycloak like every other service.

## Decisions

| Question | Decision |
|---|---|
| Feed engine | **Miniflux** (`miniflux/miniflux:2.3.3`) — polling, conditional GETs, Atom/RSS/RDF/JSON-feed parsing, dedup, full-text scraping, OPML. None of it written here. |
| Interface | **Custom Angular SPA** against Miniflux's REST API. Miniflux's own web UI is never exposed. |
| Miniflux API auth | **HTTP basic auth** with the admin credentials from Vault, held server-side by `library-api`. Not an API token — basic auth needs no bootstrap step. |
| Browser auth | Keycloak OIDC, public client `library-app` with PKCE — same as `daily-app` and `gym-bro`. |
| Feed management | **In the custom UI.** Add / edit / delete feeds, categories, OPML import + export. |
| App source | New repo `PhilippTheServer/library`, built into Harbor and deployed by a homelab role — the `daily` / `gym-bro` pattern. |
| Exposure | `library.home.example.com`, LAN + VPN only. No new FritzBox port. |
| v1 reading features | Full-text fetch, search across articles. |
| Deferred | Save/read-later, installable PWA, offline caching. |

## Architecture

```
Browser ──HTTPS──▶ Traefik ──▶ library-frontend (nginx + Angular)
   │                            │
   │  OIDC PKCE                 │  /api/  ──▶ library-api (FastAPI)
   ▼                            │                │
Keycloak (auth.example.com)             │  verifies RS256 JWT via JWKS
                                                 │  asserts sub == library_owner_sub
                                                 │
                                                 ├──X-Auth: basic──▶ library-miniflux:8080
                                                 │                      │
                                                 │                      ├──▶ library-db (postgres)
                                                 │                      └──▶ the internet (feed polling)
```

The browser talks to `/api/v1` on its own origin; nginx inside `library-frontend`
proxies it to `library-api`. No CORS configuration, no API hostname baked into the
bundle — identical to `daily-frontend`.

`library-miniflux` carries **no Traefik labels at all**. It is not reachable from the
LAN, the VPN, or anywhere else — only from `library-api` over the internal Docker
network. Its web UI exists but is unroutable.

### Containers

| Container | Image | Networks | Purpose |
|---|---|---|---|
| `library-frontend` | `registry.home.example.com/library/frontend` | `proxy`, `internal` | nginx — serves the Angular bundle, proxies `/api/` to the shim |
| `library-api` | `registry.home.example.com/library/backend` | `proxy`, `internal` | FastAPI — Keycloak JWT gate in front of Miniflux |
| `library-miniflux` | `miniflux/miniflux:2.3.3` | `proxy`, `internal` | Feed engine |
| `library-db` | `postgres:18-alpine` | `internal` | Miniflux's database |

**Network rationale.** `internal` has no egress. `library-api` needs `proxy` to reach
Keycloak's JWKS endpoint (same reason `daily-backend` is on both). `library-miniflux`
needs `proxy` for the same reason plus the one that matters most — **it must reach the
open internet to poll feeds**. A feed reader confined to `internal` fetches nothing.
Being on `proxy` grants egress; it does not publish a route, because the container
carries no `traefik.enable` label.

### Health checks

| Container | Check |
|---|---|
| `library-frontend` | `wget -qO- http://127.0.0.1/healthz` — 127.0.0.1 not localhost, per the `daily` note about IPv6 and Traefik dropping unhealthy containers |
| `library-api` | `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"` — the image has neither curl nor wget |
| `library-miniflux` | `/usr/bin/miniflux -healthcheck auto` |
| `library-db` | `pg_isready -U library -d library` |

`compose_stack`'s `compose_wait` fails the play unless all four report healthy.

## The API shim

`library-api` is deliberately thin. Two routes:

- `GET /health` — liveness, unauthenticated.
- `ANY /api/v1/{path:path}` — verify, then proxy.

Verification on every proxied request:

1. `Authorization: Bearer <jwt>` present, else 401.
2. Signature valid against Keycloak's JWKS for realm `homelab` (cached, refreshed on
   unknown `kid`), else 401.
3. `iss` matches the realm issuer, `azp == library-app`, and `exp` is in the future,
   else 401.
4. `sub == OWNER_SUB`, else 403.

Then the request is forwarded verbatim to `http://library-miniflux:8080/v1/{path}` with
the `Authorization` header replaced by basic auth from
`MINIFLUX_ADMIN_USERNAME` / `MINIFLUX_ADMIN_PASSWORD`. Query string, method, body and
response pass through unchanged.

One generic passthrough route, not an endpoint per feature: the frontend can use any
Miniflux endpoint without a backend change.

> `ponytail:` generic proxy — no per-endpoint allowlist or request-shape validation. The
> only caller is the owner's own SPA, authenticated as the single owner. Add a route
> allowlist if a second client or a non-owner user is ever introduced.

## The frontend

The product. Everything above exists to make this possible.

### Layout

| Viewport | Layout |
|---|---|
| Large display / laptop | Three panes: feed sidebar │ entry list │ reader |
| Tablet | Two panes: entry list │ reader |
| Phone | Single column: list → article, back navigation |

### Reading view

- Measure capped at ~68 characters; the column does not stretch to a 34" display.
- Deliberate typographic scale and line-height; article text is the only thing at full
  contrast on the page.
- Images and embeds constrained to the measure, never overflowing it.
- Light and dark themes from `prefers-color-scheme`, with a manual override.
- Article metadata (feed, author, date, reading time) is present but subordinate.

### Interaction

- Keyboard: `j`/`k` navigate, `o` open original, `m` toggle read, `/` search,
  `g u` unread, `g a` all. Miniflux-compatible bindings — existing muscle memory.
- Entry list pages through `offset`/`limit`, appended on scroll.
- Mark-as-read on open; bulk mark-all-read per feed and per category.

### Features against the Miniflux API

| Feature | Endpoint |
|---|---|
| Entry list, filtered and paged | `GET /v1/entries?status=&category_id=&feed_id=&offset=&limit=&order=&direction=` |
| Search across articles | `GET /v1/entries?search=` |
| Full-text fetch | `GET /v1/entries/{id}/fetch-content?update_content=true` |
| Mark read/unread | `PUT /v1/entries` |
| Feeds and categories | `GET /v1/feeds`, `GET /v1/categories`, `GET /v1/categories/{id}/feeds` |
| Add / edit / delete feed | `POST /v1/feeds`, `PUT /v1/feeds/{id}`, `DELETE /v1/feeds/{id}` |
| Category CRUD | `POST/PUT/DELETE /v1/categories` |
| Refresh a feed on demand | `PUT /v1/feeds/{id}/refresh` |
| OPML import / export | `POST /v1/import`, `GET /v1/export` |

### Error handling

- 401 from the shim → silent token refresh, then a re-login prompt if that fails.
- 403 → a terminal "not the owner" state; no retry.
- 5xx or network failure → inline retry affordance on the affected pane; the rest of
  the UI stays usable.
- A feed Miniflux failed to poll surfaces its `parsing_error_message` in the feed list
  rather than silently showing nothing new.
- Full-text fetch failure leaves the original entry content in place and reports the
  failure inline — never an empty article.

## Components

### New repo: `PhilippTheServer/library`

```
frontend/          Angular SPA + nginx image (mirrors daily's frontend)
backend/           FastAPI shim + its Dockerfile
```

Built on the Mini PC and pushed to Harbor project `library`, so images are native
`amd64` — as with `daily` and `gym-bro`.

### New role: `ansible/roles/library/`

- `tasks/main.yml` — Harbor project, "is this version published?" check, ship source,
  build, push, deploy via `compose_stack`. A copy of `ansible/roles/daily/tasks/main.yml`.
- `defaults/main.yml` — `library_source_dir`, `library_registry`,
  `library_harbor_project`, `library_components: [backend, frontend]`,
  `library_harbor_api`, `library_build_dir`, `library_force_build`.
- `README.md` — per repo convention, the standard eight-section structure.

### New service template: `services/library/`

- `docker-compose.yml.j2` — the four containers above.

### Edits to existing files

- `ansible/group_vars/all/vars.yml` — `miniflux_version: "2.3.3"`,
  `library_version: "1.0.0"`, `library_owner_sub`, and the two `vault_library_*` mappings.
- `ansible/site.yml` — add the `library` role after `daily`.
- `ansible/roles/pihole/defaults/main.yml` — add
  `library.{{ internal_subdomain }}.{{ domain }}` to `pihole_dns_hosts`.
- `services/keycloak/realm-homelab.json.j2` — add the `library-app` client.

### Keycloak client

`library-app` — public client, PKCE required, no client secret, standard flow only.
Redirect URI `https://library.home.example.com/*`.

**Not** added to `keycloak_open_clients`: the app is single-owner, so signing in
requires the realm `admin` role, same as `daily-app`.

## Secrets

`secret/ansible` gains two fields:

| Vault field | Variable | Purpose |
|---|---|---|
| `library_db_password` | `vault_library_db_password` | Miniflux's Postgres password |
| `library_miniflux_admin_password` | `vault_library_miniflux_admin_password` | Miniflux admin account — created at first boot by `CREATE_ADMIN=1`, and the credential `library-api` authenticates with |

The role also reads `vault_harbor_admin_password` for image push/pull, as `daily` does.

No OIDC client secret: `library-app` is a public PKCE client, and Miniflux's own
OIDC login is not configured because its UI is never exposed.

## Monitoring

`METRICS_COLLECTOR=1` gives Miniflux a Prometheus endpoint on `/metrics` — feed poll
failures, entry counts and poll durations, for one environment variable.

Prometheus reaches `library-miniflux` over the shared `proxy` network, so
`METRICS_ALLOWED_NETWORKS` is set to the `proxy` network's subnet, read from Docker
rather than hardcoded. Confirm the actual subnet during phase 1 — if the value is wrong
Miniflux returns 403 on `/metrics` and the scrape target shows as down in Grafana,
which is the check that this was got right.

## Verification

Per `CLAUDE.md`'s definition of done, each phase lands with a check that fails if it
regresses.

**`library` repo — `pytest`, run in CI and locally:**

- Request with no `Authorization` header → 401, and Miniflux is never called.
- Request with a token signed by the wrong key → 401.
- Request with an expired token → 401.
- Valid token whose `sub` is not `OWNER_SUB` → 403.
- Valid owner token → request reaches the stubbed Miniflux with a basic-auth header,
  and the stub's status, body and content-type come back unchanged.
- Query string and request body survive the proxy hop intact.

The Miniflux stub is a local HTTP server in the test fixture; no container, no network.

**`library` repo — Angular unit tests** on the entry list, the reader component's
sanitisation of feed HTML, and the keyboard handler.

**homelab repo:**

```bash
ansible-playbook ansible/site.yml --tags library --check
```

and, on a real apply, `compose_wait` gating all four containers healthy.

**Manual acceptance, once, at the end of phase 1:**

```bash
curl -sk https://library.home.example.com/api/v1/feeds -o /dev/null -w '%{http_code}\n'
# expect 401
```

## Build order

| Phase | Contents | Verified by |
|---|---|---|
| 1 | Role, four containers, Keycloak client, Pi-hole record, docs | All four containers healthy; `/api/v1/feeds` returns 401 without a token, 200 with the owner's |
| 2 | Reading UI — entry list, reader, search, full-text, keyboard, responsive layouts | Angular unit tests; the shim's pytest suite |
| 3 | Feed management — add/edit/delete, categories, refresh, OPML import/export | Angular unit tests |

Each phase is its own issue and its own PR.

## Deploy

```bash
export VAULT_TOKEN=...
ansible-playbook ansible/site.yml --tags pihole,keycloak,library
```

Dry run first, without `--diff` — the template tasks would print the rendered compose
file, including secrets, to the terminal:

```bash
ansible-playbook ansible/site.yml --tags library --check
```

As with `daily`, check mode fails at "fail early when the source is missing" unless the
`library` source is checked out at `library_source_dir`. That is intended.

## Docs to update (per CLAUDE.md, in the same change)

- `README.md` — stack table
- `docs/architecture.md` — service stacks, repo layout, bootstrap order
- `docs/bootstrap.md` — `vault kv put` command, deploy order
- `ansible/roles/library/README.md`

## Out of scope (YAGNI)

- **Save / read-later and starred lists.** Miniflux's API already carries `starred` and
  a bookmark endpoint, so this is a UI addition whenever it's wanted — no schema or
  backend change.
- **Installable PWA and offline reading.** Adds a service worker and a cache
  invalidation problem to a service that is LAN/VPN-only anyway.
- **Multi-user.** The shim asserts a single `OWNER_SUB`; Miniflux supports users if that
  ever changes.
- **Public internet exposure.** No new FritzBox port; the access model is unchanged.
- **Third-party reader apps** (Google Reader / Fever API compatibility). Miniflux can
  serve them, but nothing would route to it — its port is not published.
- **An in-app recommendation or ranking layer.** Chronological, by feed. That is the
  point.
