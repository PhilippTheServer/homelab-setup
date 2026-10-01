# harbor

Docker container image registry.

## Overview

Harbor is an enterprise-grade container registry with role-based access control, vulnerability scanning, and image signing. Unlike other roles that manage a simple `docker-compose.yml`, this role uses Harbor's official online installer — it downloads a versioned installer tarball, runs the `prepare` script (which generates Harbor's own internal compose files from `harbor.yml`), and then starts the stack using an override compose file to integrate Harbor into the existing Traefik `proxy` network. After startup, the role configures OIDC authentication via the Harbor API so Keycloak handles all logins.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running (OIDC SSO — the OIDC configuration step polls the Harbor API)

## Containers

Harbor's installer generates its own compose file. Key containers:

| Container | Purpose |
|---|---|
| `harbor-core` | Main Harbor API and web UI |
| `harbor-db` | Built-in Postgres database |
| `harbor-jobservice` | Async job processing (replication, GC) |
| `nginx` | Internal Harbor proxy |
| `registry` | Docker distribution registry backend |
| `redis` | Cache and job queue |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `harbor_session_timeout_minutes` | `10080` (7 days) | How long a UI login lasts; set through the configuration API on every run, only when it differs. Harbor's own default is 60 |

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/harbor/harbor.yml` | Primary Harbor configuration (hostname, HTTP port, storage paths, database password) |
| `/opt/homelab/harbor/docker-compose.override.yml` | Attaches Harbor containers to the `proxy` Docker network and adds Traefik labels |

Harbor's own nginx always listens on port `8080` **inside** the container; `http.port`
in `harbor.yml` only controls which host port the generated compose publishes. Traefik
reaches the container over the `proxy` network, so the `loadbalancer.server.port` label
must be `8080` — pointing it at the host port produced a 502.

TLS is fully handled by Traefik. The role's own API calls (readiness, OIDC config) go
through `https://harbor.home.example.com` rather than a host port, so they do
not depend on `prepare` having regenerated the compose file.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `harbor_admin_password` | `vault_harbor_admin_password` | Initial admin password |
| `harbor_db_password` | `vault_harbor_db_password` | Built-in Postgres password |
| `harbor_oidc_secret` | `vault_harbor_oidc_secret` | Keycloak OIDC client secret |

## URL

`https://harbor.home.example.com`

## Deploy

```bash
ansible-playbook ansible/site.yml --tags harbor
```

Dry run first. The read-only Admin API calls also run in check mode, so the dry run
evaluates Harbor's live configuration; every POST and PUT is skipped:

```bash
ansible-playbook ansible/site.yml --tags harbor --check --diff
```

## Notes

**Installer-based setup:** The `prepare` step only runs once (guarded by `creates:`). To force a full re-initialization, delete `/opt/homelab/harbor/common/config/` and re-run the role.

**The installer is downloaded only when missing.** `/tmp/harbor-<version>.tgz` is fetched from GitHub only if it is not already on the host, with 3 retries, so a run with the installer present never depends on GitHub being reachable.

**Browser logins must start on `harbor.*`, not `registry.*`.** Both hostnames route to
the same container, but Harbor's `sid` session cookie is host-scoped while the OIDC
callback always returns to `external_url` (`harbor.*`). Starting a login on `registry.*`
therefore lands the callback on a host that never receives the session, and Harbor
rejects it with `State mismatch` — rendered in the browser as a bare `Bad Request`.
Keep `registry.*` for `docker login/push/pull` only.

**The Keycloak `harbor` client needs the `groups` client scope.** The role sets
`oidc_scope` to `openid,profile,email,groups`, and Keycloak rejects any scope not
attached to the client with `invalid_scope` — again surfacing as `Bad Request`. The
scope is attached by the `keycloak` role via `keycloak_groups_scope_clients`; changing
`oidc_scope` here means updating that list too.

**OIDC is configured idempotently via the API.** The role reads the current `auth_mode` from the Harbor API and only applies the OIDC configuration if it is not already set to `oidc_auth`. To reconfigure OIDC without a full redeploy, set `auth_mode` back to `db_auth` in the Harbor admin UI and re-run the role.

**Pushing images** requires logging in with the OIDC-issued CLI secret (not the Keycloak password directly). In Harbor UI go to *User Profile → CLI secret*, copy it, then:

```bash
docker login harbor.home.example.com
# username: <keycloak username>
# password: <CLI secret from Harbor UI>
```
