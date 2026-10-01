#!/usr/bin/env python3
"""Fail if a pinned image tag does not exist in its registry.

The coverage check proves Renovate can *see* every pin. It cannot prove a pin is
real: a tag invented by hand, or one Renovate derived for an image that has since
stopped publishing, both sail past it and only fail at deploy time on the host.

This resolves every docker-datasource pin Renovate extracts and asks the registry
whether the manifest exists.

Best-effort by design: registries rate-limit anonymous manifest requests, and a
throttled answer is indistinguishable from a missing tag on exit code alone. Only
a registry explicitly saying the manifest is unknown fails the run; anything else
is reported as unverified. A check that fails on someone else's rate limit gets
ignored, and an ignored check catches nothing.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

RENOVATE_IMAGE = "ghcr.io/renovatebot/renovate:41"


def extracted_docker_pins() -> list[tuple[str, str]]:
    """Return (depName, currentValue) for every docker-datasource dependency."""
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
        detail = (proc.stderr + proc.stdout).strip()[-2000:]
        sys.exit(f"renovate extract failed ({proc.returncode}):\n{detail}")

    pins: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            if node.get("datasource") == "docker" and node.get("depName"):
                value = node.get("currentValue")
                if value:
                    pins[node["depName"]] = value
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for line in proc.stdout.splitlines():
        try:
            walk(json.loads(line))
        except json.JSONDecodeError:
            continue
    return sorted(pins.items())


# A registry that rate-limits or times out looks exactly like a missing tag if you
# only read the exit code. Only these phrases mean the tag is genuinely absent;
# anything else is the registry failing to answer and must not fail the build.
ABSENT = ("manifest unknown", "no such manifest", "not found", "manifest_unknown")


def tag_state(ref: str, attempts: int = 3) -> str:
    """Return "present", "absent", or "unknown"."""
    last = ""
    for attempt in range(attempts):
        proc = subprocess.run(
            ["docker", "manifest", "inspect", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return "present"
        last = (proc.stderr or proc.stdout).strip().lower()
        if any(phrase in last for phrase in ABSENT):
            return "absent"
        if attempt < attempts - 1:
            time.sleep(2 * (attempt + 1))
    print(f"     registry did not answer for {ref}: {last[:160]}")
    return "unknown"


def main() -> int:
    pins = extracted_docker_pins()
    if not pins:
        print("FAIL: no docker pins extracted — is renovate.json5 present?")
        return 1

    # A pin whose value is a Jinja expression or a moving alias is not a fixed tag
    # and there is nothing to resolve.
    skip = re.compile(r"\{\{|^latest$")
    missing, unknown, checked = [], [], 0

    for dep, value in pins:
        if skip.search(value):
            print(f"SKIP {dep}:{value}")
            continue
        ref = f"{dep}:{value}"
        state = tag_state(ref)
        checked += 1
        if state == "present":
            print(f"ok   {ref}")
        elif state == "absent":
            print(f"FAIL {ref} — no manifest in the registry")
            missing.append(ref)
        else:
            print(f"WARN {ref} — could not be verified")
            unknown.append(ref)

    if missing:
        print(f"\n{len(missing)} pinned tag(s) do not exist:")
        for ref in missing:
            print(f"  {ref}")
        print("Deploying these would fail on pull.")
        return 1

    if unknown:
        # Not a failure: the registry being unreachable says nothing about the pin,
        # and failing here would make the check flaky enough to be ignored.
        print(f"\n{len(unknown)} tag(s) could not be verified (registry unreachable):")
        for ref in unknown:
            print(f"  {ref}")

    print(f"\nOK: {checked - len(unknown)} of {checked} pinned image tags resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
