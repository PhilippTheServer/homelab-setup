# compose_stack

Internal helper role: render a service's templates and converge its Docker-Compose stack.

## Overview

`compose_stack` factors out the deploy boilerplate that every Docker service role used
to repeat (create dir → render `docker-compose.yml.j2` → `docker compose up -d`). Service
roles call it via `include_role` and pass per-service variables. The stack is brought up
with the `community.docker.docker_compose_v2` module, which **reports changes correctly**
(unlike the old `command: docker compose up -d` + `changed_when: false`) and recreates
containers whose compose definition changed — so no per-role `restart` handler is needed.
For services whose containers only re-read a *bind-mounted config file* on restart, set
`compose_restart_services` to restart them when such a file changes.

This is an internal building block invoked by other roles — it is not listed in
`site.yml` and has no tag of its own.

## Prerequisites

- `community.docker` collection (declared in `ansible/requirements.yml`)
- Docker Engine + the `docker compose` CLI plugin on the target (provided by `common`)
- `deploy_user` and `homelab_base_dir` defined (in `group_vars/all/vars.yml`)

## Containers

N/A — this role deploys whatever the calling service's compose file defines; it owns no
containers of its own.

## Configuration

Variables (set by the caller via `include_role: vars:`):

| Variable | Default | Purpose |
|---|---|---|
| `compose_service` | — (**required**) | Service name; the repo dir `services/<name>/` and host dir `services/<name>/`. |
| `compose_dirs` | `[""]` | Subdirs to create under the service dir (`""` = the dir itself). |
| `compose_extra_dirs` | `[]` | Absolute dirs to create (e.g. media mounts outside `services/`). |
| `compose_dir_mode` | `0750` | Mode for created dirs; set `0755` when a container user must read bind-mounted config dirs. |
| `compose_templates` | compose file only | List of `{src, dest, mode?, preserve_perms?}` templates to render. `preserve_perms: true` renders content only and leaves ownership/mode unmanaged — use when the file's perms are owned by its own container (e.g. linuxserver images chown their bind-mounted config). |
| `compose_recreate` | `auto` | `docker_compose_v2` recreate policy. |
| `compose_pull` | `missing` | Image pull policy (`missing` matches `docker compose up -d`). |
| `compose_wait` | `false` | Wait for every container to be running, and healthy where it has a healthcheck; fail the play otherwise. |
| `compose_wait_timeout` | `300` | Seconds to wait when `compose_wait` is on. |
| `compose_restart_services` | `[]` | Services that read bind-mounted config files; restarted when their container started before the newest rendered config file was written. |

## Secrets

N/A — secrets are referenced inside the calling service's templates, not by this role.

## URL

N/A — internal helper role.

## Deploy

Not deployed directly. Invoked from a service role, e.g.:

```yaml
- name: Deploy homepage compose stack
  ansible.builtin.include_role:
    name: compose_stack
  vars:
    compose_service: homepage
    compose_dirs: ["", "config", "images"]
    compose_templates:
      - { src: config/settings.yaml.j2, dest: config/settings.yaml }
      - { src: docker-compose.yml.j2, dest: docker-compose.yml }
    compose_restart_services: ["homepage"]
```

## Notes

- **No handlers / no `notify`.** Convergence happens in-task; the deploy step recreates
  on compose change, and `compose_restart_services` handles config-only reloads. This
  avoids a templated `notify` that would break for roles that have dropped their handler.
- **Config restarts are decided by time.** After the deploy, each service in
  `compose_restart_services` whose container started before the stack's newest rendered
  config file is restarted (the dry run reports them). It used to fire only when this
  run's templates changed *and* the deploy changed nothing, so any other recreated
  service in the stack suppressed it, and a later run never caught up (#71).
- **First run after migrating a role** typically reports `changed: true` (the module
  reflecting real state). A second run must report `changed=0` — that is the idempotency
  acceptance test.
- Pass per-call data via `include_role: vars:` (task-scoped), never `set_fact`
  (host-scoped — it would leak into the next role).
