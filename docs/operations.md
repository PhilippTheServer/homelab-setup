# Operations

Day-to-day reference for running and maintaining the homelab.

---

## Update a Service Version

Renovate watches every pin and opens the PR for you — see *Dependency updates* below.
To bump one by hand:

1. Edit the version in `ansible/group_vars/all/vars.yml`
2. Deploy it: `ansible-playbook ansible/site.yml --tags <service>`

Nothing deploys on merge. The repo is the desired state; the playbook is what applies it.

---

## Dependency updates (Renovate)

Renovate runs daily at 05:17 UTC from `.github/workflows/renovate.yml` and opens **one PR
per dependency** — image pins in `group_vars`, Galaxy collections, the Python pins and the
workflow actions. One PR maps to one `--tags <role>` deploy, so a bad bump is reviewed and
reverted on its own.

**Merging a PR does not deploy it.** The sequence is:

```bash
gh pr merge <N> --squash --delete-branch
git checkout main && git pull
ansible-playbook ansible/site.yml --tags <service>
```

Until that last command runs, the repo is ahead of the Mini PC.

**Run it now instead of waiting for the cron:** Actions → Renovate → *Run workflow*. Pick
`debug` for the log level when working out why something was or wasn't proposed.

**A pin Renovate must not touch** stays unannotated in `vars.yml` and goes in `EXCLUDED`
in `scripts/check-renovate-coverage.py` with the reason. CI fails on any pin that is
neither annotated nor excluded, which is what stops a new service from silently never
being updated.

**Rotating the token.** Renovate authenticates with a fine-grained PAT scoped to this
repo alone (`Contents`, `Pull requests`, `Workflows`: read and write). The built-in
`GITHUB_TOKEN` cannot be used: it may not write under `.github/workflows/`, and PRs it
opens do not trigger CI.

```bash
# Create the new token at github.com/settings/personal-access-tokens, then:
gh secret set RENOVATE_TOKEN --repo PhilippTheServer/homelab --app actions
vault kv patch secret/ansible renovate_github_token=-
```

Both read the value from a prompt rather than a flag, keeping it out of shell history.

---

## Release a New Build (Gym Bro / daily)

Gym Bro and daily are built from source rather than pulled from a public registry, so a
release for either is a build-and-push followed by the normal deploy. The role does all
of it — it only builds when the requested tag is missing from Harbor. daily is daily
2.0, deployed by the `daily2` role from the `daily2` repo.

```bash
# 1. Land the change in the app repo (checked out next to this one)
cd ../gym-bro && git push
# or: cd ../daily2 && git push

# 2. Bump the version in ansible/group_vars/all/vars.yml, then:
ansible-playbook ansible/site.yml --tags gym-bro
# or:
ansible-playbook ansible/site.yml --tags daily2
scripts/check-daily2.sh
```

For gym-bro, bump `gym_bro_version`; for daily, bump `daily2_version` — the role
asserts it matches the version in `backend/pyproject.toml` before building, so a
mismatched bump fails fast instead of shipping the wrong tag. `daily2_source_dir`
points at the checked-out `daily2` repo (default: next to this one, override with
`-e daily2_source_dir=/path/to/daily2`). daily builds through the shared
`harbor_image` role.

Rebuild the same tag after a fix that does not warrant a version bump:

```bash
ansible-playbook ansible/site.yml --tags gym-bro -e gym_bro_force_build=true
# or:
ansible-playbook ansible/site.yml --tags daily2 -e daily2_force_build=true
```

**Rolling back** is a version bump in reverse: set `gym_bro_version` (or
`daily2_version`) to the previous tag and re-run. Harbor still holds it, so nothing is
rebuilt.

---

## Restart a Stack

```bash
ssh philipp@192.168.178.20
docker compose -f /opt/homelab/services/<service>/docker-compose.yml restart
```

For Harbor (installer-managed):
```bash
cd /opt/homelab/harbor
docker compose -f docker-compose.yml -f docker-compose.override.yml restart
```

---

## View Logs

```bash
ssh philipp@192.168.178.20
docker compose -f /opt/homelab/services/<service>/docker-compose.yml logs -f
```

Or tail a single container:
```bash
docker logs -f <container-name>
```

---

## Rotate a Secret

1. Generate a new value locally
2. Update it in Vault: `vault kv patch secret/ansible <field>=<new-value>`
3. Re-run the affected role: `ansible-playbook ansible/site.yml --tags <service>`

---

## Unseal HashiCorp Vault (after restart)

Vault seals itself whenever the container restarts. Unseal with 3 of the 5 unseal keys (stored in Vaultwarden):

```bash
docker exec -it vault vault operator unseal
```

Run three times with three different keys. Check status:

```bash
docker exec -it vault vault status
```

---

## SSH into the Mini PC

Vault-signed SSH cert is required. Cert is valid 8 hours.

```bash
# Authenticate and sign (run once per session)
export VAULT_ADDR=https://vault.home.example.com
vault login -method=oidc
vault write -field=signed_key ssh/sign/user \
  public_key="$(cat ~/.ssh/hcvault.pub)" > ~/.ssh/hcvault-cert.pub

# SSH in
ssh minipc.home.example.com
```

See [vault.md](vault.md) for full SSH setup and per-OS instructions.

---

## Add an Account (VPN + gym-bro only)

Every new Keycloak account can use the VPN (gym-bro and DNS on the Mini PC only, see the
headscale README) and sign in to `headscale`, `gym-bro` and its own account page.
Everything else needs the realm role `admin` (see the keycloak README).

1. Store a one-time password:
   `vault kv patch secret/ansible keycloak_<name>_initial_password="$(openssl rand -base64 18)"`
2. Map it in `ansible/group_vars/all/vars.yml` as `vault_keycloak_<name>_initial_password`
   and add the account to `keycloak_users` in `ansible/roles/keycloak/defaults/main.yml`.
   Leave out `admin: true` unless the person should reach everything.
3. `ansible-playbook ansible/site.yml --tags keycloak --check --diff`, then without `--check`.
   The role creates the account once and never touches it again.
4. Hand over the username and `vault kv get -field=keycloak_<name>_initial_password secret/ansible`.
   At first sign-in Keycloak asks for a new password and the missing profile fields
   (email, last name).
5. On their device: install Tailscale, set the coordination server to
   `https://vpn.example.com`, sign in with the Keycloak account, then open
   `https://gym-bro.home.example.com` while the VPN is on.

**Exit node** (all internet traffic out through the home connection): after step 3, add
`https://auth.example.com/realms/homelab/<keycloak user id>@` to
`headscale_exit_node_users` in `ansible/roles/headscale/defaults/main.yml`. The ID is under
Users → the account in the Keycloak admin console. Deploy with `--tags headscale` (dry run
first), then run `scripts/check-vpn-acl.sh`. On the device, the user picks **Exit node →
minipc** in the Tailscale app.

Opening several admin-only apps within a second counts as failed sign-ins and locks the
account for a minute (brute-force protection); it clears on its own.

---

## Register a New Tailscale Device

1. Open Headplane at `https://headscale.home.example.com/admin`
2. Go to **Pre-auth Keys** → create a key (single-use recommended)
3. On the new device:
   ```bash
   tailscale up --login-server=https://vpn.example.com --authkey=<key>
   ```

---

## Push a Docker Image to Harbor

Log in with your OIDC CLI secret (not your Keycloak password directly):

1. In Harbor UI → click your username → **User Profile** → copy **CLI secret**
2. ```bash
   docker login harbor.home.example.com
   # username: <keycloak username>
   # password: <CLI secret from Harbor UI>
   
   docker tag myimage:latest harbor.home.example.com/<project>/myimage:latest
   docker push harbor.home.example.com/<project>/myimage:latest
   ```

The Docker registry endpoint (`registry.home.example.com`) also works for `docker login/push/pull` and points to the same Harbor instance.

Use it for the CLI only. Harbor's web UI has to be opened at `harbor.home.example.com`: its session cookie is host-scoped and the OIDC callback always comes back to `harbor.*`, so a login started on `registry.*` fails with a bare `Bad Request`.

---

## Add a DNS Record for a New Service

Pi-hole handles internal DNS. `*.home.example.com` is not a wildcard — each
hostname needs its own record. Add the hostname to `pihole_dns_hosts` in
`ansible/roles/pihole/defaults/main.yml` (or override it in `group_vars`), then re-run
the role:

```bash
ansible-playbook ansible/site.yml --tags pihole
```

The list is authoritative — the role renders it into Pi-hole's `FTLCONF_dns_hosts`, so
removing a hostname removes its record, and the Pi-hole admin UI shows the records
read-only. After deploying, the role queries Pi-hole for every listed hostname and fails
if one does not resolve to the Mini PC. A hostname served by another machine — such as
`ai.home.example.com`, which points at the atlas dev-lab VM's LAN address —
goes into `pihole_dns_records` as `{host, ip}` instead, and is checked against its own
address. See the [pihole role README](../ansible/roles/pihole/README.md).

---

## Add a New Service (full workflow)

1. Create `services/<name>/docker-compose.yml.j2` (Jinja2 template with Traefik labels)
2. Create `ansible/roles/<name>/tasks/main.yml`:
   - Creates target directory on Mini PC
   - Renders template via `template:` module
   - Runs `docker compose up -d`
3. Add any new secrets to Vault:
   ```bash
   vault kv patch secret/ansible <field>="$(openssl rand -base64 32)"
   ```
4. Add the `vault_*` mapping to `ansible/group_vars/all/vars.yml`
5. Add role to `ansible/site.yml` with a matching tag
6. Create OIDC client in Keycloak if the service supports SSO — add it to
   `services/keycloak/realm-homelab.json.j2` and re-run the `keycloak` role, which
   syncs clients through the Admin API
7. Add Pi-hole DNS record (see above) — `*.home.example.com` is **not** a
   wildcard, so a new hostname does not resolve until its record exists

---

## Force Cert Renewal (Let's Encrypt)

Traefik renews automatically ~30 days before expiry. To force an immediate renewal:

```bash
# Delete the acme.json volume entry for the domain, then restart Traefik
ssh philipp@192.168.178.20
docker restart traefik
```

Traefik will attempt renewal on startup. Check logs:
```bash
docker logs traefik | grep -i acme
```

---

## Troubleshooting

**Can't reach a service at `*.home.example.com`**
- Confirm your device is on the LAN or connected via Headscale VPN
- Check Pi-hole has a DNS record for the hostname pointing to `192.168.178.20`
- Check Traefik dashboard (`https://traefik.home.example.com`) — verify the router is registered

**Let's Encrypt cert not issuing**
- Check Traefik logs: `docker logs traefik | grep -i acme`
- Verify Namecheap API key is correct and the home IP is whitelisted in Namecheap API settings
- Set `letsencrypt_staging: true` in `group_vars/all/vars.yml` and re-deploy to test without hitting rate limits
- See [ddns.md](ddns.md) for the full diagnostic checklist

**Headscale devices can't connect remotely**
- Check ddclient logs: `docker logs ddclient` — confirm A record is current
- Verify `vpn.example.com` resolves to your home IP: `dig vpn.example.com +short`
- Check FritzBox port forwarding: TCP 443 → `192.168.178.20`
- See [ddns.md](ddns.md) for the full diagnostic checklist

**Keycloak OIDC login failing**
- Verify the redirect URI in the Keycloak client matches the service URL exactly
- Check client secret in Vault matches what Keycloak shows under Credentials
- Re-run the affected role after any Vault change

**HashiCorp Vault sealed after reboot**
- Vault seals itself on restart by design — unseal manually with 3 of 5 keys (stored in Vaultwarden):
  ```bash
  docker exec -it vault vault operator unseal
  ```

**GitLab takes forever to start**
- GitLab CE typically takes 3–5 minutes on first boot while it initializes the database and compiles assets. Monitor with:
  ```bash
  docker logs -f gitlab
  ```
