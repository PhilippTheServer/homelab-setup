# harbor_image

Internal helper role: build an application from source on the Mini PC and publish it to Harbor.

## Overview

`harbor_image` holds the build-and-publish steps for services built from source rather
than pulled from a public registry. Service roles call it via `include_role` before
deploying their stack with `compose_stack`. It:

1. ensures the Harbor project exists
2. asks Harbor whether `harbor_image_version` is already published, for each component
3. if any is missing (or `harbor_image_force_build`), tars the source on the control
   machine, unpacks it on the Mini PC, builds each component there and pushes
   `<registry>/<project>/<component>:<version>` and `:latest`
4. logs the deploy user in to Harbor, so `docker compose pull` works even when nothing
   was built

Building on the target keeps the images native `amd64`. Used by `daily2`.
`gym-bro` and `library` still carry their own copy of these steps.

This is an internal building block invoked by other roles. It is not listed in
`site.yml` and has no tag of its own.

## Prerequisites

- `harbor` role running (registry + API)
- Docker Engine on the target (provided by `common`)
- The application source checked out on the control machine, with a
  `version = "x.y.z"` line in `harbor_image_version_file`

## Containers

N/A. The role builds images and deploys no containers.

## Configuration

Variables (set by the caller via `include_role: vars:`):

| Variable | Default | Purpose |
|---|---|---|
| `harbor_image_name` | — (**required**) | Name used in task names, the tarball and the default build dir |
| `harbor_image_project` | — (**required**) | Harbor project holding the images |
| `harbor_image_version` | — (**required**) | Tag to build and publish |
| `harbor_image_components` | — (**required**) | Components; each becomes the image `<project>/<component>` |
| `harbor_image_source_dir` | — (**required**) | Source on the control machine |
| `harbor_image_version_file` | — (**required**) | File (relative to the source) whose `version = "…"` line must equal `harbor_image_version` |
| `harbor_image_source_repo` | — (**required**) | Where to clone the source from, for the error message |
| `harbor_image_registry` | `registry.home.example.com` | Harbor CLI endpoint |
| `harbor_image_api` | `https://harbor.home.example.com/api/v2.0` | Harbor API |
| `harbor_image_build_dir` | `/opt/homelab/build/<name>` | Where the source is unpacked and built |
| `harbor_image_context_prefix` | `""` | Each component builds from `<build_dir>/<prefix><component>` |
| `harbor_image_force_build` | `false` | Rebuild and overwrite an existing tag |

## Secrets

| Vault field | Variable | Purpose |
|---|---|---|
| `harbor_admin_password` | `vault_harbor_admin_password` | Harbor API calls, image pushes and pulls (owned by the `harbor` role) |

## URL

N/A. Internal helper role.

## Deploy

Not deployed directly. Invoked from a service role, e.g.:

```yaml
- name: daily2 | build and publish the images
  ansible.builtin.include_role:
    name: harbor_image
  vars:
    harbor_image_name: daily2
    harbor_image_source_repo: github.com/PhilippTheServer/daily
    harbor_image_source_dir: "{{ daily2_source_dir }}"
    harbor_image_version_file: backend/pyproject.toml
    harbor_image_project: "{{ daily2_harbor_project }}"
    harbor_image_components: "{{ daily2_components }}"
    harbor_image_version: "{{ daily2_version }}"
```

## Notes

- **Check mode queries Harbor for real** (a read-only GET), so a dry run reports the
  true build decision. It creates no project and ships, builds or pushes nothing.
- **A missing source fails the dry run** when a build is needed. A dry run that reports
  green while the real apply would fail on a missing checkout is worse than none.
- **The working tree is shipped**, not a commit: build from a clean checkout of the
  released version.
- **Idempotence:** a run that finds every tag in Harbor changes nothing. A second run
  after a build must report `changed=0` for this role.
