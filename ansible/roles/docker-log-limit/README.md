# docker-log-limit

Caps Docker container log storage to 5 MB per container via the daemon's global log options.

## Overview

Writes `/etc/docker/daemon.json` with the `json-file` log driver configured to rotate at 5 MB and keep a single log file. This limits each container's on-disk log footprint to 5 MB and applies to every container on the host — no per-container labels needed. Docker is restarted automatically if the config changes; running containers are brought back up by their `restart: always` policy.

## Prerequisites

- `common` role applied (Docker installed and running)

## Containers

None. This role only changes the Docker daemon configuration.

## Configuration

| File | Purpose |
|---|---|
| `/etc/docker/daemon.json` | Global Docker daemon log driver and rotation options |

## Secrets

None. This role has no secret dependencies.

## URL

None. This role exposes no web interface.

## Deploy

```bash
ansible-playbook ansible/site.yml --tags docker-log-limit
```

## Notes

**Running containers:** Restarting the Docker daemon briefly stops all containers. They are automatically restarted by their `restart: always` policy. Expect a few seconds of downtime if services are running.

**Existing logs:** The limit applies to new log output only. Pre-existing log files that exceed 5 MB are not truncated retroactively. To clear them: `docker compose down && docker compose up -d`.
