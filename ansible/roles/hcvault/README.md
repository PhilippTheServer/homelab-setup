# hcvault

HashiCorp Vault — secrets management, dynamic credentials, and SSH certificate authority.

## Overview

HashiCorp Vault is the secrets backbone of the homelab. All Ansible secrets are stored here in a KV v2 store and fetched at runtime — nothing sensitive lives in this repo. Beyond static secrets, Vault acts as an SSH certificate authority: it signs short-lived SSH certificates so that no static keys need to be distributed to the Mini PC. The `configure.yml` task file runs after startup to provision all engines, auth methods, policies, and roles idempotently: KV v2 at `secret/`, OIDC auth backed by Keycloak, AppRole auth for CI/CD pipelines, and the SSH CA.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running (OIDC for Vault login)
- `VAULT_TOKEN` environment variable set to the root token before running the playbook

## Containers

| Container | Image | Purpose |
|---|---|---|
| `vault` | `hashicorp/vault:2.0` | Secrets engine |

The container runs with `IPC_LOCK` capability to prevent secrets from being swapped to disk.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/hcvault/docker-compose.yml` | Stack definition |
| `/opt/homelab/services/hcvault/config/vault.hcl` | Vault server configuration (storage, listener, cluster address) |

## Vault Configuration (applied by `configure.yml`)

| Resource | Path | Purpose |
|---|---|---|
| KV v2 secrets engine | `secret/` | All homelab secrets |
| OIDC auth method | `auth/oidc/` | Login via Keycloak (`admin` role, 7-day token TTL) |
| AppRole auth method | `auth/approle/` | Machine auth for CI/CD pipelines (1h TTL) |
| SSH secrets engine | `ssh/` | Certificate authority for SSH access |
| Policy `admin` | — | Full access to all paths, including `patch` (so `vault kv patch` is a single HTTP PATCH) |
| Policy `ci-cd` | — | Read `secret/data/ansible`, sign `ssh/sign/ci-cd` |
| SSH role `user` | `ssh/roles/user` | Sign user certs (8h TTL, pty + port-forwarding) |
| SSH role `ci-cd` | `ssh/roles/ci-cd` | Sign CI/CD certs (30m TTL) |

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `hcvault_oidc_secret` | `vault_hcvault_oidc_secret` | Keycloak OIDC client secret for Vault |

The root token is passed via the `VAULT_TOKEN` environment variable, not stored in Vault itself.

## URL

`https://vault.home.example.com`

## Deploy

```bash
export VAULT_TOKEN=<root-token>
ansible-playbook ansible/site.yml --tags hcvault
```

Dry run first, with the same `VAULT_TOKEN` exported. The seal check and the SSH CA
key read are read-only and run in check mode too, so the dry run aborts on a sealed
Vault and shows the real `/etc/ssh/vault-ca.pub` diff. A change there restarts sshd.

```bash
ansible-playbook ansible/site.yml --tags hcvault --check --diff
```

The role refuses to write anything but an SSH public key to `/etc/ssh/vault-ca.pub`;
an empty file there would reject every Vault-signed SSH certificate.

## Notes

**Vault seals on restart.** Vault seals itself whenever the container restarts. Unseal manually with 3 of the 5 unseal keys:

```bash
docker exec -it vault vault operator unseal
```

Run three times with three different keys. Long-term, configure auto-unseal with a cloud KMS.

**SSH CA workflow (per session):**

```bash
vault login -method=oidc
SIGNED=$(vault write -field=signed_key ssh/sign/user public_key="$(cat ~/.ssh/hcvault.pub)")
echo "$SIGNED" > ~/.ssh/hcvault-cert.pub
ssh minipc.home.example.com
```

**CI/CD AppRole credentials** are fetched once and stored as CI secret variables:

```bash
vault read -field=role_id auth/approle/role/ci-cd/role-id
vault write -field=secret_id -f auth/approle/role/ci-cd/secret-id
```
