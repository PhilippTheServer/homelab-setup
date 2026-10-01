# common

Base host configuration — Docker, deploy user, and shared Docker network.

## Overview

This role runs first and prepares the Mini PC for all other service roles. It installs Docker CE with the Compose plugin, adds the deploy user to the `docker` group, creates the base directory structure under `/opt/homelab/services`, and creates the shared `proxy` Docker network that every service stack joins. Firewall setup is handled by the separate `ufw` role.

## Prerequisites

- Debian-based host with `apt`
- SSH access as root or a user with sudo privileges
- The deploy user (`philipp`) must already exist on the host

## What It Installs

| Package / Resource | Purpose |
|---|---|
| `docker-ce`, `docker-ce-cli`, `containerd.io` | Docker engine |
| `docker-buildx-plugin`, `docker-compose-plugin` | Build and Compose support |
| Docker network `proxy` | Shared network — all Traefik-routed containers attach here |
| Directory `/opt/homelab/services` | Base path for all service stacks |

## Secrets

None. This role has no secret dependencies.

## Deploy

```bash
ansible-playbook ansible/site.yml --tags common
```

## Notes

The `common` role is idempotent but only needs to run once per host. After first setup it is commented out in `site.yml` to avoid unnecessary overhead on every deploy. Re-enable it if provisioning a fresh host or after an OS reinstall.
