# mqtt

Self-hosted MQTT broker (Eclipse Mosquitto) with username/password auth.

## Overview

Mosquitto is a lightweight MQTT broker for general-purpose pub/sub — IoT devices,
home automation, and homelab services/scripts. It is reachable from the **LAN and
Headscale VPN only**, never the public internet.

MQTT is a raw TCP protocol, so it does not use Traefik's HTTP routing. Instead,
Traefik exposes a dedicated **`mqtt` entrypoint on `:8883`** and a **TCP router**
terminates TLS there using the shared `*.home` Let's Encrypt wildcard cert, then
forwards the decrypted stream to Mosquitto's plain `1883` listener on the internal
`proxy` network. Because the cert is publicly-trusted, clients need no custom CA —
just the hostname (which resolves via its own per-host Pi-hole record — there is
no `*.home` wildcard DNS record). Connections are
**TLS-only**; the `1883` listener is never published to the host. Authentication is
enforced by Mosquitto with a single shared account (anonymous disabled).

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running with the `mqtt` entrypoint (`:8883`) — deploy/redeploy `traefik`
- `ufw` role allowing `8883/tcp`

## Containers

| Container | Image | Purpose |
|---|---|---|
| `mosquitto` | `eclipse-mosquitto:2.0.22` | MQTT broker |

Networks: `mosquitto` joins `proxy` only. Its `1883` listener is reachable solely
through Traefik; the port is not published to the host.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/mqtt/docker-compose.yml` | Stack definition + TCP-router labels |
| `/opt/homelab/services/mqtt/config/mosquitto.conf` | Broker config (listener, auth, persistence) |
| `/opt/homelab/services/mqtt/config/passwd` | Mosquitto password file (rendered from Vault, owned `1883:1883` mode `0700`) |

Persistence and logs use the named volumes `mosquitto_data` and `mosquitto_log`.
The container runs as its own uid/gid (`user: "1883:1883"`) so the image entrypoint
skips its root-only `chown -R /mosquitto`; the password file is therefore pre-rendered
readable by uid 1883 before the stack comes up, and the named volumes inherit `1883`
ownership from the image.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `mqtt_passwd` | `vault_mqtt_passwd` | Full Mosquitto passwd line (`user:$7$…`), pre-hashed |

Generate the value once (the plaintext password is handed to clients out-of-band):

```bash
docker run --rm eclipse-mosquitto:2.0.22 \
  sh -c 'mosquitto_passwd -b /tmp/pw homelab "<plaintext>" >/dev/null && cat /tmp/pw'
# → homelab:$7$101$...   (store this whole line)
vault kv patch secret/ansible mqtt_passwd='homelab:$7$101$...'
```

## URL

`mqtt.home.example.com:8883` (MQTT over TLS — not a web URL)

## Deploy

```bash
ansible-playbook ansible/site.yml --tags ufw,traefik,mqtt
```

`traefik` adds the `:8883` entrypoint, `ufw` opens the port, `mqtt` brings up Mosquitto.

## Notes

**Client configuration:**

```
Host:     mqtt.home.example.com
Port:     8883
TLS:      enabled (system CA trust — no custom CA needed)
Username: homelab
Password: <the plaintext handed over at bootstrap>
```

**TLS-only.** There is no plaintext listener exposed. Clients must connect with TLS
and send SNI (all modern TLS MQTT clients — paho, Home Assistant, MQTT Explorer — do).

**Single shared account.** Anonymous access is disabled. To add per-topic ACLs or
multiple accounts later, extend `mosquitto.conf` with an `acl_file` and add users to
the passwd file.

**Rotating the password:** regenerate the passwd line (see Secrets), update the Vault
field, and re-run `--tags mqtt`.
