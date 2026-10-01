# monitoring

Full observability stack: Grafana + Prometheus + Loki + Tempo.

## Overview

This role deploys a complete observability stack as a single Docker Compose stack. Grafana is the unified UI for metrics (Prometheus), logs (Loki), and traces (Tempo). All access to Grafana is via Keycloak SSO — the login form is disabled and the browser redirects directly to Keycloak on every visit. Prometheus, Loki, and Tempo are internal-only containers; they are never exposed through Traefik.

Traefik sends structured JSON access logs (captured by Promtail) and OTLP traces (sent directly to Tempo) so every HTTP request is visible across all three pillars. Grafana's datasource provisioning wires trace↔log and trace↔metric correlation automatically.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination, metrics endpoint, and OTLP tracing enabled)
- `keycloak` role running (OIDC SSO)

## Containers

| Container | Purpose | Port (internal) |
|---|---|---|
| `grafana` | Dashboard UI — metrics, logs, traces; SSO via Keycloak | 3000 |
| `prometheus` | Metrics scraper + TSDB (30-day retention); remote write receiver for Tempo | 9090 |
| `loki` | Log aggregation — receives logs from Promtail | 3100 |
| `promtail` | Docker log shipper — tails all container logs → Loki | 9080 |
| `tempo` | Distributed tracing backend — OTLP receiver, 48h retention | 3200 (HTTP), 4317 (gRPC), 4318 (HTTP OTLP) |
| `node-exporter` | Host metrics (CPU, memory, disk, network) | 9100 |
| `cadvisor` | Per-container resource metrics | 8080 |

## Configuration

| File | Purpose |
|---|---|
| `/opt/homelab/services/monitoring/docker-compose.yml` | Stack definition |
| `/opt/homelab/services/monitoring/prometheus/prometheus.yml` | Scrape targets (includes Tempo self-metrics) |
| `/opt/homelab/services/monitoring/loki/loki.yml` | Loki single-binary config (filesystem storage) |
| `/opt/homelab/services/monitoring/promtail/promtail.yml` | Docker log discovery and shipping config |
| `/opt/homelab/services/monitoring/tempo/tempo.yml` | Tempo single-binary config — OTLP receivers, metrics generator |
| `/opt/homelab/services/monitoring/grafana/provisioning/datasources/datasources.yml` | Auto-configures Prometheus, Loki, and Tempo datasources with correlation |
| `/opt/homelab/services/monitoring/grafana/provisioning/dashboards/dashboards.yml` | Dashboard file provider pointing to `/etc/grafana/dashboards` |
| `/opt/homelab/services/monitoring/grafana/dashboards/*.json` | Pre-provisioned dashboards — downloaded by Ansible at deploy time |

Prometheus retains 30 days of metrics. Loki uses on-disk TSDB storage under a named Docker volume. Tempo retains traces for 48 hours and pushes service-graph and span-metrics into Prometheus via remote write.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `grafana_admin_password` | `vault_grafana_admin_password` | Bootstrap admin password (emergency access via API only — login form is disabled) |
| `grafana_oidc_secret` | `vault_grafana_oidc_secret` | Keycloak OIDC client secret |

## URL

`https://monitoring.home.example.com`

## Deploy

```bash
# Add secrets first (one-time)
vault kv patch secret/ansible \
  grafana_admin_password="$(openssl rand -base64 32)" \
  grafana_oidc_secret="PLACEHOLDER"

# Wire Keycloak client, copy the secret, then patch:
vault kv patch secret/ansible grafana_oidc_secret="<secret-from-keycloak>"

ansible-playbook ansible/site.yml --tags monitoring
```

## Notes

**SSO is enforced.** `GF_AUTH_DISABLE_LOGIN_FORM=true` and `GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN=true` mean the browser goes directly to Keycloak. The admin password in Vault is only useful for API access (`Authorization: Basic`). To temporarily re-enable the login form for emergency recovery, set `GF_AUTH_DISABLE_LOGIN_FORM=false` and redeploy.

**Role mapping.** Keycloak realm role `admin` → Grafana `Admin`. All other authenticated users get `Viewer`. To promote a user to Editor, assign them the `editor` Keycloak role and update the `GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH` expression, then redeploy.

**Traefik metrics.** The role expects `--metrics.prometheus=true`, `--metrics.prometheus.addRoutersLabels=true`, `--metrics.prometheus.addServicesLabels=true`, `--metrics.prometheus.addEntryPointsLabels=true`, and `--entrypoints.metrics.address=:8082` in the Traefik command. These flags are included in the Traefik role's `docker-compose.yml`. Re-run `--tags traefik` if Traefik was deployed before this role.

**Traefik tracing.** Traefik sends OTLP traces directly to Tempo via gRPC (`tempo:4317` on the `proxy` network). Tempo is attached to both `proxy` and `internal` networks. Traefik's JSON access logs include a `traceID` field — Grafana's Loki datasource uses a derived field to turn it into a clickable link to the corresponding trace.

**Dashboards.** Three community dashboards are downloaded once, when their file is missing (`get_url` would otherwise query grafana.com on every run): Node Exporter Full (ID 1860), Traefik v3 (ID 17346) and Traefik Loki (ID 13713, datasource and job selector fixed up after download). Two are kept in this repo under `services/monitoring/grafana/dashboards/` and copied on every run: Container Logs and Keycloak. Additional dashboards can be added by placing JSON files in `/opt/homelab/services/monitoring/grafana/dashboards/` — Grafana picks them up within 30 seconds without a restart.

**Keycloak dashboard.** Prometheus scrapes Keycloak's management port (`keycloak:9000/metrics`, job `keycloak`) over the `proxy` network. The dashboard (uid `homelab-keycloak`, filterable by realm and client) has six rows:

- **Overview:** status, uptime, sign-ins, failed sign-ins, success rate, tokens issued, event errors, distinct users.
- **Authentication:** events and errors per client over time, per-client totals, password checks.
- **Security:** a sign-in log and a failure log with user, client and IP; failed sign-ins by user and IP; lockouts; rejected client requests.
- **HTTP:** requests by outcome, latency percentiles, 5xx, slowest and busiest endpoints.
- **Runtime:** JVM heap, CPU, GC, threads, DB connection pool, request workers, container memory.
- **Event log:** every Keycloak event.

Event counts come from Keycloak's event log in Loki, not from `keycloak_user_events_total`: Keycloak creates each counter series on its first event, so `increase()` never sees that first step, and a single rare event would count as zero. The event metrics feed the realm and client filters. After deploying, the role fails unless Prometheus has the `keycloak` target up, `keycloak_user_events_total` exists, and Loki holds Keycloak INFO event lines from the last hour. The Keycloak side is described in the keycloak role README.

**Tempo metrics generator.** Tempo generates service-graph and span-metrics from traces and pushes them into Prometheus via remote write (`http://prometheus:9090/api/v1/write`). Prometheus must be started with `--web.enable-remote-write-receiver` (already included).

**Loki log retention.** There is no default retention policy. To add one, set `retention_period` under `limits_config` in `loki.yml.j2` and re-run the role.
