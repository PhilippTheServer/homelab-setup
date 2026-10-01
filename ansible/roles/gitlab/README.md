# gitlab

Git hosting and CI/CD pipelines.

## Overview

GitLab CE provides the primary Git remote and CI/CD system for the homelab. After initial bootstrap, GitLab CI takes over redeployment duties: on every push to `main`, a pipeline authenticates to HashiCorp Vault via AppRole, fetches secrets, and runs the Ansible playbook — so Ansible on a local machine is only needed for host-level changes. CI jobs require a separately provisioned GitLab Runner; no runner is deployed by this role. Self-registration is disabled; all login goes through Keycloak OIDC. SSH access for `git push/pull` is on port 2222 to avoid conflicting with the host SSH daemon.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running (OIDC SSO)

## Containers

| Container | Image | Purpose |
|---|---|---|
| `gitlab` | `gitlab/gitlab-ce:19.0.2-ce.0` | GitLab application server |

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/gitlab/docker-compose.yml` | Stack definition including all `GITLAB_OMNIBUS_CONFIG` settings |

All GitLab configuration (OIDC, Puma workers, Sidekiq concurrency, SSH port, etc.) is embedded in the `GITLAB_OMNIBUS_CONFIG` environment variable inside the compose file.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `gitlab_root_password` | `vault_gitlab_root_password` | Initial root password (first run only) |
| `gitlab_oidc_secret` | `vault_gitlab_oidc_secret` | Keycloak OIDC client secret |

## URL

`https://gitlab.home.example.com`

SSH: `git clone ssh://git@gitlab.home.example.com:2222/<group>/<repo>.git`

## Deploy

```bash
ansible-playbook ansible/site.yml --tags gitlab
```

## Notes

**Initial startup is slow.** GitLab CE typically takes 3–5 minutes to become responsive on first boot while it initializes the database and assets. Monitor with `docker logs -f gitlab`.

**CI/CD runners** are not deployed by this role. Provision a GitLab Runner separately and register it against this instance before pipelines can run.

**Admin access** must be granted manually — GitLab CE 19 does not support automatic admin promotion via OIDC group membership (`omniauth_admin_groups` was removed in GitLab 16.1). Use the Rails runner or log in as `root`:

```bash
docker exec gitlab gitlab-rails runner 'User.find_by(username: "philipp").update!(admin: true)'
```

**Memory tuning:** Puma workers (2), Puma threads (1–4), and Sidekiq concurrency (5) are set conservatively for a 16 GB host shared with other services. Prometheus monitoring is disabled to reduce overhead.

**SSH port:** Git operations use port 2222. Add to `~/.ssh/config`:

```
Host gitlab.home.example.com
    Port 2222
```
