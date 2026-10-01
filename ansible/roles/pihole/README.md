# pihole

DNS server, DHCP, ad/tracker blocking, and internal name resolution.

## Overview

Pi-hole provides DNS and DHCP for the local network. `*.home.example.com` is **not** a wildcard record — there is no single config entry that resolves every `*.home` hostname. Each hostname resolves only because a per-host DNS record exists for it. Every local record is declared in `pihole_dns_hosts` (`defaults/main.yml`) and rendered into Pi-hole's `FTLCONF_dns_hosts` environment variable, which makes the repo the only source of these records — see Notes below. Pi-hole runs with `network_mode: host` so it can bind to port 53 directly and support DHCP broadcasts — as a result it is **not** routed through Traefik.

## Prerequisites

- `common` role applied (Docker)
- Port 53 (TCP + UDP) open on UFW — added by the `common` role

## Containers

| Container | Image | Purpose |
|---|---|---|
| `pihole` | `pihole/pihole:2026.06.0` | DNS + DHCP + ad blocking |

Pi-hole runs with `network_mode: host`. It is not on the `proxy` Docker network and has no Traefik labels.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/pihole/docker-compose.yml` | Stack definition |

`FTLCONF_dns_hosts` in `docker-compose.yml` holds one `192.168.178.20 <hostname>` line per entry in `pihole_dns_hosts` — every internal `*.home` service, plus the apex-domain hosts `auth.example.com`, `daily-mcp.example.com` and `vpn.example.com`, which would otherwise hairpin through the public IP. It also holds one `<ip> <hostname>` line per entry in `pihole_dns_records`, for hosts that are not the Mini PC — currently `ai.home.example.com` → the LAN address of the atlas dev-lab VM (`dev_lab_ip`), which terminates TLS itself; tailnet clients reach it through the Mini PC's subnet route. Pi-hole v6 treats a setting given by environment variable as read-only, so the admin UI lists these records but cannot add, change or delete them.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `pihole_webpassword` | `vault_pihole_webpassword` | Web admin UI password |

## URL

`http://192.168.178.20:8080`

Pi-hole is not behind Traefik. It is accessible directly by LAN IP on port 8080. No HTTPS for the admin UI.

## Deploy

```bash
ansible-playbook ansible/site.yml --tags pihole
```

## Notes

**Adding or removing a DNS record:** Edit `pihole_dns_hosts` in `defaults/main.yml` (or override it in `group_vars`) and re-run the role. The changed environment recreates the container, and the role then asks Pi-hole for every listed hostname and fails if any does not answer with `192.168.178.20`. For a host that is not the Mini PC, add `{host, ip}` to `pihole_dns_records` instead; the role checks each of those answers with its own `ip`. The list is authoritative: removing a hostname removes its record. Records cannot be added in the admin UI, and the on-host `custom.list` is not read at all — Pi-hole v6 reads it only once, when migrating from v5 — so the role deletes any leftover copy.

**DHCP:** If Pi-hole is used for DHCP, disable the FritzBox's built-in DHCP server first to avoid conflicts.

**Upstream DNS:** Pi-hole forwards non-local queries upstream (default: `1.1.1.1`, `8.8.8.8`). Configure upstream resolvers in the Pi-hole admin UI under *Settings → DNS*.
