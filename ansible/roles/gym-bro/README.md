# gym-bro

Self-hosted workout tracker — templates, live sessions, and progress tracking.

## Overview

Deploys the [gym-bro](https://github.com/PhilippTheServer/gym-bro) application: an
Angular PWA served by nginx, a FastAPI backend, and a dedicated Postgres.

Unlike the other service roles, the images are not pulled from Docker Hub — they are
built from source and published to the self-hosted Harbor registry. The role:

1. ensures the `gym-bro` project exists in Harbor
2. asks Harbor whether `gym_bro_version` is already published
3. if it is not, ships the source to the Mini PC, builds both images there, and pushes
   them to `registry.home.example.com`
4. deploys the compose stack, which pulls those images

Building on the target rather than the control machine keeps the images native `amd64`
— the control machine is Apple Silicon, and cross-building the Angular bundle under
emulation is slow and needlessly fragile.

Publishing a new build is a version bump in `group_vars/all/vars.yml`. To rebuild
without bumping (after a fix), pass `-e gym_bro_force_build=true`.

The frontend container terminates the app *and* the API path: nginx serves the Angular
bundle and reverse-proxies `/api/` to the backend over the internal network. The browser
therefore only ever talks to one origin, so there is no CORS configuration and no API
hostname compiled into the bundle. Only the frontend carries Traefik labels.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `keycloak` role running — the `gym-bro` client must exist in the `homelab` realm
- `harbor` role running (image registry)
- The application source checked out on the control machine. By default the role
  expects it next to this repo:

  ```
  ~/code/homelab
  ~/code/gym-bro      ← git clone git@github.com:PhilippTheServer/gym-bro.git
  ```

  Override with `-e gym_bro_source_dir=/path/to/gym-bro` if it lives elsewhere.

## Containers

| Container | Image | Purpose |
|---|---|---|
| `gym-bro-frontend` | `registry.home.example.com/gym-bro/frontend` | nginx — serves the Angular PWA and proxies `/api/` to the backend |
| `gym-bro-backend` | `registry.home.example.com/gym-bro/backend` | FastAPI, 4 uvicorn workers; runs Alembic migrations at start; healthcheck on `/health` |
| `gym-bro-db` | `postgres` | Application database |

`gym-bro-backend` is attached to the `proxy` network despite having no Traefik labels:
the `internal` network has no egress, and the API must reach Keycloak's JWKS endpoint to
verify tokens.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `gym_bro_version` | `1.2.0` (in `group_vars`) | Image tag to build/deploy |
| `gym_bro_source_dir` | `{{ playbook_dir }}/../../gym-bro` | Application source on the control machine |
| `gym_bro_registry` | `registry.home.example.com` | Harbor CLI endpoint |
| `gym_bro_harbor_project` | `gym-bro` | Harbor project holding the images |
| `gym_bro_build_dir` | `/opt/homelab/build/gym-bro` | Where the source is unpacked and built |
| `gym_bro_force_build` | `false` | Rebuild and overwrite an existing tag |

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/gym-bro/docker-compose.yml` | The stack definition |

Keycloak is not configured by this role — the `gym-bro` public client lives in
`services/keycloak/realm-homelab.json.j2` and is applied by the `keycloak` role.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `gym_bro_db_password` | `vault_gym_bro_db_password` | Application Postgres password |

The role also reads `vault_harbor_admin_password` (owned by the `harbor` role) to
authenticate image pushes and pulls. The app itself holds no OIDC client secret — the
frontend is a public client using PKCE.

## URL

`https://gym-bro.home.example.com`

## Deploy

```bash
ansible-playbook ansible/site.yml --tags gym-bro
```

The deploy waits up to five minutes (`compose_wait`) for all three containers to
report healthy, and fails the play if they don't. A backend whose migrations fail
never passes its healthcheck, so a broken release fails the deploy instead of
passing it.

Dry run first. Check mode queries Harbor for the tag, so it reports the real build
decision and the compose diff, but it creates no Harbor project and ships, builds or
pushes nothing:

```bash
ansible-playbook ansible/site.yml --tags gym-bro --check --diff
```

Rebuild the images without bumping the version:

```bash
ansible-playbook ansible/site.yml --tags gym-bro -e gym_bro_force_build=true
```

## Notes

**Publishing a new version.** Release the version in gym-bro first (its README,
"Releasing"), then set `gym_bro_version` in `ansible/group_vars/all/vars.yml` to the same
value and re-run the role. Before building, the role checks that `gym_bro_version` equals
`version` in the source's `gym-bro-backend/pyproject.toml`, and fails if it doesn't, so a
stale checkout is never published under a new tag. Harbor keeps every tag, so
rolling back is a matter of setting the variable to the previous value and re-running —
no rebuild happens, because that tag is already published.

That holds only between versions with the same Alembic head. An older image does not
know a newer revision, so `alembic upgrade head` in its entrypoint fails and the backend
never starts. `1.1.0` added `0002_exercise_taxonomy` and `0003_template_rep_range`, so
going back to `1.0.0` means restoring a pre-upgrade `pg_dump` of `gym-bro-db` (or
running `alembic downgrade 0001_initial_schema` in the `1.1.0` backend) before reverting
the variable. Take the dump before deploying a version that adds a migration. Because
the deploy waits for the stack to be healthy, reverting without that step fails the play
rather than leaving a crash-looping backend behind.

**Migrations run in the container entrypoint**, not in the application's startup hook.
uvicorn runs four workers; running schema creation per worker raced and crashed one of
them on a cold database.

**The `/export` route (since 1.2.0).** `gym-bro-backend` exposes a read-only export of a
user's workout data, added for the `daily` app's sync. The route is reachable via Traefik
at `https://gym-bro.home.example.com/api/v1/export/workouts` (because
`gym-bro-frontend`'s nginx proxies all of `/api/` to the backend), as well as directly
by other containers over the shared `proxy` network. The only gate is a client-credentials
access token check: the token's `azp` (client id) must match `EXPORT_CLIENT_ID`
(`daily-gymbro-sync`, the confidential Keycloak client defined in
`services/keycloak/realm-homelab.json.j2`). The route accepts any `user_id` query param
and serves the data for that user; any other token, including a normal user's, is
rejected. See the `daily2` role README ("The gym-bro sync") for the calling side.

**The exercise library is seeded on every start** (`RUN_SEED: "true"`). The seed matches
on exercise name and only inserts what is missing, so it is safe to leave enabled and it
restores the built-in library if rows are deleted.

**Traefik drops unhealthy containers from the router entirely.** If the app returns a
404 rather than a 502, check `docker inspect gym-bro-frontend` for its health status —
Traefik removes the route rather than serving a broken backend.

**First login.** Any user in the Keycloak `homelab` realm can sign in; there is no
separate authorisation step. Each user's templates, sessions and progress are private to
them — the API scopes every query by the token subject.
