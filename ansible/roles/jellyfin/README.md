# jellyfin

Self-hosted media server for streaming movies, TV shows, and music.

## Overview

Jellyfin streams locally stored media to any device via a browser or native app. It handles transcoding, subtitle extraction, chapter thumbnails, and user-specific watch progress. Configuration and metadata are stored in a named Docker volume; the media library is a read-only bind mount from `{{ homelab_base_dir }}/media/library` on the host. Jellyfin has no external database dependency — it uses its own internal SQLite store inside the config volume.

Authentication defaults to local accounts. SSO via Keycloak can be added post-deploy using the [Jellyfin SSO plugin](https://github.com/9p4/jellyfin-plugin-sso) — see Notes.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)

## Containers

| Container | Image | Purpose |
|---|---|---|
| `jellyfin` | `jellyfin/jellyfin` | Media server + transcoding |

Networks: joins `proxy` only (Traefik). No internal network needed — Jellyfin has no companion services.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/jellyfin/docker-compose.yml` | Stack definition |

Role variables (`defaults/main.yml`):

| Variable | Purpose |
|---|---|
| `jellyfin_media_trees` | The two sibling trees built under the media root — `library` and `incoming` |
| `jellyfin_libraries` | Every library, as a path relative to each tree |
| `jellyfin_library_types` | Jellyfin content type per library — documentation only, used to generate `NAMING.md` |
| `jellyfin_url` | Jellyfin's own API, called from the Mini PC to converge library options |

`jellyfin_media_root` (`/opt/homelab/media`) lives in `group_vars/all/vars.yml` rather
than here, because the `metube` role writes into the same tree.

Media directories created by Ansible:

| Path | Purpose |
|---|---|
| `/opt/homelab/media/library` | Library tree — mounted read-only into Jellyfin at `/media` |
| `/opt/homelab/media/incoming` | Staging tree — deliberately **not** mounted |
| `/opt/homelab/media/NAMING.md` | Generated naming guide, kept outside `library/` so it is never scanned |

Everything under both trees is derived from `jellyfin_libraries`, so adding a library is
a one-line change plus a role re-run. Creating a directory by hand instead leaves the
next run unaware of it.

### Layout

```
/opt/homelab/media/
├── NAMING.md
├── incoming/     films/  series/  anime/{films,series}/  documentaries/  music/  audiobooks/  podcasts/  youtube/
└── library/      films/  series/  anime/{films,series}/  documentaries/  music/  audiobooks/  podcasts/  youtube/
```

Uploads land in `incoming/<kind>/`, get renamed to convention, then move into
`library/<kind>/`. Both trees share a filesystem, so the move is atomic and Jellyfin
never scans a half-transferred file. Because only `library/` is bind-mounted, the
container cannot see the staging tree at all.

### Libraries

Each is added once in the admin UI — Jellyfin has no configuration-file route for this.

| Library | Content type | Path to enter in the UI |
|---|---|---|
| Films | Movies | `/media/films` |
| Series | Shows | `/media/series` |
| Anime Films | Movies | `/media/anime/films` |
| Anime Series | Shows | `/media/anime/series` |
| Documentaries | Movies | `/media/documentaries` |
| Music | Music | `/media/music` |
| Audiobooks | Books | `/media/audiobooks` |
| Podcasts | Books | `/media/podcasts` |
| YouTube | Home Videos and Photos | `/media/youtube` |

Anime is split across two libraries because a library folder may only hold one content
type. Podcasts are a *Books* library rather than *Music* because Jellyfin remembers the
playback position in books, and a three-hour episode is rarely heard in one go. Naming conventions live in `/opt/homelab/media/NAMING.md` on the host, rendered
from `services/jellyfin/NAMING.md.j2`.

## Secrets

All secrets live in HashiCorp Vault at `secret/data/ansible`.

| Vault field | Variable | Purpose |
|---|---|---|
| `jellyfin_oidc_secret` | `vault_jellyfin_oidc_secret` | Keycloak OIDC client secret (SSO plugin, configured post-deploy via UI) |
| `jellyfin_api_key` | `vault_jellyfin_api_key` | API key for the Homepage dashboard widget, and for this role's library-options convergence |

Both are set to `PLACEHOLDER` on initial deploy and filled in after Jellyfin is running.

**API key** — generate in Jellyfin admin UI → Dashboard → API Keys → + , then store in Vault and re-run the homepage role:

```bash
vault kv patch secret/ansible jellyfin_api_key="<api-key>"
ansible-playbook ansible/site.yml --tags jellyfin,homepage
```

Until that key is real, the library-options task answers 401 and no-ops rather than
failing the play, so a first bootstrap is not blocked on it.

**OIDC secret** — after Keycloak is running, create the `jellyfin` OIDC client, copy the secret from Keycloak → Credentials tab, then patch Vault:

```bash
vault kv patch secret/ansible jellyfin_oidc_secret="<keycloak-client-secret>"
```

The OIDC secret is used when configuring the SSO plugin through the Jellyfin admin UI (see Notes). There is no compose-level env var for it.

## URL

`https://media.home.example.com`

## Deploy

```bash
ansible-playbook ansible/site.yml --tags jellyfin
```

## Notes

**Initial setup:** On first visit, the Jellyfin setup wizard runs. Create the admin account, add libraries pointing to subdirectories of `/media`, and let the initial scan complete.

**Media directory:** Drop uploads onto the host at `/opt/homelab/media/incoming/<kind>/` (e.g. via `scp`, `rsync`, or Samba), rename them to the conventions in `NAMING.md`, then `mv` them into the matching folder under `/opt/homelab/media/library/`. The mount is read-only inside the container — Jellyfin writes all metadata and thumbnails to the `jellyfin_config` volume.

**YouTube downloads** skip that manual step: the [metube role](../metube/README.md) writes audio into `library/music`, video into `library/youtube` and podcast episodes into `library/podcasts`, staging its partial files in `incoming/metube`.

**Realtime monitoring** is converged by this role over Jellyfin's API. Jellyfin sets it per library when the library is created, and a library created without it only updates at the scheduled scan — which is how the Musik library came to sit an hour behind. The task posts each library's existing options back with `EnableRealtimeMonitor` set, so a library added later through the UI is corrected on the next run.

**Adding a library:** append it to `jellyfin_libraries` in `defaults/main.yml`, add its content type to `jellyfin_library_types`, re-run the role, then add it in the admin UI at `/media/<path>`.

**Transcoding:** Software transcoding works out of the box. For hardware acceleration (Intel Quick Sync, VA-API), add the appropriate device passthrough to the compose file and re-run the role. Example for Intel iGPU:

```yaml
devices:
  - /dev/dri:/dev/dri
```

**SSO via Keycloak (optional):** Jellyfin supports OIDC through the community SSO plugin. Steps:

1. In Keycloak, create an OIDC client `jellyfin` in the `homelab` realm. Set the redirect URI to `https://media.home.example.com/sso/OID/r/keycloak`.
2. In Jellyfin admin UI → Plugins → Catalog → install **SSO-Auth**.
3. Restart the Jellyfin container: `docker restart jellyfin`
4. In Jellyfin admin UI → Plugins → SSO-Auth → configure the Keycloak provider using the client ID and secret from step 1.

**Clients:** Use any Jellyfin client — the web UI, Jellyfin for Android/iOS, Infuse, Swiftfin, or Kodi with the Jellyfin add-on. Point them at `https://media.home.example.com`.
