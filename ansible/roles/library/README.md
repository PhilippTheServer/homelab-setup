# library

Self-hosted RSS reader — a Miniflux feed engine behind a purpose-built reading UI.

## Overview

Deploys the [library](https://github.com/PhilippTheServer/library) stack: an Angular
reading app served by nginx, a FastAPI shim that gates the API on Keycloak, a
[Miniflux](https://miniflux.app) feed engine, and a dedicated Postgres.

Miniflux does the work nobody should write twice — polling schedules, conditional GETs,
Atom/RSS/RDF/JSON-feed parsing, deduplication, full-text scraping and OPML. The
application repository contains no feed-parsing code at all; it contains the interface,
which is the part the existing readers get wrong.

Like `gym-bro` and `daily`, the two application images are not pulled from Docker Hub —
they are built from source and published to the self-hosted Harbor registry. The role:

1. ensures the `library` project exists in Harbor
2. asks Harbor whether `library_version` is already published, for each component in
   `library_components`
3. if it is not, ships the source to the Mini PC, builds the image(s) there, and pushes
   them to `registry.home.example.com`
4. reads the `proxy` network's subnet so Miniflux will answer Prometheus
5. deploys the compose stack, which pulls those images

Building on the target rather than the control machine keeps the images native `amd64`.

Publishing a new build is a version bump in `group_vars/all/vars.yml`. To rebuild
without bumping (after a fix), pass `-e library_force_build=true`.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running — the `library-app` client must exist in the `homelab` realm
  (defined in `services/keycloak/realm-homelab.json.j2`, applied by the `keycloak` role)
- `harbor` role running (image registry)
- `pihole` role running — resolves `library.{{ internal_subdomain }}.{{ domain }}`
  internally (`pihole_dns_hosts`)
- The application source checked out on the control machine. By default the role
  expects it next to this repo:

  ```
  ~/code/homelab
  ~/code/library        ← git clone git@github.com:PhilippTheServer/library.git
  ```

  Override with `-e library_source_dir=/path/to/library` if it lives elsewhere.

## Containers

| Container | Image | Purpose |
|---|---|---|
| `library-frontend` | `registry.home.example.com/library/frontend` | nginx — serves the Angular bundle and proxies `/api/` to the shim |
| `library-api` | `registry.home.example.com/library/backend` | FastAPI; healthcheck on `/health`; verifies the Keycloak token, then forwards to the engine |
| `library-miniflux` | `miniflux/miniflux` | The feed engine. **No Traefik labels — no route, anywhere** |
| `library-db` | `postgres` | The engine's database |

`library-frontend` is attached to `proxy` (the Traefik route) and `internal` (to reach
`library-api`), the same pattern as `daily2-frontend`. The browser talks to `/api/v1` on
the same origin, so there is no CORS configuration and no API hostname in the bundle.

`library-api` is attached to both networks too: `internal` to reach the engine, and
`proxy` for egress, because it must fetch Keycloak's JWKS to verify tokens and
`internal` has no route out.

`library-miniflux` is **also** on `proxy`, and this is the one that matters: `internal`
has no egress, and a feed reader that cannot reach the open internet polls nothing.
Being on `proxy` grants it that egress. What keeps it unreachable is the complete
absence of a `traefik.enable` label — Traefik never learns it exists, so its web UI and
its API are reachable only from `library-api` over the Docker network.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `library_version` | `1.1.1` (in `group_vars`) | Image tag to build/deploy |
| `miniflux_version` | `2.3.3` (in `group_vars`) | Feed engine image tag |
| `library_owner_sub` | (in `group_vars`) | Keycloak `sub` of the sole owner — a valid token from any other account is refused with 403 |
| `library_source_dir` | `{{ playbook_dir }}/../../library` | Application source on the control machine |
| `library_registry` | `registry.home.example.com` | Harbor CLI endpoint |
| `library_harbor_project` | `library` | Harbor project holding the images |
| `library_components` | `[backend, frontend]` | Components built and published |
| `library_build_dir` | `/opt/homelab/build/library` | Where the source is unpacked and built |
| `library_force_build` | `false` | Rebuild and overwrite an existing tag |
| `library_polling_frequency` | `30` | Minutes between feed polls |
| `library_miniflux_username` | `library` | The engine's own account name |

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/library/docker-compose.yml` | The stack definition |

Keycloak is not configured by this role — the `library-app` client lives in
`services/keycloak/realm-homelab.json.j2` and is applied by the `keycloak` role.

## Secrets

All secrets live in HashiCorp Vault at `secret/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `library_db_password` | `vault_library_db_password` | The engine's Postgres password |
| `library_miniflux_admin_password` | `vault_library_miniflux_admin_password` | The engine's own account, created at first boot by `CREATE_ADMIN=1`, and the credential `library-api` authenticates with |

The role also reads `vault_harbor_admin_password` (owned by the `harbor` role) to
authenticate image pushes and pulls.

There is no OIDC client secret: `library-app` is a public client using PKCE, and the
engine's own OIDC login is not configured because its UI is never exposed.

## URL

`https://library.{{ internal_subdomain }}.{{ domain }}` — LAN and VPN only.

The engine has no URL. That is deliberate.

## Deploy

```bash
ansible-playbook ansible/site.yml --tags library
```

The deploy waits (`compose_wait`) for all four containers to report healthy, and fails
the play if they don't.

Dry run first. Check mode queries Harbor for the tag, so it reports the real build
decision, but it creates no Harbor project and ships, builds or pushes nothing:

```bash
ansible-playbook ansible/site.yml --tags library --check
```

Don't add `--diff`: the template task would print the rendered compose file, including
the engine's password, to your terminal.

Check mode still fails at "fail early when the source is missing" unless the library
source is checked out at `library_source_dir` — that's intended, for the same reason it
is in the `harbor_image` role.

Rebuild the image without bumping the version:

```bash
ansible-playbook ansible/site.yml --tags library -e library_force_build=true
```

## Notes

**Why there is a shim at all.** Miniflux's REST API authenticates with an `X-Auth-Token`
header or HTTP basic auth. It has no support for OIDC bearer tokens, so the credential
cannot be handed to a browser without handing the whole API to anything running on the
page. `library-api` holds it instead: it verifies the caller's Keycloak token —
signature against the realm JWKS, issuer, expiry, and `azp` — checks the subject
against `OWNER_SUB`, and only then reissues the request upstream with basic auth. The
caller's bearer token is stripped before forwarding; the engine never sees it.

It uses basic auth rather than an API token deliberately. A token would have to be
minted by signing in to the engine's web UI, which has no route — so the bootstrap
would require reaching into the container by hand. The admin password is already a
Vault field, because `CREATE_ADMIN` needs it.

**The shim is one route.** `ANY /api/v1/{path}` forwards verbatim. There is no endpoint
per feature, so the reading UI can use any part of the Miniflux API without a backend
change. The trade-off is that there is no per-endpoint allowlist; the only caller is
the owner's own browser app, authenticated as the single owner.

**The metrics endpoint.** Miniflux answers `/metrics` only for source networks listed
in `METRICS_ALLOWED_NETWORKS`. Prometheus reaches it over the shared `proxy` network,
so the role reads that network's real subnet with `docker network inspect` and asserts
it looks like a CIDR before rendering the stack. Hardcoding it would break silently —
a recreated `proxy` network with a different subnet would leave Miniflux returning 403
and the Grafana target showing as down, with nothing else wrong.

**The `library-app` client.** Public client with PKCE, no client secret, standard flow
only. It is **not** listed in `keycloak_open_clients`, so it stays admin-only: the
reader is single-owner (`OWNER_SUB`), and there is no reason to let a second realm
account authenticate against it.
