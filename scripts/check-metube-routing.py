#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["yt-dlp", "pyyaml", "jinja2"]
# ///
"""Fail if MeTube would file a download in the wrong Jellyfin library.

Evaluates the output templates from ansible/roles/metube/defaults/main.yml with
yt-dlp's own template engine against the metadata yt-dlp hands over, offline:
audio-only formats have no height and go to music/, anything with a picture goes
to youtube/, and the Podcast preset sends audio to podcasts/.

    ./scripts/check-metube-routing.py
"""

import sys
from pathlib import Path

import jinja2
import yaml
from yt_dlp import YoutubeDL

DEFAULTS = (
    Path(__file__).resolve().parent.parent / "ansible/roles/metube/defaults/main.yml"
)

TOPIC_UPLOAD = {
    "artists": ["BAKI"],
    "album": "Dark Horse",
    "track": "Dark Horse (Hardstyle)",
    "release_year": 2022,
    "uploader": "BAKI - Topic",
    "title": "Dark Horse (Hardstyle)",
    "upload_date": "20220101",
}
CHANNEL_UPLOAD = {
    "uploader": "All-In Podcast",
    "title": "Episode 1",
    "upload_date": "20260901",
}


def render(value, context):
    while isinstance(value, str) and "{{" in value:
        value = jinja2.Template(value).render(context)
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    return value


def main() -> int:
    raw = yaml.safe_load(DEFAULTS.read_text())
    config = {k: render(v, raw) for k, v in raw.items()}
    default = config["metube_output_template"]
    podcast = config["metube_ytdl_options_presets"]["Podcast"]["outtmpl"]["default"]

    cases = [
        (
            "topic audio",
            default,
            {**TOPIC_UPLOAD, "height": None, "ext": "opus"},
            "music/BAKI/Dark Horse (2022)/01 Dark Horse (Hardstyle).opus",
        ),
        (
            "channel audio",
            default,
            {**CHANNEL_UPLOAD, "height": None, "ext": "opus"},
            "music/All-In Podcast/Episode 1 (2026)/01 Episode 1.opus",
        ),
        (
            "video",
            default,
            {**CHANNEL_UPLOAD, "height": 1080, "ext": "webm"},
            "youtube/All-In Podcast/Episode 1 (2026)/01 Episode 1.webm",
        ),
        (
            "podcast preset",
            podcast,
            {**CHANNEL_UPLOAD, "height": None, "ext": "opus"},
            "podcasts/All-In Podcast/Episode 1 (2026)/01 Episode 1.opus",
        ),
    ]

    failed = 0
    with YoutubeDL({"quiet": True}) as ydl:
        for name, template, info, expected in cases:
            got = ydl.evaluate_outtmpl(template, info)
            ok = got == expected
            failed += not ok
            print(
                f"{'ok  ' if ok else 'FAIL'} {name}: {got}"
                + ("" if ok else f"\n     expected: {expected}")
            )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
