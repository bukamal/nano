from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
license_code = (ROOT / "src/nano_offline/services/license_service.py").read_text(encoding="utf-8")
paths = (ROOT / "src/nano_offline/core/paths.py").read_text(encoding="utf-8")

required = {
    "pyproject version": ('version = "0.8.1"', pyproject),
    "build number": ("build_number = 13", pyproject),
    "internet permission": ("android.permission.INTERNET", pyproject),
    "android auto backup disabled": ('allowBackup = "false"', pyproject),
    "persistent Flet storage": ("FLET_APP_STORAGE_DATA", paths),
    "activation gate": ("ActivationGate", main),
    "Hawaa activation URL": ("license.manhal-almasriiii199119.workers.dev/activate", license_code),
    "Hawaa request licenseCode": ('"licenseCode"', license_code),
    "Hawaa request fingerprint": ('"fingerprint"', license_code),
    "native files dependency": ('flet-native-files==0.1.1', pyproject),
    "native files dev package": ('"flet-native-files" = "extensions/flet_native_files"', pyproject),
}
for label, (needle, text) in required.items():
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")

all_source = "\n".join(p.read_text(encoding="utf-8", errors="ignore").lower() for p in (ROOT / "src").rglob("*.py"))
for forbidden in ["telegram.webapp", "supabase", "vercel", "postgresql://"]:
    if forbidden in all_source:
        raise AssertionError(f"online dependency forbidden in offline build: {forbidden}")

print("apk_release_preflight passed")
