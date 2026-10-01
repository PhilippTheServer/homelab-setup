# vaultwarden

Self-hosted Bitwarden-compatible password manager.

## Overview

Vaultwarden is a lightweight, unofficial Bitwarden server implementation. It is compatible with all official Bitwarden clients (browser extensions, mobile apps, desktop). Registration is disabled — access is by invitation only, with SSO via Keycloak as the primary login method. Passwords and secure notes are stored encrypted in a dedicated Postgres database on an internal-only network.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running (OIDC SSO)

## Containers

| Container | Image | Purpose |
|---|---|---|
| `vaultwarden` | `vaultwarden/server:1.37.1` | Password manager server |
| `vaultwarden-db` | `postgres:18-alpine` | Encrypted vault storage |

Networks: `vaultwarden` joins `proxy` (Traefik) and `vaultwarden_internal` (database). The database is not externally routable.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/vaultwarden/docker-compose.yml` | Stack definition |

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `vaultwarden_db_password` | `vault_vaultwarden_db_password` | Postgres password |
| `vaultwarden_admin_token` | `vault_vaultwarden_admin_token` | Admin panel token (`/admin` path) |
| `vaultwarden_oidc_secret` | `vault_vaultwarden_oidc_secret` | Keycloak OIDC client secret |

## URL

`https://bw.home.example.com`

## Deploy

```bash
ansible-playbook ansible/site.yml --tags vaultwarden
```

## Notes

**Public registration is disabled** (`SIGNUPS_ALLOWED=false`). New users must be invited by an existing admin. Invitations are enabled (`INVITATIONS_ALLOWED=true`).

**Admin panel** is available at `https://bw.home.example.com/admin` — authenticate with the `vault_vaultwarden_admin_token`. Use it to manage users and send invitations.

**Bitwarden clients** should be configured to use a custom server URL: `https://bw.home.example.com`. The SSO login option will redirect to Keycloak.

**Keep the server version current.** Vaultwarden ships the web vault bundled with the server image, so the browser UI always stays version-matched and keeps working. The browser extensions, desktop app and mobile apps auto-update independently and can outrun the server's supported API. When that happens the symptom is one-sided: the web vault at the URL above works fine, while every native client fails to sync or load vault data. Vaultwarden `1.37.0` is the minimum required for clients `2026.7.0+`. If clients break after an auto-update, check the upstream release notes for a client-compatibility requirement before debugging the network or Traefik.
