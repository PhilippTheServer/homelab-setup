#!/usr/bin/env python3
"""Fail if a version pin in group_vars is invisible to Renovate.

Runs Renovate's local extract and compares the `*_version` keys it matched
against the keys actually present in the vars file. A pin that is neither
extracted nor explicitly excluded is a silent update hole: that service never
gets a Renovate PR and nothing else would ever surface it.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VARS = REPO / "ansible" / "group_vars" / "all" / "vars.yml"

# The control node runs a Node version newer than Renovate supports, so this
# runs as a container rather than via npx. The workflows read the pin from here.
RENOVATE_IMAGE = "ghcr.io/renovatebot/renovate:41"

EXCLUDED = {
    "gym_bro_version": "self-built Harbor image, bumped to publish a build",
    "daily2_version": "self-built Harbor image, bumped to publish a build",
    "library_version": "self-built Harbor image, bumped to publish a build",
    "metube_version": "deliberately latest: a yt-dlp wrapper rots when pinned",
}

VERSION_KEY = re.compile(r"^([a-z0-9_]+_version):", re.MULTILINE)


def pins_in_vars_file() -> set[str]:
    return set(VERSION_KEY.findall(VARS.read_text()))


def replace_strings(node):
    """Yield every `replaceString` in Renovate's extract output.

    Walking the structure matters: these values contain real newlines, and
    matching against a re-serialised copy would capture the `n` of the escaped
    `\\n` as part of the variable name.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "replaceString" and isinstance(value, str):
                yield value
            else:
                yield from replace_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from replace_strings(item)


def pins_renovate_extracted() -> set[str]:
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{REPO}:/repo",
            "-w",
            "/repo",
            "-e",
            "LOG_LEVEL=info",
            "-e",
            "LOG_FORMAT=json",
            "-e",
            "RENOVATE_CONFIG_FILE=/repo/renovate.json5",
            "-e",
            "GIT_CONFIG_COUNT=1",
            "-e",
            "GIT_CONFIG_KEY_0=safe.directory",
            "-e",
            "GIT_CONFIG_VALUE_0=/repo",
            RENOVATE_IMAGE,
            "renovate",
            "--platform=local",
            "--dry-run=extract",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if not (REPO / "renovate.json5").exists():
            sys.exit(
                "FAIL: renovate.json5 does not exist, so nothing can be extracted."
            )
        # Under LOG_FORMAT=json the useful diagnostics go to stdout, not stderr.
        detail = (proc.stderr + proc.stdout).strip()[-2000:]
        sys.exit(f"renovate extract failed ({proc.returncode}):\n{detail}")

    found = set()
    for line in proc.stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        for replaced in replace_strings(record):
            found.update(VERSION_KEY.findall(replaced))
    return found


def main() -> int:
    present = pins_in_vars_file()
    extracted = pins_renovate_extracted()

    if not extracted:
        print("FAIL: renovate extracted no version pins at all.")
        print("      Is renovate.json5 present and is the custom manager matching?")
        return 1

    missing = sorted(present - extracted - set(EXCLUDED))
    leaked = sorted(extracted & set(EXCLUDED))

    for key in missing:
        print(f"FAIL: {key} is not extracted by Renovate and is not excluded.")
        print("      Add a '# renovate:' annotation above it, or add it to EXCLUDED.")
    for key in leaked:
        print(f"FAIL: {key} is excluded ({EXCLUDED[key]}) but Renovate extracted it.")
        print("      Remove its '# renovate:' annotation.")

    if missing or leaked:
        return 1

    print(f"OK: {len(present - set(EXCLUDED))} pins tracked, {len(EXCLUDED)} excluded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
