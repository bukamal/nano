#!/usr/bin/env python3
"""Read the single source of truth for the app version: ``src/nano_offline/version.py``.

The version file is parsed as text on purpose (instead of imported) so this
helper works before ``uv sync``/``pip install -e .`` has run and without
needing ``PYTHONPATH=src`` -- it is called at the very top of the Android
build scripts and from CI.

Usage::

    python tools/app_version.py            # "0.17.1 46"
    python tools/app_version.py --version  # "0.17.1"
    python tools/app_version.py --build    # "46"
    python tools/app_version.py --shell    # eval-able BUILD_VERSION/BUILD_NUMBER
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[1] / "src" / "nano_offline" / "version.py"


def read_app_version() -> tuple[str, str]:
    """Return ``(app_version, build_number)`` parsed from version.py."""
    text = _VERSION_FILE.read_text(encoding="utf-8")
    ver = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    num = re.search(r"BUILD_NUMBER\s*=\s*(\d+)", text)
    return (ver.group(1) if ver else "0.0.0", num.group(1) if num else "1")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read Nano's app version from version.py")
    parser.add_argument("--version", action="store_true", help="print only APP_VERSION")
    parser.add_argument("--build", action="store_true", help="print only BUILD_NUMBER")
    parser.add_argument(
        "--shell",
        action="store_true",
        help="print eval-able BUILD_VERSION=... / BUILD_NUMBER=... assignments",
    )
    args = parser.parse_args(argv)
    version, build = read_app_version()
    if args.version:
        print(version)
    elif args.build:
        print(build)
    elif args.shell:
        print(f'BUILD_VERSION="{version}"')
        print(f'BUILD_NUMBER="{build}"')
    else:
        print(f"{version} {build}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
