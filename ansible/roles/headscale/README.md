# headscale

Self-hosted Tailscale VPN control plane with a web admin UI.

## Overview

Headscale replaces the Tailscale SaaS control plane, giving full ownership over the mesh VPN. It coordinates device authentication, key exchange, and ACLs for the Tailscale mesh network — actual data plane traffic flows peer-to-peer and never touches this server. Headplane is a web UI layered on top for managing nodes, users, and pre-auth keys without the CLI. Both services sit behind Traefik; the Headscale control plane additionally needs to be reachable from the public internet via `vpn.example.com` for remote device registration. A Postgres database stores node state.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS + DDNS for `vpn.example.com`)
- `keycloak` role running (OIDC for Headplane)
- FritzBox port forwarding: UDP 3478 → `192.168.178.20` (STUN for NAT traversal)

## Containers

| Container | Image | Purpose |
|---|---|---|
| `headscale` | `headscale/headscale:latest` | VPN control plane |
| `headplane` | `ghcr.io/tale/headplane:latest` | Web admin UI |
| `headscale-db` | `postgres:18-alpine` | State database |

Networks: `headscale` and `headplane` join `proxy` (Traefik) and `headscale_internal` (database). The database is not externally routable.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/headscale/docker-compose.yml` | Stack definition |
| `/opt/homelab/services/headscale/config/config.yaml` | Headscale server configuration |
| `/opt/homelab/services/headscale/config/acl.hujson` | Tailnet access policy (`policy.path`) |
| `/opt/homelab/services/headscale/headplane.yaml` | Headplane configuration |

| Variable | Default | Purpose |
|---|---|---|
| `headscale_admins` | philipp's OIDC provider identifier | `group:admins` in the policy: full access to every node and the home LAN |
| `headscale_exit_node_users` | ali's OIDC provider identifier, `vpn-check-exit@` | `group:exit-node` in the policy: may send internet traffic out through the Mini PC's exit node |

**Access policy.** `group:admins` may reach everything, including the whole `192.168.178.0/24` LAN through the Mini PC's route. Every other member (`autogroup:member`) may reach only the Mini PC's LAN address on 443 (Traefik: gym-bro; every other app there requires the Keycloak `admin` role) and 53 (Pi-hole, which answers the split-DNS `*.home` names). A new account therefore gets gym-bro-only access until it's added to `headscale_admins`. Users are referenced by OIDC provider identifier plus `@` (`headscale users list -o json` → `provider_id`), which survives renames.

**Exit node.** The Mini PC advertises itself as exit node (`tailscale-client` role), and `autoApprovers.exitNode` approves it for `group:admins`, so no manual route approval is needed. `group:exit-node` (`headscale_exit_node_users`) may reach `autogroup:internet` through it; admins may already. Headscale 0.29 offers the exit node to every member, but the Mini PC drops internet traffic from anyone outside those two groups. To give an account the exit node, add its `provider_id` to `headscale_exit_node_users`. The user shows up in headscale only after the first sign-in, but the ID is the Keycloak user ID, so it can be read from Keycloak beforehand (`https://auth.<domain>/realms/homelab/<keycloak user id>@`). `vpn-check-exit@` is the local user the check script creates to prove the grant works.

Validate a policy change before deploying it, and prove the result afterwards:

```bash
headscale policy check --file acl.hujson   # inside the headscale container
scripts/check-vpn-acl.sh                   # joins as a throwaway member; exits 1 unless only 443 and 53 on the Mini PC are reachable,
                                           # the member gets no internet through the exit node, and a group:exit-node user does
```

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `headscale_db_password` | `vault_headscale_db_password` | Postgres password |
| `headscale_oidc_secret` | `vault_headscale_oidc_secret` | Keycloak OIDC client secret for Headscale |
| `headplane_api_key` | `vault_headplane_api_key` | Headscale API key for Headplane to manage nodes |
| `headplane_cookie_secret` | `vault_headplane_cookie_secret` | Session cookie signing secret for Headplane |

## URLs

| Service | URL | Access |
|---|---|---|
| Headscale control plane | `https://vpn.example.com` | Public (required for remote node registration) |
| Headplane admin UI | `https://headscale.home.example.com/admin` | LAN / VPN only |

## Deploy

```bash
ansible-playbook ansible/site.yml --tags headscale
```

## Notes

**HTTP/2 disabled on the Headscale router.** The `no-h2@file` TLS option is set in the Traefik label because some Tailscale clients have compatibility issues with HTTP/2 on the control plane endpoint.

**Adding devices:** Use Headplane at `/admin` to generate pre-auth keys, then run `tailscale up --login-server=https://vpn.example.com --authkey=<key>` on the device.

**STUN port 3478 (UDP)** must be forwarded from the FritzBox for NAT traversal to work reliably for remote peers.
