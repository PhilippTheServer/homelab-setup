# tailscale-client

Installs and configures the Tailscale client on the Mini PC as a subnet router.

## Overview

The Mini PC joins the Headscale mesh as a node and advertises the home LAN subnet (`192.168.178.0/24`) to all other peers. This makes Traefik at `192.168.178.20` reachable from any device connected to the VPN — which is required for split DNS and `*.home.example.com` to work remotely.

It is also an exit node: members of `group:exit-node` (see the headscale README) can send all their internet traffic out through the home connection.

## Prerequisites

- `headscale` role running (`vpn.example.com` reachable)

## Containers

None. Tailscale runs as a native systemd service (`tailscaled`).

## Configuration

The role installs Tailscale, starts `tailscaled`, persists IPv4 forwarding (`/etc/sysctl.d/99-tailscale.conf`) and, once the node is logged in, advertises it as exit node (`tailscale set --advertise-exit-node`, skipped when `0.0.0.0/0` is already advertised). Headscale approves the exit node through `autoApprovers` in the tailnet policy. Authentication and subnet advertisement are done manually after the first deploy (see Deploy section). Re-run the role after that step to advertise the exit node.

## Secrets

None. Authentication is performed interactively on the machine.

## URL

No web UI. Manage the node via Headplane at `https://headscale.home.example.com/admin`.

## Deploy

**Step 1 — install Tailscale:**

```bash
ansible-playbook ansible/site.yml --tags tailscale-client
```

**Step 2 — authenticate on the Mini PC:**

```bash
ssh philipp@192.168.178.20
tailscale up --login-server=https://vpn.example.com \
             --advertise-routes=192.168.178.0/24 \
             --hostname=minipc
# Prints a URL — open it on any device and log in with your Keycloak account
```

**Step 3 — approve the subnet route:**

```bash
docker exec -it headscale headscale routes list
docker exec -it headscale headscale routes enable -r <route-id>
```

**Step 4 — enable route acceptance on remote devices:**

```bash
tailscale up --accept-routes
```

## Notes

**Subnet route approval is manual.** Headscale requires explicit approval of the advertised LAN route. This is a one-time step and survives re-deploys. The exit node routes are approved automatically.

**IPv6 forwarding is off.** The exit node advertises `::/0` too, but the host doesn't forward IPv6: turning it on would stop the host accepting router advertisements. Exit-node clients get IPv4 only.
