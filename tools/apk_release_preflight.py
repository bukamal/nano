from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
version_py = (ROOT / "src/nano_offline/version.py").read_text(encoding="utf-8")
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
license_code = (ROOT / "src/nano_offline/services/license_service.py").read_text(encoding="utf-8")
paths = (ROOT / "src/nano_offline/core/paths.py").read_text(encoding="utf-8")

required = {
    # Single source of truth: version.py. pyproject resolves its version
    # dynamically from it, and the build scripts/CI read the same file through
    # tools/app_version.py (asserted below).
    "pyproject dynamic version": ('dynamic = ["version"]', pyproject),
    "pyproject version attr": ('attr = "nano_offline.version.APP_VERSION"', pyproject),
    "internet permission": ("android.permission.INTERNET", pyproject),
    "android auto backup disabled": ('allowBackup = "false"', pyproject),
    "persistent Flet storage": ("FLET_APP_STORAGE_DATA", paths),
    "activation gate": ("ActivationGate", main),
    "Hawaa activation URL": ("license.manhal-almasriiii199119.workers.dev/activate", license_code),
    "Hawaa request licenseCode": ('"licenseCode"', license_code),
    "Hawaa request fingerprint": ('"fingerprint"', license_code),
    "native files dependency": ('flet-native-files==0.1.6', pyproject),
    "native files dev package": ('"flet-native-files" = "extensions/flet_native_files"', pyproject),
}
for label, (needle, text) in required.items():
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")

# [tool.flet].build_number has no dynamic form, so enforce it against
# version.py:BUILD_NUMBER here (this is the drift that shipped 0.9.6/25 APKs
# whose in-app version said 0.17.1/46).
build_num = re.search(r"BUILD_NUMBER\s*=\s*(\d+)", version_py)
assert build_num, "BUILD_NUMBER missing from version.py"
assert re.search(r"^build_number\s*=\s*" + build_num.group(1) + r"\b", pyproject, re.M), (
    "pyproject [tool.flet].build_number does not match version.py:BUILD_NUMBER"
)
app_version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', version_py)
assert app_version, "APP_VERSION missing from version.py"

all_source = "\n".join(p.read_text(encoding="utf-8", errors="ignore").lower() for p in (ROOT / "src").rglob("*.py"))
for forbidden in ["telegram.webapp", "supabase", "vercel", "postgresql://"]:
    if forbidden in all_source:
        raise AssertionError(f"online dependency forbidden in offline build: {forbidden}")

print("apk_release_preflight passed")
