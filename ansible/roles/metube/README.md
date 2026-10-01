# metube

Web UI for yt-dlp that downloads YouTube audio and video straight into the Jellyfin libraries.

## Overview

MeTube is a single-container front end for [yt-dlp](https://github.com/yt-dlp/yt-dlp).
Paste a URL, pick *Audio / opus / best*, and the track lands in
`/opt/homelab/media/library/music` as `<Artist>/<Album> (<Year>)/01 <Track>.opus`.
Jellyfin's realtime monitor (enabled for every library by the `jellyfin` role) picks it
up within seconds.

Where a download goes:

| Download | Library | How it is chosen |
|---|---|---|
| Audio | `library/music` | default |
| Video | `library/youtube` | automatic — the format has a picture |
| Audio, **Podcast** preset ticked | `library/podcasts` | *Advanced Options → Option Presets → Podcast* |

Podcasts (All-In, Joe Rogan, Big Think, …) need that one tick per download — see
[Routing](#routing) for why MeTube cannot recognise the channel by itself.

How good the name is depends entirely on what YouTube hands over — see
[Naming](#naming) below.

Nothing is re-encoded. YouTube's best audio stream is Opus at roughly 130–160 kbps, and
`FFmpegExtractAudio` with `preferredcodec: opus` remuxes it rather than transcoding, so
the file keeps the original bytes. There is no higher-quality source to extract; a tool
that claims otherwise is upsampling.

MeTube has **no authentication**. It is reachable only from the LAN and the Headscale
mesh, because `*.home.example.com` exists only in Pi-hole — the name does not
resolve on public DNS. Do not give it a record at the apex domain.

## Prerequisites

- `common` role applied (Docker, `proxy` network)
- `traefik` role running (TLS termination)
- `pihole` role applied — `ytdl.home.example.com` is in `pihole_dns_hosts`;
  there is no `*.home` wildcard record
- `jellyfin` role applied — it creates the media tree this role writes into

## Containers

| Container | Image | Purpose |
|---|---|---|
| `metube` | `ghcr.io/alexta69/metube` | yt-dlp web UI + download worker |

Networks: joins `proxy` only (Traefik). No companion services, no database — queue state
is a JSON file in the bind-mounted `state/` directory.

## Configuration

Files rendered by Ansible to the host:

| File | Purpose |
|---|---|
| `/opt/homelab/services/metube/docker-compose.yml` | Stack definition |

Directories created by Ansible:

| Path | Purpose |
|---|---|
| `/opt/homelab/services/metube/state` | Queue and subscription state (`STATE_DIR`) |
| `/opt/homelab/media/incoming/metube` | Intermediate download files (`TEMP_DIR`) |

Role variables (`defaults/main.yml`):

| Variable | Purpose |
|---|---|
| `metube_host` | Web UI hostname; needs a matching `pihole_dns_hosts` entry |
| `metube_puid` / `metube_pgid` | uid/gid MeTube runs as — must be `deploy_user`'s |
| `metube_library_subdir` | Download base (`DOWNLOAD_DIR`), relative to `jellyfin_media_root` |
| `metube_temp_subdir` | Intermediate files, relative to `jellyfin_media_root` |
| `metube_track_template` | `<Artist>/<Album> (<Year>)/01 <Track>` — the `NAMING.md` layout |
| `metube_output_template` | `music/` or `youtube/` + the track template |
| `metube_ytdl_options_presets` | `YTDL_OPTIONS_PRESETS` — the **Podcast** preset |

`jellyfin_media_root` lives in `group_vars/all/vars.yml`, shared with the `jellyfin`
role.

### Routing

MeTube has **one** output template for audio and video, so the library is picked inside
it: `%(height&youtube|music)s/…`. An audio-only format has no height and yields
`music/`; anything with a picture yields `youtube/`. The download base is therefore the
whole `library/` tree, not `library/music`.

Podcasts cannot be recognised automatically. yt-dlp templates can test whether a field
is empty but cannot compare it to a value, `--parse-metadata` takes Python callables
that `YTDL_OPTIONS` (JSON) cannot express, and a preset that points `paths` at another
directory is refused by MeTube's confinement check. What a preset *can* do is replace
the template within the base directory, so the **Podcast** preset swaps `music/` for
`podcasts/`.

`scripts/check-metube-routing.py` (run in CI) evaluates these templates with yt-dlp
against audio, video and Topic-channel metadata and fails if any lands in the wrong
library.

### Naming

Uploads from a YouTube Music **"- Topic"** channel carry real music metadata, and the
template reproduces the convention in `NAMING.md` exactly:

| Field | Value | Result |
|---|---|---|
| `artists.0` | `BAKI` | `BAKI/` |
| `album` | `Dark Horse` | `Dark Horse (2022)/` |
| `track` | `Dark Horse (Hardstyle)` | `01 Dark Horse (Hardstyle).opus` |

An **ordinary channel upload** has none of those — `artists`, `album`, `track` and
`release_year` are all `NA` — so the template falls back to the uploading channel and
the raw video title:

```
Gikoloz/Adele - Set Fire To The Rain HARDSTYLE REMIX (ANDONIS) (2022)/01 ….opus
```

That is filed in the library anyway rather than held back for review, so every download
reaches Jellyfin immediately; the untidy ones get renamed in place afterwards. yt-dlp
cannot do better here — the artist and track simply are not in the video's metadata.

`artists.0` rather than `artist` because `artist` is the whole credit list joined with
commas (`Daciva, SRXPH, rediver, Dang Nguyen, Dang Nguyen`), which is not a directory
name.

Check what a URL will produce without downloading it:

```bash
docker exec metube yt-dlp -f bestaudio --simulate --print filename \
  -o "%(height&youtube|music)s/%(artists.0,artist,uploader)s/%(album,track,title)s (%(release_year,release_date>%Y,upload_date>%Y)s)/01 %(track,title)s.%(ext)s" \
  "<url>"
```

Swap `-f bestaudio` for `-f bestvideo+bestaudio` to see where a video download goes.

### Why the whole media root is mounted

The container gets `/opt/homelab/media` as one bind mount rather than just `library/`.
yt-dlp writes intermediate files to `TEMP_DIR` and moves the finished file to
`DOWNLOAD_DIR`; that move is an atomic `rename()` only while both are inside the same
mount. Across a mount boundary `rename()` fails with `EXDEV` and yt-dlp falls back to a
copy, which Jellyfin's realtime monitor can catch half-written. The role asserts the two
paths share a filesystem, so mounting a separate disk at `library/` fails the play
instead of producing silently broken library entries.

`incoming/` is still not mounted into Jellyfin, so partial downloads are invisible to it
regardless.

### Why there is no `YTDL_OPTIONS`

MeTube's audio path already appends `FFmpegMetadata` and `EmbedThumbnail` — but only
when `writethumbnail` is *absent* from the options it was given
([`dl_formats.py`](https://github.com/alexta69/metube/blob/master/app/dl_formats.py)):

```python
if format != "wav" and "writethumbnail" not in opts:
    opts["writethumbnail"] = True
    ...
    postprocessors.append({"key": "FFmpegMetadata"})
    postprocessors.append({"key": "EmbedThumbnail"})
```

Setting `writethumbnail` in `YTDL_OPTIONS` — the obvious way to ask for cover art —
therefore turns tagging *and* cover art off. Leave `YTDL_OPTIONS` unset, and keep
`writethumbnail` out of the presets for the same reason.

## Secrets

None. MeTube stores no credentials and this role reads none from Vault.

## URL

`https://ytdl.home.example.com` — LAN/VPN only.

## Deploy

```bash
ansible-playbook ansible/site.yml --tags metube
```

## Notes

**Pick the format once per browser.** Select *Audio*, format *opus*, quality *best* on
the first download; every later one is then paste-and-enter. Choosing `mp3` instead
would re-encode the Opus source — lossy twice, smaller, worse.

There is **no server-side default** for this. MeTube's `_FRONTEND_KEYS` exposes
`DEFAULT_THEME` and `DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT` to the browser but nothing for
the download type, format or quality, and the UI reads no query parameters — so it
cannot be preset from the compose file or from a bookmark. The selection lives in
cookies on the `ytdl.home.example.com` origin (`ui/src/app/app.ts`):

| Cookie | Set to | MeTube's own default |
|---|---|---|
| `metube_download_type` | `audio` | `video` |
| `metube_format` | `opus` | `any` |
| `metube_quality` | `best` | `best` |

They are written with a 3650-day expiry, so one pass through the dropdowns holds for ten
years — but only in that browser. To set them directly on another device, paste this
into its console on the MeTube page:

```js
['download_type=audio', 'format=opus', 'quality=best']
  .forEach(c => document.cookie = `metube_${c};path=/;max-age=315360000`);
location.reload();
```

Forcing the defaults server-side would mean injecting three `Set-Cookie` headers, and
Traefik's `customResponseHeaders` holds one value per header name — so it would take a
container whose only job is to set cookies. Not worth it against a ten-year cookie.

**Version is unpinned.** `metube_version` is `latest`, against the repo's usual habit.
MeTube is a yt-dlp wrapper and yt-dlp breaks whenever YouTube changes its layout; a
pinned tag rots into a downloader that no longer downloads. The image is rebuilt on each
yt-dlp stable release, so `docker compose pull` is the fix when a download starts
failing.

**A "- Topic" channel is the signal.** If the YouTube page shows the artist name
followed by `- Topic`, the download will be named correctly with no help. Anything else
is a guess, and the guess is the channel name.

**The Podcast tick does not stick.** Presets are chosen per download, not remembered
like the format cookies. Forgetting it files the episode under `music/<Channel>/`; move
that channel directory to `podcasts/` on the host.

**The whole library is downloadable from MeTube.** MeTube serves finished files under
its own URL from `DOWNLOAD_DIR`, which is now `library/` rather than `library/music`, so
anyone on the LAN or VPN who can guess a path can fetch any file in `library/` — films
included. Directory listing stays off (`DOWNLOAD_DIRS_INDEXABLE` defaults to `false`).
That is the same audience that can already reach the unauthenticated UI.

**Deleting from the UI does not delete the file.** `DELETE_FILE_ON_TRASHCAN` is left at
its default of `false`, so clearing a finished download from the MeTube list leaves the
track in the library.

**Long mixes are single tracks.** A three-hour upload becomes one file in one album
directory. Jellyfin handles it, but it will not have chapters.

**The temp tree keeps empty directories.** yt-dlp mirrors the output path under
`TEMP_DIR` and removes only the files, so `incoming/metube/<Artist>/<Album>/` is left
behind empty. Nothing reads that tree and Jellyfin does not mount it, so it is cosmetic;
clear it with `find /opt/homelab/media/incoming/metube -mindepth 1 -type d -empty
-delete` if it ever bothers you.

**Re-downloading a URL overwrites the existing track.** yt-dlp checks for the
pre-conversion filename, which never exists, so it downloads and replaces rather than
skipping. Harmless when the source is the same, but it is not a no-op.
