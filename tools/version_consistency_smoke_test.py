"""Contract: the app version/build number has exactly ONE source of truth.
The single source is ``src/nano_offline/version.py``. Everything that reports
or bakes in a version must derive from it, never hardcode its own copy:
* ``pyproject.toml`` resolves ``[project].version`` dynamically from
  ``APP_VERSION`` and its ``[tool.flet].build_number`` matches ``BUILD_NUMBER``.
* ``tools/app_version.py`` (used by the Android build scripts and CI) reads the
  same file.
* The root/installer ``build_nano_apk.sh``/``.bat`` and the GitHub workflow all
  call ``app_version.py`` and contain no hardcoded version literals.
This is the guard against the drift that shipped 0.9.6/25 APKs whose in-app
about screen said 0.17.1/46.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

version_py = (ROOT / "src/nano_offline/version.py").read_text(encoding="utf-8")
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

app_version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', version_py)
assert app_version, "APP_VERSION missing from src/nano_offline/version.py"
build_number = re.search(r"BUILD_NUMBER\s*=\s*(\d+)", version_py)
assert build_number, "BUILD_NUMBER missing from src/nano_offline/version.py"
APP_VERSION = app_version.group(1)
BUILD_NUMBER = build_number.group(1)

# --- pyproject resolves from the same file --------------------------------
assert 'dynamic = ["version"]' in pyproject, "pyproject must declare a dynamic version"
assert 'version = { attr = "nano_offline.version.APP_VERSION" }' in pyproject, (
    "pyproject must read its version from nano_offline.version.APP_VERSION"
)
assert re.search(rf"^build_number\s*=\s*{BUILD_NUMBER}\b", pyproject, re.M), (
    f"[tool.flet].build_number must equal version.py BUILD_NUMBER ({BUILD_NUMBER})"
)

# --- app_version.py reports the same values -------------------------------
for flag, expected in (("--version", APP_VERSION), ("--build", BUILD_NUMBER)):
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "app_version.py"), flag],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == expected, f"app_version.py {flag} -> {out!r} != {expected!r}"

# --- build scripts derive instead of hardcoding ---------------------------
scripts = [
    ROOT / "build_nano_apk.sh",
    ROOT / "installer/build_nano_apk.sh",
    ROOT / "build_nano_apk.bat",
    ROOT / "installer/build_nano_apk.bat",
    ROOT / ".github/workflows/build-android-apk.yml",
]
for path in scripts:
    text = path.read_text(encoding="utf-8")
    assert "app_version.py" in text, f"{path.relative_to(ROOT)} must call tools/app_version.py"
    # No re-introduced hardcoded pair (e.g. "--build-version 0.9.6"): the value
    # must come from the resolved variable/expression instead.
    assert not re.search(r"--build-version\s+\d", text), (
        f"{path.relative_to(ROOT)} hardcodes a --build-version literal"
    )
    assert not re.search(r"--build-number\s+\d", text), (
        f"{path.relative_to(ROOT)} hardcodes a --build-number literal"
    )

print(f"version_consistency_smoke_test passed ({APP_VERSION} build {BUILD_NUMBER})")
