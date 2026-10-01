# paperless

Self-hosted document management system with OCR.

## Overview

Paperless-ngx ingests, OCRs, tags, and archives scanned documents and PDFs. Documents dropped into the consume directory are automatically processed and made full-text searchable. Office documents (docx, xlsx, odt) are converted via Tika and Gotenberg before OCR. Authentication is OIDC via Keycloak; local signups are disabled. The application data, media, and database are each in dedicated named volumes so the stack can be rebuilt without data loss.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running (OIDC SSO)

## Containers

| Container | Image | Purpose |
|---|---|---|
| `paperless` | `ghcr.io/paperless-ngx/paperless-ngx:2.14` | Document management + OCR |
| `paperless-db` | `postgres:18-alpine` | Document index and metadata |
| `paperless-redis` | `redis:7-alpine` | Task queue for async processing |
| `paperless-gotenberg` | `gotenberg/gotenberg:8` | Office document → PDF conversion |
| `paperless-tika` | `apache/tika:latest` | File content extraction |

Networks: `paperless` joins `proxy` (Traefik) and `paperless_internal` (database, Redis, Gotenberg, Tika). The backing services are not externally routable.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/paperless/docker-compose.yml` | Stack definition |

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `paperless_db_password` | `vault_paperless_db_password` | Postgres password |
| `paperless_secret_key` | `vault_paperless_secret_key` | Django secret key (sessions, CSRF) |
| `paperless_admin_password` | `vault_paperless_admin_password` | Initial admin account password |
| `paperless_oidc_secret` | `vault_paperless_oidc_secret` | Keycloak OIDC client secret |
| `paperless_api_token` | `vault_paperless_api_token` | API token for Homepage dashboard widget |

## URL

`https://paper.home.example.com`

## Deploy

```bash
ansible-playbook ansible/site.yml --tags paperless
```

## Notes

**Admin account** (`admin` user) is created automatically on first startup via `PAPERLESS_ADMIN_USER` / `PAPERLESS_ADMIN_PASSWORD`. Use it for initial setup and to assign the Keycloak OIDC user the superuser role if needed.

**OIDC login** appears as a "Keycloak" button on the login page. New accounts via OIDC are blocked (`SOCIAL_ACCOUNT_ALLOW_SIGNUPS=false`) — the admin must create user accounts first, then users can link them to Keycloak via the profile settings.

**Consume directory** is backed by the `paperless_consume` Docker volume. To auto-ingest documents, copy files into that volume (e.g. via `docker cp` or a watched NFS/Samba share mounted to the volume path).

**Homepage API token**: after first login, generate a token in paperless → Settings → API token, then store it in Vault:

```bash
vault kv patch secret/ansible paperless_api_token="<token>"
ansible-playbook ansible/site.yml --tags homepage
```

**OCR languages**: configured for German + English (`deu+eng`). Add more ISO 639-2/T codes to `PAPERLESS_OCR_LANGUAGE` if needed.
