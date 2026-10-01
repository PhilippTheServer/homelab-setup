# MQTT Broker — Design

**Date:** 2026-07-23
**Status:** Approved

## Goal

Add a self-hosted MQTT broker to the homelab for general-purpose pub/sub
("everything" — IoT devices, home automation, and homelab services/scripts).
Reachable from **LAN + Headscale VPN only**, never the public internet.
Connections are **TLS-only** with **username/password** authentication.

## Decisions

| Question | Decision |
|---|---|
| Broker | Eclipse Mosquitto (`eclipse-mosquitto:2.0.22`) — the de-facto standard |
| Exposure | LAN + VPN only; no new FritzBox port |
| Transport security | TLS only (no plaintext listener exposed) |
| TLS termination | **Traefik TCP router** terminates TLS with the existing Let's Encrypt wildcard cert (Approach A) |
| Auth | Single shared account, anonymous disabled |
| Secret storage | Pre-hashed mosquitto passwd line in Vault (`mqtt_passwd`), mirroring `traefik_dashboard_auth` |

## Architecture (Approach A)

```
MQTT client ──TLS:8883──▶ Traefik (mqtt entrypoint)
                          │  HostSNI(`mqtt.home.example.com`)
                          │  terminates TLS with *.home wildcard cert
                          └──plain TCP:1883──▶ mosquitto (proxy network)
                                               allow_anonymous false
                                               password_file (shared account)
```

- Traefik gains a new **`mqtt` entrypoint on `:8883`** and publishes that port.
- A **TCP** router (defined via labels on the mosquitto container) matches
  `HostSNI(\`mqtt.home.example.com\`)`, sets `tls.certresolver=letsencrypt`,
  and forwards the decrypted stream to `mosquitto:1883`.
- Mosquitto runs a **plain listener on 1883**, only on the `proxy` network —
  **not published to the host**. It is never reachable except through Traefik.
- Username/password is enforced by Mosquitto itself; credentials travel inside
  the MQTT CONNECT packet, which Traefik forwards after TLS termination.

### Why Approach A

- Reuses Traefik's existing wildcard cert **and its automatic ACME renewal** —
  no cert-dumping cron, no reload machinery.
- Publicly-trusted Let's Encrypt CA → clients install **no** custom CA; they only
  need to trust the hostname (which resolves via its own per-host Pi-hole record —
  there is no `*.home` wildcard DNS record).
- Mosquitto config stays minimal; consistent with "everything behind Traefik".

Trade-off: clients must send TLS SNI (every modern TLS MQTT client does), and
MQTT depends on Traefik being up (already true for every other HTTP service).

## Components

### New role: `ansible/roles/mqtt/`
- `tasks/main.yml` — thin wrapper delegating to `compose_stack`.
- `README.md` — per repo convention.

### New service templates: `services/mqtt/`
- `docker-compose.yml.j2` — mosquitto container, `proxy` network, TCP-router labels,
  named volumes for data + log.
- `config/mosquitto.conf.j2` — `listener 1883`, `allow_anonymous false`,
  `password_file`, persistence, stdout logging.
- `config/passwd.j2` — renders the pre-hashed `{{ vault_mqtt_passwd }}` line.

### Edits to existing files
- `services/traefik/docker-compose.yml.j2` — add `--entrypoints.mqtt.address=:8883`
  and publish `8883:8883`.
- `ansible/roles/ufw/tasks/main.yml` — allow `8883/tcp`.
- `ansible/group_vars/all/vars.yml` — add `mosquitto_version: "2.0.22"` and the
  `vault_mqtt_passwd` mapping.
- `ansible/site.yml` — add the `mqtt` role (after `traefik`).

### Ownership note
Mosquitto's image runs as uid/gid 1883. To avoid host-dir ownership conflicts,
persistence + logs use **named Docker volumes** (the container owns them). Config
files are bind-mounted read-only at mode `0644` (mosquitto reads them regardless
of owner; the passwd file holds only salted PBKDF2 hashes).

## Secret

`secret/ansible` gains one field:

- `mqtt_passwd` — the full mosquitto passwd line, e.g. `homelab:$7$101$…`,
  generated once with `mosquitto_passwd -b`. The plaintext password is handed to
  the user out-of-band (never committed).

## Deploy

```bash
export VAULT_TOKEN=...
ansible-playbook ansible/site.yml --tags ufw,traefik,mqtt
```

`traefik` re-run adds the entrypoint; `ufw` opens 8883; `mqtt` brings up mosquitto.

## Client usage

```
Host:     mqtt.home.example.com
Port:     8883
TLS:      enabled (system CA trust — no custom CA needed)
Username: homelab
Password: <the plaintext handed over at bootstrap>
```

## Docs to update (per CLAUDE.md)

- `README.md` stack table
- `docs/architecture.md` (service stacks, repo layout, bootstrap order)
- `docs/bootstrap.md` (vault kv command + deploy order)
- `docs/operations.md` (if an ops note is warranted)
- `ansible/roles/mqtt/README.md`

## Out of scope (YAGNI)

- Per-topic ACLs and multiple accounts (single shared account chosen; can layer later)
- Plaintext 1883 exposure and MQTT-over-WebSockets
- Public-internet exposure / bridging to external brokers
