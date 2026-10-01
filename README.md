# Homelab

Deliberately over-engineered self-hosted infrastructure on a single mini PC running Debian 13. Everything is Infrastructure as Code — no manual steps after initial host setup.

---

## Stack

Services are listed in setup priority order — the order in which they should be configured.

| Priority | Service | Role | URL |
|---|---|---|---|
| 1 | **Keycloak** | SSO / OIDC identity provider — all services authenticate here | `auth.example.com` |
| 2 | **Traefik** | Reverse proxy, wildcard SSL (Let's Encrypt via Namecheap DNS) | `traefik.home.example.com` |
| 2 | **Headscale** | Self-hosted Tailscale VPN control plane | `vpn.example.com` (public, DDNS) |
| 3 | **HashiCorp Vault** | Secrets management, SSH certificate authority | `vault.home.example.com` |
| 3 | **Vaultwarden** | Self-hosted Bitwarden-compatible password manager | `bw.home.example.com` |
| 4 | **Pi-hole** | DNS + DHCP, ad/tracker blocking, internal name resolution | `http://192.168.178.20:8080` (no Traefik) |
| 4 | **GitLab CE** | Git hosting + CI/CD pipelines | `gitlab.home.example.com` |
| 4 | **Harbor** | Docker image registry | `harbor.home.example.com` (UI) · `registry.home.example.com` (CLI) |
| 4 | **Homepage** | Homelab dashboard | `dash.home.example.com` |
| 4 | **Paperless-ngx** | Document management & OCR | `paper.home.example.com` |
| 4 | **Jellyfin** | Media server — stream movies, TV, and music | `media.home.example.com` |
| 4 | **MeTube** | yt-dlp web UI — YouTube audio, video and podcasts into the Jellyfin libraries | `ytdl.home.example.com` |
| 4 | **Monitoring** | Grafana + Prometheus + Loki — metrics and log aggregation | `monitoring.home.example.com` |
| 4 | **MQTT** | Eclipse Mosquitto broker — TLS + password pub/sub for IoT & services | `mqtt.home.example.com:8883` (MQTT over TLS) |
| 5 | **Gym Bro** | Workout tracker — built from source, images stored in Harbor | `gym-bro.home.example.com` |
| 6 | **daily** | daily 2.0 (role `daily2`), health and diet journal — frontend, backend, a sync from gym-bro, and a public, IP-restricted MCP endpoint for claude.ai | `daily.home.example.com` · `daily-mcp.example.com` (public, DDNS) |
| 6 | **library** | RSS reader — a Miniflux feed engine behind a purpose-built reading UI | `library.home.example.com` |

All services (except Pi-hole) sit behind Traefik with a wildcard Let's Encrypt cert (`*.home.example.com`). Each service stack is self-contained with its own Postgres (and Redis where needed) — stacks can be rebuilt or replaced independently.

**Keycloak**, **Headscale** and **daily** are the services that sit at the apex domain (not under `.home.`), each for its own reason: Keycloak so OIDC redirect URIs work from any device, including those not on the LAN or VPN; Headscale and daily because they expose a public endpoint directly to the internet (see Access Model below).

---

## Access Model

**Three ports are open on the FritzBox** (TCP 443, TCP 80, UDP 3478), forwarded to the Mini PC. Everything else is LAN/VPN only.

- **On the local network** — `*.home.example.com` resolves via Pi-hole to the Mini PC's LAN IP (`192.168.178.20`)
- **Remotely via VPN** — Headscale (self-hosted Tailscale) provides a private mesh network

**Three hostnames are reachable directly from the public internet, each for its own reason:**

Headscale's control plane is reachable from the internet via `vpn.example.com`, kept current by ddclient (Namecheap DDNS). Traefik terminates TLS directly — no tunnel or third-party proxy sits in front of it.

**auth.example.com** (Keycloak) is also reachable directly from the public internet, so OIDC redirects work from any device — including one that isn't on the LAN or VPN yet, such as during first-time VPN sign-in.

**daily-mcp.example.com** is also reachable directly from the public internet: TLS terminates at Traefik on 443, and only `/mcp` and `/.well-known/oauth-protected-resource…` are routed through to `daily2-backend` (daily 2.0) — nothing else on the service is exposed. An `ipallowlist` middleware restricts inbound traffic to Anthropic's outbound range (`160.79.104.0/21`), the home LAN (`192.168.178.0/24`), and the Headscale VPN mesh (`100.64.0.0/10`); a `ratelimit` middleware caps it at 20 req/s (burst 40). The allowlist is `mcp_allowed_sources` in `group_vars`. See the [daily2 role README](ansible/roles/daily2/README.md) for details.

**All other services are never reachable from the public internet.**

---

## Shared documentation

atlas documentation lives only in [PhilippTheServer/atlas](https://github.com/PhilippTheServer/atlas),
vendored here at `docs/atlas`. Nothing in this repository documents atlas. Run
`git submodule update --init` if that directory is empty.

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Network diagram, access model, service stack details, traffic flows |
| [docs/bootstrap.md](docs/bootstrap.md) | Step-by-step first deploy guide |
| [docs/ddns.md](docs/ddns.md) | DDNS setup, Namecheap config, cert issuance, verification & troubleshooting |
| [docs/vault.md](docs/vault.md) | Vault CLI setup, SSH certs, secret management, Ansible integration |
| [docs/operations.md](docs/operations.md) | Day-to-day: updates, restarts, logs, secret rotation, adding services |

### Dependency updates

Renovate runs daily and opens one PR per dependency when a newer version is available —
image pins, Ansible collections, Python pins and the workflow actions. **Merging a PR does
not deploy it**; run `ansible-playbook ansible/site.yml --tags <service>` afterwards. See
[docs/operations.md](docs/operations.md#dependency-updates-renovate).

Each Ansible role also has its own README:

| Role | README |
|---|---|
| common | [ansible/roles/common/README.md](ansible/roles/common/README.md) |
| ufw | [ansible/roles/ufw/README.md](ansible/roles/ufw/README.md) |
| docker-log-limit | [ansible/roles/docker-log-limit/README.md](ansible/roles/docker-log-limit/README.md) |
| traefik | [ansible/roles/traefik/README.md](ansible/roles/traefik/README.md) |
| keycloak | [ansible/roles/keycloak/README.md](ansible/roles/keycloak/README.md) |
| headscale | [ansible/roles/headscale/README.md](ansible/roles/headscale/README.md) |
| hcvault | [ansible/roles/hcvault/README.md](ansible/roles/hcvault/README.md) |
| vaultwarden | [ansible/roles/vaultwarden/README.md](ansible/roles/vaultwarden/README.md) |
| pihole | [ansible/roles/pihole/README.md](ansible/roles/pihole/README.md) |
| gitlab | [ansible/roles/gitlab/README.md](ansible/roles/gitlab/README.md) |
| harbor | [ansible/roles/harbor/README.md](ansible/roles/harbor/README.md) |
| homepage | [ansible/roles/homepage/README.md](ansible/roles/homepage/README.md) |
| paperless | [ansible/roles/paperless/README.md](ansible/roles/paperless/README.md) |
| jellyfin | [ansible/roles/jellyfin/README.md](ansible/roles/jellyfin/README.md) |
| metube | [ansible/roles/metube/README.md](ansible/roles/metube/README.md) |
| monitoring | [ansible/roles/monitoring/README.md](ansible/roles/monitoring/README.md) |
| mqtt | [ansible/roles/mqtt/README.md](ansible/roles/mqtt/README.md) |
| gym-bro | [ansible/roles/gym-bro/README.md](ansible/roles/gym-bro/README.md) |
| library | [ansible/roles/library/README.md](ansible/roles/library/README.md) |
| daily2 | [ansible/roles/daily2/README.md](ansible/roles/daily2/README.md) |

---

## Prerequisites

On your **local machine** (where you run Ansible) — set up a project virtualenv
with [uv](https://docs.astral.sh/uv/) from the repo root (where `ansible.cfg` lives):

```bash
uv venv                                                         # creates .venv
uv pip install -r requirements.txt                              # ansible-core + hvac (latest, pinned)
.venv/bin/ansible-galaxy collection install -r ansible/requirements.yml
source .venv/bin/activate
```

- uv — `brew install uv`
- HashiCorp Vault CLI — `brew install hashicorp/tap/vault`
- A Vault-signed SSH cert for the hosts (see [docs/vault.md](docs/vault.md)); the
  Mini PC trusts the Vault SSH CA, so no static key in `~/.ssh/authorized_keys` is
  needed once it is provisioned

On the **Mini PC** (one-time manual steps before first Ansible run):

```bash
apt install openssh-server -y
useradd -m -s /bin/bash philipp
usermod -aG sudo philipp
mkdir -p /home/philipp/.ssh
echo "YOUR_PUBLIC_KEY" >> /home/philipp/.ssh/authorized_keys
chmod 700 /home/philipp/.ssh && chmod 600 /home/philipp/.ssh/authorized_keys
chown -R philipp:philipp /home/philipp/.ssh
```

On **Namecheap** (before running Ansible):
1. DDNS enabled for the domain — DDNS password noted
2. API access enabled — home IP whitelisted
3. A record `vpn.example.com` created

On **FritzBox** (before deploying Traefik):

Navigate to **http://fritz.box → Internet → Permit Access → Port Sharing**, target `192.168.178.20`:

| Protocol | Port | Purpose |
|----------|------|---------|
| TCP | 443 | Traefik HTTPS / Headscale |
| TCP | 80 | Let's Encrypt HTTP fallback |
| UDP | 3478 | STUN for Tailscale NAT traversal |

---

## Setup

### 1. Configure inventory

Edit [ansible/inventory/hosts.yml](ansible/inventory/hosts.yml) to set target device.

### 2. Set non-secret variables

Edit [ansible/group_vars/all/vars.yml](ansible/group_vars/all/vars.yml) to change service versions or other config variables.

### 3. Populate secrets in HashiCorp Vault

All secrets live at `secret/ansible` in HashiCorp Vault. Ansible fetches them at runtime — nothing sensitive is stored in this repo.

First, install the required Ansible collection:

```bash
ansible-galaxy collection install -r ansible/requirements.yml
```

Then store all secrets (run from your Mac after `vault login -method=oidc`):

```bash
vault kv put secret/ansible \
  minipc_passwd="..." \
  namecheap_api_user="..." \
  namecheap_api_key="..." \
  namecheap_ddns_password="..." \
  traefik_dashboard_auth="..." \
  pihole_webpassword="..." \
  keycloak_admin_user="admin" \
  keycloak_admin_password="..." \
  keycloak_alice_initial_password="$(openssl rand -base64 18)" \
  keycloak_bob_initial_password="$(openssl rand -base64 18)" \
  keycloak_ali_initial_password="$(openssl rand -base64 18)" \
  keycloak_db_password="..." \
  hcvault_oidc_secret="PLACEHOLDER" \
  vaultwarden_db_password="..." \
  vaultwarden_admin_token="..." \
  vaultwarden_oidc_secret="PLACEHOLDER" \
  headscale_db_password="..." \
  headscale_oidc_secret="PLACEHOLDER" \
  headplane_api_key="PLACEHOLDER" \
  headplane_cookie_secret="..." \
  gitlab_root_password="..." \
  gitlab_oidc_secret="PLACEHOLDER" \
  gitlab_api_token="PLACEHOLDER" \
  harbor_admin_password="..." \
  harbor_db_password="..." \
  harbor_oidc_secret="PLACEHOLDER" \
  homepage_oidc_secret="PLACEHOLDER" \
  homepage_nextauth_secret="..." \
  paperless_db_password="$(openssl rand -base64 32)" \
  paperless_secret_key="$(openssl rand -base64 50)" \
  paperless_admin_password="$(openssl rand -base64 32)" \
  paperless_oidc_secret="PLACEHOLDER" \
  paperless_api_token="PLACEHOLDER" \
  jellyfin_oidc_secret="PLACEHOLDER" \
  jellyfin_api_key="PLACEHOLDER" \
  gym_bro_db_password="$(openssl rand -hex 32)"
```

Fields marked `PLACEHOLDER` are filled in after Keycloak is running (OIDC secrets) or after the relevant service is deployed (headplane_api_key, gitlab_api_token). See [docs/bootstrap.md](docs/bootstrap.md) for the full step-by-step.

<details>
<summary>Password generation reference</summary>

```bash
# Strong random password (use for any "..." above)
openssl rand -base64 32

# Vaultwarden admin token
openssl rand -hex 32

# Traefik dashboard auth (needs apache2-utils)
htpasswd -nB philipp

# Namecheap API key: Profile → Tools → API Access
# Namecheap DDNS password: Domain List → Manage → Advanced DNS → Dynamic DNS
# OIDC secrets: filled in after Keycloak is running — copy from Keycloak client credentials
# headplane_api_key: generated after Headscale is running — headscale apikeys create
# gitlab_api_token: generated after GitLab is running — User Settings → Access Tokens
```

</details>

---

## Repo Layout

```
homelab/
├── ansible/
│   ├── inventory/
│   │   └── hosts.yml              # Mini PC connection details
│   ├── group_vars/all/
│   │   └── vars.yml               # config (domain, versions, IPs) + Vault lookups
│   ├── roles/
│   │   ├── common/                # Docker, deploy user, shared network
│   │   ├── ufw/                   # UFW firewall rules
│   │   ├── docker-log-limit/      # Docker daemon log rotation
│   │   ├── traefik/               # reverse proxy + SSL + ddclient DDNS
│   │   ├── keycloak/              # SSO
│   │   ├── headscale/             # VPN
│   │   ├── hcvault/               # HashiCorp Vault
│   │   ├── vaultwarden/           # Bitwarden-compatible password manager
│   │   ├── pihole/                # DNS + DHCP
│   │   ├── gitlab/                # Git + CI/CD
│   │   ├── harbor/                # Docker registry
│   │   ├── homepage/              # Dashboard
│   │   ├── paperless/             # Document management
│   │   ├── jellyfin/              # Media server
│   │   └── monitoring/            # Metrics + logs
│   └── site.yml                   # master playbook
├── services/
│   ├── traefik/                   # includes ddclient DDNS sidecar
│   ├── keycloak/
│   ├── headscale/
│   ├── hcvault/
│   ├── vaultwarden/
│   ├── pihole/
│   ├── gitlab/
│   ├── harbor/
│   ├── homepage/
│   ├── paperless/
│   ├── jellyfin/
│   ├── monitoring/
│   └── gym-bro/
├── docs/
│   ├── architecture.md
│   ├── bootstrap.md
│   ├── ddns.md
│   ├── vault.md
│   └── operations.md
├── scripts/
│   ├── check-keycloak-access.py
│   ├── check-renovate-coverage.py # fails if a version pin is invisible to Renovate
│   ├── check-pinned-tags.py       # fails if a pinned image tag does not exist
│   ├── check-vpn-acl.sh
│   └── check-daily2.sh            # post-deploy smoke check of daily (the daily2 stack)
├── .github/workflows/
│   ├── renovate.yml               # opens dependency PRs daily
│   └── ci.yml                     # runs the coverage check on every PR
├── renovate.json5                 # custom manager for the group_vars version pins
└── README.md
```

---

## How It Works

```
Ansible (local machine)
  └── renders Jinja2 templates → Docker Compose files on the Mini PC
  └── runs docker compose up -d per stack
  └── all secrets fetched at runtime from HashiCorp Vault (KV at secret/ansible)

After bootstrap:
  GitLab CI → re-deploys stacks on git push (Ansible only needed for host-level changes)
  CI/CD authenticates to Vault via AppRole → fetches secrets → runs playbook
```
