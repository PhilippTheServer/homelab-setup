# ufw

Host firewall configuration — strict default-deny with explicit allow rules for all exposed services.

## Overview

This role installs UFW, sets a default-deny incoming / allow outgoing policy, and opens exactly the ports that services running on this host need to be reachable. It runs once during initial host provisioning alongside `common`.

## Prerequisites

- Debian-based host with `apt`
- SSH access as root or a user with sudo privileges

## Containers

None. This role configures the host firewall only.

## Configuration

No variables. All port rules are explicit tasks in `tasks/main.yml`.

## Firewall Rules

| Port | Protocol | Service | Purpose |
|---|---|---|---|
| 1461 | TCP | SSH | Remote administration |
| 80 | TCP | Traefik | HTTP (redirects to HTTPS) |
| 443 | TCP | Traefik | HTTPS — all web services route through here |
| 53 | TCP + UDP | Pi-hole | DNS queries (`network_mode: host`) |
| 2222 | TCP | GitLab | Git SSH access (`host:2222 → container:22`) |
| 8080 | TCP | Pi-hole | Admin web UI (`network_mode: host`, port set via `FTLCONF_webserver_port`) |

Default policy: incoming **deny**, outgoing **allow**.

## Secrets

None.

## URL

No URL — host firewall only.

## Deploy

```bash
ansible-playbook ansible/site.yml --tags ufw
```

## Notes

- All other services are reachable only through Traefik (ports 80/443) or on internal Docker networks — no additional host ports are required.
- The role is idempotent. UFW rules are applied with the `ufw` module, which is a no-op when the rule already exists.
- Like `common`, this role is commented out in `site.yml` after the initial provisioning run to avoid overhead on every deploy. Re-enable it when provisioning a fresh host or after an OS reinstall.
