# homepage

Homelab dashboard with service links, widgets, and OIDC-protected access.

## Overview

Homepage is a highly configurable start page that aggregates all homelab services into a single dashboard. It reads live container status from the Docker socket and displays service health, links, and widgets. Access is protected by OIDC via Keycloak — unauthenticated requests are redirected to the Keycloak login page. All dashboard configuration (service tiles, widgets, bookmarks, Docker integration) is managed as Jinja2 templates and rendered by Ansible.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running (OIDC SSO)

## Containers

| Container | Image | Purpose |
|---|---|---|
| `homepage` | `ghcr.io/gethomepage/homepage:latest` | Dashboard application |

The container mounts `/var/run/docker.sock` (read-only) for live container discovery.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/homepage/docker-compose.yml` | Stack definition |
| `/opt/homelab/services/homepage/config/settings.yaml` | Global appearance and layout settings |
| `/opt/homelab/services/homepage/config/services.yaml` | Service tiles and links displayed on the dashboard |
| `/opt/homelab/services/homepage/config/widgets.yaml` | Info widgets (system stats, weather, etc.) |
| `/opt/homelab/services/homepage/config/bookmarks.yaml` | Bookmark groups and links |
| `/opt/homelab/services/homepage/config/docker.yaml` | Docker socket connection for container status |

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `homepage_oidc_secret` | `vault_homepage_oidc_secret` | Keycloak OIDC client secret |
| `homepage_nextauth_secret` | `vault_homepage_nextauth_secret` | NextAuth.js session signing secret |

## URL

`https://dash.home.example.com`

## Deploy

```bash
ansible-playbook ansible/site.yml --tags homepage
```

## Notes

**Config changes** to service tiles, widgets, or bookmarks only require updating the Jinja2 templates in `services/homepage/config/` and re-running the role — no container rebuild needed. Homepage reloads config automatically on file changes.

**Dashboard check:** after deploying, the role asks Homepage (`/api/services`, from inside the container) which services it shows and fails if any service in `services.yaml` is missing — Homepage silently drops entries it cannot parse. Only service names are read, never widget config. In `--check` mode the same comparison runs against the live dashboard, so tiles not yet deployed appear as an ignored failure that names them.

**Service groups:** Health (Gym Bro, daily), Media and Documents render as rows; Security & Identity, Development, Monitoring and Network are laid out as columns by `settings.yaml`, which also puts them first. Gym Bro and daily use their own PWA icons, which the browser loads from each app. OpenChamber (Development) links to the atlas dev-lab VM and uses the `opencode` icon: dashboard-icons has none for OpenChamber, and its own favicon sits behind Keycloak SSO.

**Docker widget** data (container status, uptime) requires the Docker socket mount. All containers visible to the socket can be referenced in `services.yaml` using their container name.
