# DDNS & External Access

How `vpn.example.com` is kept reachable from the internet despite a dynamic home IP, and how TLS certificates are issued for all homelab domains.

---

## Architecture

### Public services (`vpn.`, `auth.`, `daily-mcp.`)

```
External client
    │ HTTPS (443)
    ▼
Namecheap DNS  ←─── ddclient updates A record every 5 min
    │ resolves vpn.example.com → home public IP
    ▼
FritzBox  ←─── port forwarding: TCP 443, TCP 80, UDP 3478 → 192.168.178.20
    ▼
Traefik (192.168.178.20:443)  ←─── TLS termination, Let's Encrypt cert
    ▼
headscale:8080 (Docker proxy network)
```

No reverse proxy or tunnel sits between the client and the server.
Traefik terminates TLS directly; the public IP is the home router's WAN address.

### Internal services (`*.home.example.com`) — remote access via VPN

```
Remote client (connected to Headscale VPN)
    │ DNS query for *.home.example.com
    ▼
Headscale split DNS → nameserver 192.168.178.20 (Pi-hole on home LAN)
    │ resolves *.home.example.com → 192.168.178.20
    ▼
Tailscale subnet route: 192.168.178.0/24 advertised by minipc node
    │ routes traffic through VPN tunnel to home LAN
    ▼
Traefik (192.168.178.20:443)  →  internal service
```

The Mini PC runs the Tailscale client (`tailscale-client` role) and advertises `192.168.178.0/24` as a subnet route. Remote devices must have `--accept-routes` enabled to use it. Without the subnet route, the split DNS nameserver (`192.168.178.20`) is unreachable from outside and `*.home.example.com` does not resolve.

---

## Components

### ddclient — IP address updater

**Image:** `lscr.io/linuxserver/ddclient:latest`  
**Config:** `/opt/homelab/services/traefik/ddclient.conf` (rendered by Ansible from `services/traefik/ddclient.conf.j2`)

Every 5 minutes ddclient fetches the current public IPv4 from `icanhazip.com` and calls Namecheap's DDNS endpoint to update the A record for each host configured in `ddclient.conf` — currently `vpn`, `auth` and `daily-mcp`. If the IP has not changed since the last update, Namecheap ignores the call. Each host record must already exist in Namecheap (Step 1 of `docs/bootstrap.md`) — ddclient updates a record's value, it does not create one.

The DDNS update uses a separate **DDNS password** (not the Namecheap account password and not the API key). It is found at:
> Namecheap → Domain List → Manage `example.com` → Advanced DNS → Dynamic DNS

```
# ddclient.conf (simplified)
protocol=namecheap
server=dynamicdns.park-your-domain.com
login=example.com      # domain, not username
password=<vault_namecheap_ddns_password>
vpn                             # updates vpn.example.com
```

Check status:
```bash
docker logs ddclient
```

### Traefik — TLS termination & reverse proxy

**Image:** `traefik:v3.7`  
**Entrypoints:** `:80` (HTTP → redirect to HTTPS), `:443` (HTTPS)

Traefik issues and renews all TLS certificates via Let's Encrypt using the **Namecheap DNS-01 challenge**. Let's Encrypt asks Traefik to temporarily create a `_acme-challenge` TXT record in Namecheap DNS to prove domain ownership. DNS-01 is required because:
- The wildcard cert `*.home.example.com` can only be issued via DNS challenge
- Internal services (`*.home.example.com`) are not publicly reachable, so HTTP-01 challenge cannot be used for them

**Certificates issued:**

| Domain | Type | Used by |
|--------|------|---------|
| `vpn.example.com` | individual | Headscale |
| `daily-mcp.example.com` | individual | daily's public MCP endpoint |
| `home.example.com` + `*.home.example.com` | wildcard | all internal services |

Certs are stored in the `traefik_letsencrypt` Docker volume (`acme.json`) and renewed automatically ~30 days before expiry.

### FritzBox — port forwarding

Navigate to **http://fritz.box → Internet → Permit Access → Port Sharing**. All rules target `192.168.178.20`:

| Protocol | External port | Purpose |
|----------|--------------|---------|
| TCP | 443 | Traefik HTTPS / Headscale |
| TCP | 80 | Let's Encrypt HTTP (fallback) |
| UDP | 3478 | STUN — Tailscale NAT traversal |

FritzBox creates both an IPv4 NAT rule and an IPv6 firewall allow rule from a single port sharing entry, so the same rules cover both protocols.

---

## Required Credentials

All secrets live in HashiCorp Vault at `secret/ansible` and are fetched at runtime via the `community.hashi_vault` Ansible lookup.

| Vault field | What it is | Where to find it |
|----------------|-----------|-----------------|
| `namecheap_api_user` | Namecheap account username | Namecheap login |
| `namecheap_api_key` | Namecheap API key | Profile → Tools → API Access |
| `namecheap_ddns_password` | DDNS password (separate from API key) | Domain List → Manage → Advanced DNS → Dynamic DNS |

---

## Namecheap Prerequisites

### API access (for Let's Encrypt DNS challenge)

1. Go to **Profile → Tools → API Access**
2. Confirm your API key is visible
3. Under **Whitelisted IPs**, add your home public IP:
   ```bash
   curl -4 -s https://icanhazip.com
   ```
4. If your IP changes and cert renewal fails, update the whitelist and Traefik will retry on the next renewal cycle. Let's Encrypt certs are valid for 90 days; Traefik starts renewing at 60 days, so there is a 30-day window to fix a stale whitelist.

### DDNS enabled

1. Go to **Domain List → Manage `example.com` → Advanced DNS**
2. Ensure **Dynamic DNS** is toggled on
3. The DDNS password shown there must match `namecheap_ddns_password` in Vault

---

## Ansible Deployment

The traefik Ansible role renders both the docker-compose and the ddclient config:

```
services/traefik/
├── docker-compose.yml.j2        → /opt/homelab/services/traefik/docker-compose.yml
├── ddclient.conf.j2             → /opt/homelab/services/traefik/ddclient.conf
└── dynamic/
    └── tls-options.yaml.j2      → /opt/homelab/services/traefik/dynamic/tls-options.yaml
```

Deploy:
```bash
ansible-playbook ansible/site.yml --tags traefik
```

---

## Verification

```bash
# 1. ddclient updated the A record
docker logs ddclient | tail -20

# 2. DNS resolves to home IP
dig vpn.example.com +short
curl -4 -s https://icanhazip.com   # must match

# 3. Traefik serves a valid Let's Encrypt cert
curl -sv https://vpn.example.com/key?v=138 2>&1 | grep -E "subject|issuer|< HTTP"

# 4. Headscale WebSocket handshake (the definitive Tailscale test)
curl --http1.1 -sv \
  -H "Upgrade: websocket" -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  https://vpn.example.com/ts2021 2>&1 | grep "< HTTP"
# Expected: HTTP/1.1 101 Switching Protocols
```

---

## Troubleshooting

**ddclient reports wrong IP / not updating**
```bash
docker exec ddclient ddclient -verbose -noquiet
```
If `icanhazip.com` returns a `100.x.x.x` address, your ISP is using CGNAT for IPv4 and external IPv4 access is not possible — IPv6 is required instead.

**Let's Encrypt cert request fails**
- Check Traefik logs: `docker logs traefik | grep -i acme`
- Most likely cause: home IP not in Namecheap API whitelist
- Fix: add current IP at Profile → Tools → API Access → Whitelisted IPs

**Port forwarding not working**
```bash
# From an external machine
curl -sv https://vpn.example.com/key?v=138 2>&1 | grep "< HTTP"
# If connection refused: FritzBox port forward missing or wrong target IP
# If TLS error: Traefik is reachable but cert issue
```
