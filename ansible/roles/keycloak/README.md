# keycloak

SSO / OIDC identity provider — all services authenticate here.

## Overview

Keycloak is the central authentication hub for the homelab. Every service that supports OIDC (Vaultwarden, GitLab, Harbor, HashiCorp Vault, Headscale, Homepage, Paperless-ngx) is configured as a client in the `homelab` realm, as is OpenChamber on the atlas dev-lab VM, which has no OIDC of its own and signs in through an oauth2-proxy there (client `openchamber`, admin-only like every client not in `keycloak_open_clients`). A realm export JSON is rendered by Ansible and imported automatically on first container startup via the `--import-realm` flag, so OIDC clients and realm settings are declared as code. Keycloak's database is an isolated Postgres container on an internal-only network.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- Pi-hole DNS record `auth.example.com` → `192.168.178.20` (added automatically by the `pihole` role)

## Containers

| Container | Image | Purpose |
|---|---|---|
| `keycloak` | `quay.io/keycloak/keycloak:26.6` | Identity provider |
| `keycloak-db` | `postgres:18-alpine` | Keycloak database |

Networks: `keycloak` joins `proxy` (Traefik-visible) and `keycloak_internal` (database-only, not routable).

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/keycloak/docker-compose.yml` | Stack definition |
| `/opt/homelab/services/keycloak/import/realm-homelab.json` | Realm definition imported on first boot |

Role variables (`defaults/main.yml`):

| Variable | Purpose |
|---|---|
| `keycloak_groups_scope_clients` | Clients that get the `groups` client scope attached as a default scope |
| `keycloak_retired_clients` | Clients deleted from the live realm (`daily2-app`, `daily2-mcp`) |

A client may only request a scope that is attached to it — anything else is answered
with `invalid_scope` and the request never reaches the login page. Listing the scope
in the realm template's `defaultClientScopes` is not enough on its own: Keycloak's
Admin API **ignores** `defaultClientScopes` when a client is *updated*, so the
template's arrays only take effect for clients created by the first-boot import.
Clients that already exist are corrected through the dedicated
`default-client-scopes` sub-resource, which is what `keycloak_groups_scope_clients`
drives. Add a service here whenever its OIDC scope string contains `groups`.

The client sync only creates clients and updates them, so a client dropped from the
realm template stays in the live realm. To remove one, drop it from the template and
list its `clientId` in `keycloak_retired_clients`; the role deletes it when it exists,
which also ends every session and token issued to it.

A client that requests `offline_access` (claude.ai does, for the `daily-mcp`
connector's refresh tokens) also needs the `offline_access` realm role in its token scope, or
Keycloak refuses the code exchange with "Offline tokens not allowed for the user or
client". Clients with `fullScopeAllowed: true` get it from the user's roles. A client
without full scope (`daily-mcp`) gets it only through the `offline_access` client
scope's role mapping. That mapping is Keycloak's built-in default, but this realm was
imported without it, so the template's realm-level `scopeMappings` declares it and the
role adds it to the live realm when it is missing. After syncing, the role asks Keycloak
(`evaluate-scopes/.../granted?scope=offline_access`) whether every template client
offering `offline_access` is granted that role, and fails for any that is not. The check
is read-only, so a dry run reports the gap as an ignored failure.

**Metrics and event log.** Keycloak exports Prometheus metrics on its management port `9000` (`/metrics`), which only the `proxy` Docker network reaches — Traefik routes port `8080` alone. The export includes HTTP request histograms and per-client user event metrics (`keycloak_user_events_total`, tagged `realm` and `clientId`). These are build-time options, so changing them makes Keycloak rebuild at startup (about a minute without SSO). The role's first admin-token request retries until Keycloak answers again. The jboss-logging event listener logs successful events at INFO (`KC_SPI_EVENTS_LISTENER__JBOSS_LOGGING__SUCCESS_LEVEL`), not only errors at WARN. Every login, code exchange, refresh and client login then reaches Loki with username, client and IP, kept for Loki's 14-day retention. The monitoring role's Keycloak dashboard is built on both.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `keycloak_db_password` | `vault_keycloak_db_password` | Postgres password for the `keycloak` database |
| `keycloak_admin_user` | `vault_keycloak_admin_user` | Initial admin username |
| `keycloak_admin_password` | `vault_keycloak_admin_password` | Initial admin password |
| `keycloak_alice_initial_password` | `vault_keycloak_alice_initial_password` | One-time password for `alice` (`keycloak_users`); must be changed at first sign-in |
| `keycloak_bob_initial_password` | `vault_keycloak_bob_initial_password` | One-time password for `bob` (`keycloak_users`); must be changed at first sign-in |
| `keycloak_ali_initial_password` | `vault_keycloak_ali_initial_password` | One-time password for `ali` (`keycloak_users`); must be changed at first sign-in |
| `openchamber_oidc_secret` | `vault_openchamber_oidc_secret` | Client secret of `openchamber`; the dev-lab oauth2-proxy reads the same field |

## URL

`https://auth.example.com`

Keycloak sits at the apex domain (not under `home.`) because OIDC redirect URIs must resolve from any device, including those not on the LAN or VPN. Headscale (`vpn.example.com`) and daily (`daily-mcp.example.com`) also sit at the apex domain, for their own reasons — see the [README](../../../README.md) Access Model section.

## Deploy

```bash
ansible-playbook ansible/site.yml --tags keycloak
```

Dry run first. The read-only Admin API calls also run in check mode, so the dry run
evaluates the live realm (admin token, clients, client scopes, mappers); every POST and PUT is skipped:

```bash
ansible-playbook ansible/site.yml --tags keycloak --check --diff
```

## Notes

**Realm import is first-boot only; clients are synced on every run.** The `--import-realm` flag skips import if the realm already exists, so re-deploying never re-imports the realm and leaves other manual realm changes alone. The Admin API client sync then runs on every deploy: it POSTs any template client missing from the live realm, and, after a change to the rendered realm template, PUTs every template client over its live counterpart, so manual edits to those clients in the Keycloak UI are overwritten. To fully re-import, delete the `keycloak_db` volume and redeploy.

**Who may sign in to what.** Every client is admin-only unless it is listed in `keycloak_open_clients` (`headscale`, `gym-bro`, `account-console`). The realm's default browser flow is `browser-admin-only` (`keycloak_gated_flow_nodes` in `defaults/main.yml`). It wraps the normal sign-in (SSO cookie, or password plus OTP where configured) in a required sub-flow, then denies users without the realm role `admin` in a conditional one, so an SSO session opened on gym-bro doesn't carry a non-admin into Grafana. The open clients override it with the stock `browser` flow. `tasks/access.yml` builds the flow when it's missing, asserts its structure on every run, and fails if any other client has its own browser flow. Check the result with real sign-ins:

```bash
KEYCLOAK_ADMIN_USER=$(vault kv get -field=keycloak_admin_user secret/ansible) \
KEYCLOAK_ADMIN_PASSWORD=$(vault kv get -field=keycloak_admin_password secret/ansible) \
python3 scripts/check-keycloak-access.py
```

It creates a throwaway admin and non-admin user, signs both in to every client (fresh and via an existing SSO session), expects the admin everywhere and the non-admin only in the open clients, deletes both users and exits 1 on any other result.

Keycloak counts an "Access denied" as a failed login for brute-force protection (`bruteForceProtected`, `quickLoginCheckMilliSeconds: 1000`): a non-admin who opens several admin-only apps within a second is locked out for a minute. The check script clears the count before each attempt; a locked-out user can be cleared in the admin console under the user's Details.

**Token and session lifetimes are kept in step on every run.** The realm-level keys listed in `keycloak_realm_synced_settings` (`defaults/main.yml`) are compared with the realm template and PUT to the live realm when they differ; the dry run prints each `old -> new`. Every other realm-level key still applies to a fresh realm only.

**Log in once a week.** Access tokens and the SSO session last 7 days (604800 s), and Remember me is enabled with the same 7 days. Tick **Remember me** on the login page: without it Keycloak's session cookie is dropped when the browser closes, and apps that check the Keycloak session on every visit (gym-bro) ask for a login again. The trade-off is deliberate: a leaked access token stays valid for up to a week.

**OIDC client secrets** are generated in the Keycloak admin UI after first boot, then stored in HashiCorp Vault (`vault kv patch secret/ansible <service>_oidc_secret="..."`). Ansible reads them back on subsequent runs to configure each service's OIDC integration.

**Setup priority:** Keycloak should be deployed first among all services because every other OIDC-enabled service depends on it being reachable to complete its own configuration.
