# traefik

Reverse proxy, wildcard TLS termination via Let's Encrypt, and DDNS updater.

## Overview

Traefik acts as the single entry point for all HTTP/HTTPS traffic. It discovers services automatically via Docker labels and terminates TLS using a wildcard Let's Encrypt certificate (`*.home.example.com`) issued through the Namecheap DNS-01 challenge — internal services never need to be publicly reachable for cert issuance. A `ddclient` sidecar keeps the public DNS A record for `vpn.example.com` pointed at the current home IP, which is required for Headscale remote access.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- Namecheap API access enabled and home IP whitelisted
- DDNS enabled for the domain in Namecheap
- FritzBox port forwarding: TCP 80 and TCP 443 → `192.168.178.20`

## Containers

| Container | Image | Purpose |
|---|---|---|
| `traefik` | `traefik:v3.7` | Reverse proxy + TLS termination + dashboard |
| `ddclient` | `lscr.io/linuxserver/ddclient:latest` | Keeps `vpn.example.com` A record current |

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/traefik/docker-compose.yml` | Stack definition |
| `/opt/homelab/services/traefik/ddclient.conf` | DDNS update interval and Namecheap credentials |
| `/opt/homelab/services/traefik/dynamic/tls-options.yaml` | TLS cipher and version options |

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `namecheap_api_user` | `vault_namecheap_api_user` | Namecheap API authentication |
| `namecheap_api_key` | `vault_namecheap_api_key` | Namecheap API key for DNS-01 challenge |
| `namecheap_ddns_password` | `vault_namecheap_ddns_password` | DDNS update password for ddclient |
| `traefik_dashboard_auth` | `vault_traefik_dashboard_auth` | Basic auth credentials for the dashboard (htpasswd format) |

## URLs

| Service | URL |
|---|---|
| Traefik dashboard | `https://traefik.home.example.com` |
| DDNS target (public) | `vpn.example.com` — not a UI, kept current by ddclient |

## Deploy

```bash
ansible-playbook ansible/site.yml --tags traefik
```

## Notes

**Staging certs:** Set `letsencrypt_staging: true` in `group_vars/all/vars.yml` before the first deploy to avoid hitting Let's Encrypt rate limits while testing. Switch back to `false` and re-deploy once everything is working.

**HTTP redirect:** Traefik automatically redirects all HTTP traffic to HTTPS via the `web` entrypoint configuration.

**New services** are exposed by adding `traefik.enable=true` and the relevant router/service labels to a container on the `proxy` network — no Traefik config changes needed.

**Observability.** Traefik is fully instrumented:
- *Metrics*: Prometheus endpoint on `:8082`, scraped by the monitoring stack. Per-router, per-service, and per-entrypoint labels are enabled.
- *Access logs*: Structured JSON format with a 100-entry write buffer. The `traceID` field in each log entry links to the corresponding trace in Tempo via Grafana's Loki derived fields.
- *Tracing*: OTLP traces sent to Tempo via gRPC (`tempo:4317`). Tempo must be running (monitoring role) and on the `proxy` network before Traefik is restarted, otherwise it retries silently.
