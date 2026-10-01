# Renovate — automated dependency PRs

Refs #103

Renovate runs daily from a GitHub Actions workflow in this repo and opens one pull
request per dependency when a newer version exists. Nothing automerges and nothing
auto-deploys.

## Why this needs a custom manager

Renovate finds zero dependencies in this repo today. The compose files are Jinja2
templates:

```yaml
image: traefik:{{ traefik_version }}
```

and the real pins are Ansible variables in `ansible/group_vars/all/vars.yml`. No built-in
Renovate manager reads a `group_vars` file, and the built-in `ansible` manager only
matches `docker_container` tasks, which this repo does not use.

The supported way through is a **custom regex manager** driven by annotation comments —
the same pattern Renovate's own documentation shows for Ansible variable files. One
manager and one annotation per pin covers every service.

## Architecture

Four managers, three of them built in:

| Manager | Files | Tracks |
| --- | --- | --- |
| `custom.regex` | `ansible/group_vars/all/vars.yml` | 25 image/release pins |
| `ansible-galaxy` | `ansible/requirements.yml` | 3 collections |
| `pip_requirements` | `requirements.txt` | `ansible-core`, `hvac` |
| `github-actions` | `.github/workflows/*.yml` | action pins in our own workflows |

## Annotating the version pins

Every tracked pin in `ansible/group_vars/all/vars.yml` gains a `# renovate:` comment on
the line above it:

```yaml
# ── Service versions (pin these, update deliberately) ──────────────────────────
# renovate: datasource=docker depName=traefik
traefik_version: "v3.7"
# renovate: datasource=docker depName=quay.io/keycloak/keycloak
keycloak_version: "26.6"
# renovate: datasource=github-releases depName=goharbor/harbor
harbor_version: "v2.14.4"
```

The comment is what the regex keys on, which is why `gitlab_homepage_user_id: "2"` — an
unrelated value sitting inside the version block — is never matched.

### The full mapping

| Variable | Image / release | datasource | depName |
| --- | --- | --- | --- |
| `traefik_version` | `traefik` | docker | `traefik` |
| `keycloak_version` | `quay.io/keycloak/keycloak` | docker | `quay.io/keycloak/keycloak` |
| `headscale_version` | `headscale/headscale` | docker | `headscale/headscale` |
| `hcvault_version` | `hashicorp/vault` | docker | `hashicorp/vault` |
| `vaultwarden_version` | `vaultwarden/server` | docker | `vaultwarden/server` |
| `postgres_version` | `postgres` | docker | `postgres` |
| `gitlab_version` | `gitlab/gitlab-ce` | docker | `gitlab/gitlab-ce` |
| `harbor_version` | goharbor release | github-releases | `goharbor/harbor` |
| `pihole_version` | `pihole/pihole` | docker | `pihole/pihole` |
| `homepage_version` | `ghcr.io/gethomepage/homepage` | docker | `ghcr.io/gethomepage/homepage` |
| `grafana_version` | `grafana/grafana` | docker | `grafana/grafana` |
| `prometheus_version` | `prom/prometheus` | docker | `prom/prometheus` |
| `loki_version` | `grafana/loki` **and** `grafana/promtail` | docker | `grafana/loki` |
| `tempo_version` | `grafana/tempo` | docker | `grafana/tempo` |
| `node_exporter_version` | `prom/node-exporter` | docker | `prom/node-exporter` |
| `cadvisor_version` | `gcr.io/cadvisor/cadvisor` | docker | `gcr.io/cadvisor/cadvisor` |
| `paperless_version` | `ghcr.io/paperless-ngx/paperless-ngx` | docker | `ghcr.io/paperless-ngx/paperless-ngx` |
| `jellyfin_version` | `jellyfin/jellyfin` | docker | `jellyfin/jellyfin` |
| `mosquitto_version` | `eclipse-mosquitto` | docker | `eclipse-mosquitto` |
| `miniflux_version` | `miniflux/miniflux` | docker | `miniflux/miniflux` |
| `redis_version` *(new)* | `redis` | docker | `redis` |
| `gotenberg_version` *(new)* | `gotenberg/gotenberg` | docker | `gotenberg/gotenberg` |
| `tika_version` *(new)* | `apache/tika` | docker | `apache/tika` |
| `ddclient_version` *(new)* | `lscr.io/linuxserver/ddclient` | docker | `lscr.io/linuxserver/ddclient` |
| `headplane_version` *(new)* | `ghcr.io/tale/headplane` | docker | `ghcr.io/tale/headplane` |

`loki_version` drives two images on purpose — Loki and Promtail are released as a pair
and the repo already shares one pin between them. The annotation says so in a comment, so
that if the two projects ever diverge the reason to split them is written down.

Three pins need an explicit `versioning=` because the default ordering gets them wrong:

- `pihole_version` (`2026.06.0`) — calendar versioning
- `gitlab_version` (`19.0.2-ce.0`) — the `-ce.0` suffix is not a semver prerelease
- `postgres_version` (`18-alpine`) — the suffix must survive the bump

The exact `versioning=` value for each is settled during implementation by running the
extract check and confirming the proposed update is sane, not by reasoning about it here.

### Never annotated

Renovate cannot touch these, and the coverage check knows they are excluded on purpose:

| Variable | Why |
| --- | --- |
| `gym_bro_version` | self-built Harbor image; bumped to publish a build |
| `daily_version` | same |
| `library_version` | same |
| `metube_version` | deliberately `latest` — a yt-dlp wrapper rots when pinned, already documented in the file |

## Moving the hardcoded images into `group_vars`

Five images are currently written straight into the templates and are invisible to any
single manager. They move into `group_vars` as `*_version` variables, matching the
convention every other service already follows:

| Template | Today | Becomes |
| --- | --- | --- |
| `services/paperless/docker-compose.yml.j2:76` | `redis:7-alpine` | `redis:{{ redis_version }}` |
| `services/paperless/docker-compose.yml.j2:88` | `gotenberg/gotenberg:8` | `gotenberg/gotenberg:{{ gotenberg_version }}` |
| `services/paperless/docker-compose.yml.j2:99` | `apache/tika:latest` | `apache/tika:{{ tika_version }}` |
| `services/traefik/docker-compose.yml.j2:82` | `lscr.io/linuxserver/ddclient:latest` | `lscr.io/linuxserver/ddclient:{{ ddclient_version }}` |
| `services/headscale/docker-compose.yml.j2:29` | `ghcr.io/tale/headplane:latest` | `ghcr.io/tale/headplane:{{ headplane_version }}` |

`jellyfin_version` and `headscale_version` move from `"latest"` to a real tag at the same
time.

### Choosing the initial values

Five of these are `latest` today, so pinning them decides which version the next deploy
pulls. Each is pinned to **the tag currently running on the Mini PC**, read off the host
before the value is written:

```
docker inspect --format '{{.Config.Image}} {{.Image}}' <container>
```

This makes the first `ansible-playbook ansible/site.yml --tags paperless` (and `traefik`,
`headscale`, `jellyfin`) a no-op rather than a surprise upgrade of five containers at
once. Any actual upgrade then arrives as its own reviewable Renovate PR, which is the
entire point.

If a running tag cannot be resolved to a published version, that image is pinned to the
newest release instead and the deviation is called out in the PR body — not silently
rounded up.

## `renovate.json5`

At the repo root. The decisions that matter:

- **One PR per dependency.** No grouping. One PR maps to one
  `ansible-playbook ansible/site.yml --tags <role>` deploy, so a bad bump is reviewed,
  deployed and reverted in isolation.
- **`separateMinorPatch: true`** and majors in their own PR with a `major` label, because
  a Keycloak major and a Keycloak patch are not the same risk.
- **`prConcurrentLimit: 10`, `prHourlyLimit: 0`.** The daily run is the throttle; the
  concurrency cap stops a first run from opening 25 PRs at once.
- **No `automerge` anywhere.** Merging is manual, and so is deploying.
- **No `schedule` inside the config.** The Actions cron is the single place the timing
  lives; duplicating it in the Renovate config gives two sources of truth that drift.

## `.github/workflows/renovate.yml`

`renovatebot/github-action` on a daily cron plus `workflow_dispatch`, so a run can be
triggered by hand without waiting for tomorrow. `RENOVATE_REPOSITORIES` is scoped to this
repo alone. Renovate's own version is pinned in the workflow — and, because the
`github-actions` manager is enabled, Renovate keeps that pin current itself.

The repository cache is restored and saved around the run so a daily job does not re-fetch
every datasource from scratch.

### Authentication

A **fine-grained personal access token**, stored as the `RENOVATE_TOKEN` Actions secret,
scoped to `PhilippTheServer/homelab` only, with `contents: write`, `pull requests: write`
and `workflows: write`.

The built-in `GITHUB_TOKEN` was considered and rejected. It cannot push changes under
`.github/workflows/**` — there is no `workflows:` permission that a workflow can grant
itself, it is a GitHub security boundary — so the action pins in our own workflows could
never be updated. More importantly, pull requests opened by `GITHUB_TOKEN` do not trigger
other workflows, which would mean the coverage check below never runs on the very PRs it
exists to validate.

**Secret handling.** The token is a GitHub Actions secret and is never written to a file,
template, playbook or variable in this repo. `CLAUDE.md` mandates Vault at
`secret/ansible` for secrets, so the token is also recorded there
(`vault kv patch secret/ansible renovate_github_token="..."`) to keep Vault the single
recoverable source of truth. It deliberately does **not** get a `vault_*` mapping in
`ansible/group_vars/all/vars.yml`: no playbook consumes it, and an unused variable that
resolves a Vault lookup on every run is cost without a reader. This is a conscious
deviation from the "add the mapping" step in `CLAUDE.md` and is noted here so it reads as
a decision rather than an oversight.

Rotation is documented in `docs/operations.md`.

## Verification

`renovate-config-validator` only checks that the config matches a schema. By the standard
in the `verification-standards` skill, a linter is not verification — it would pass just
as happily against a config whose regex matches nothing at all.

The behavioral check is **`scripts/check-renovate-coverage.py`**:

1. Parse `ansible/group_vars/all/vars.yml` for every `*_version` key.
2. Run `renovate --platform=local --dry-run=extract` against the checkout. This runs
   extraction only — no network lookups, no platform access, no PRs.
3. Assert every `*_version` key was extracted as a dependency, except the four documented
   exclusions.
4. Exit non-zero naming any pin Renovate cannot see.

This satisfies the standard because it fails on the current code — with no `customManagers`
configured, extraction finds zero dependencies — and passes once the managers and
annotations exist. It also catches the regression that actually matters over time: a new
service is added to `group_vars` and nobody writes the `# renovate:` line, so it silently
never updates. The check fails the moment that happens.

`renovate-config-validator` runs too, as a fast schema gate before the slower extract.
It is a supplement, not the check.

### Known unknown

Reading the per-dependency list out of the dry-run output needs `LOG_FORMAT=json` parsing
that has not been run yet. If that output proves unstable across Renovate versions, the
fallback is to assert annotation coverage directly — every non-excluded `*_version` has a
`# renovate:` line — *and* assert the extract run reports a dependency count equal to the
expected number. That is still behavioral rather than schema-only, but less precise about
which pin is missing. Which of the two is used gets settled by running it, and the PR body
records what was actually run.

### `.github/workflows/ci.yml`

Runs the coverage check on `push` to `main` and on `pull_request`. Because Renovate
authenticates with a PAT, its own PRs trigger this workflow — so every version bump is
checked before merge.

This is the first CI in the repo. It is scoped to the Renovate check only; adding
`ansible-lint` or template-rendering checks is out of scope here and belongs to its own
issue.

## Documentation, in the same change

| File | Change |
| --- | --- |
| `README.md` | how dependency updates arrive, and that merging does not deploy |
| `docs/operations.md` | reviewing a Renovate PR, deploying the role after merge, PAT rotation, triggering a run by hand |
| `docs/bootstrap.md` | the `vault kv patch` line for `renovate_github_token` |
| `CLAUDE.md` | new services must carry a `# renovate:` annotation, or be added to the exclusion list with a reason |
| `docs/architecture.md` | repo layout gains `.github/` |

## Out of scope

- **Automerge.** Every PR is reviewed and merged by hand.
- **Auto-deploy on merge.** The repo sits ahead of the Mini PC until the playbook runs.
  Closing that gap is a real question but a different one.
- **Broader CI.** `ansible-lint`, template rendering and idempotence checks are worth
  having and are not this change.
- **`metube_version`.** Stays on `latest`, for the reason already written in the file.
