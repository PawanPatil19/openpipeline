#!/usr/bin/env python3
"""Set or check the version across every package in the monorepo.

    python3 scripts/bump_version.py 0.2.0          # set it everywhere
    python3 scripts/bump_version.py --check 0.2.0  # fail if anything differs

Then commit, and push a tag ``v0.2.0`` to trigger the release workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_FILES = [
    ROOT / "packages/core/src/openpipeline_core/__init__.py",
    ROOT / "apps/server/src/openpipeline/__init__.py",
]
WEB_PACKAGE = ROOT / "apps/web/package.json"
# The app pins the exact core version it was released with.
APP_PYPROJECT = ROOT / "apps/server/pyproject.toml"
CORE_PIN_RE = re.compile(r'"openpipeline-core==([^"]+)"')
VERSION_RE = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-?(?:a|b|rc)\d+)?$")


def current() -> dict[str, str]:
    found = {}
    for f in PY_FILES:
        m = VERSION_RE.search(f.read_text())
        found[str(f.relative_to(ROOT))] = m.group(1) if m else "<missing>"
    found[str(WEB_PACKAGE.relative_to(ROOT))] = json.loads(WEB_PACKAGE.read_text())["version"]
    pin = CORE_PIN_RE.search(APP_PYPROJECT.read_text())
    found[str(APP_PYPROJECT.relative_to(ROOT))] = pin.group(1) if pin else "<missing>"
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not SEMVER_RE.match(args.version):
        print(f"{args.version!r} is not a version like 1.2.3 or 1.2.3rc1", file=sys.stderr)
        return 2

    if args.check:
        wrong = {f: v for f, v in current().items() if v != args.version}
        for f, v in wrong.items():
            print(f"{f} has version {v}, expected {args.version}", file=sys.stderr)
        return 1 if wrong else 0

    for f in PY_FILES:
        f.write_text(VERSION_RE.sub(f'__version__ = "{args.version}"', f.read_text()))
    pkg = json.loads(WEB_PACKAGE.read_text())
    pkg["version"] = args.version
    WEB_PACKAGE.write_text(json.dumps(pkg, indent=2) + "\n")
    APP_PYPROJECT.write_text(
        CORE_PIN_RE.sub(f'"openpipeline-core=={args.version}"', APP_PYPROJECT.read_text())
    )
    print(f"Set version {args.version} in {len(PY_FILES) + 2} files. Now run `uv lock`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
