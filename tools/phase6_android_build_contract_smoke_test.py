from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
workflow = (root / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")
main = (root / "src/main.py").read_text(encoding="utf-8")
paths = (root / "src/qeid_offline/core/paths.py").read_text(encoding="utf-8")

version = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', pyproject, re.M)
assert version and tuple(map(int, version.groups())) >= (0, 6, 0)
build = re.search(r'^build_number\s*=\s*(\d+)', pyproject, re.M)
assert build and int(build.group(1)) >= 6
for needle in ['"android.permission.INTERNET"', 'allowBackup = "false"']:
    assert needle in pyproject, needle
for needle in ["FLET_APP_STORAGE_DATA", "migrate_legacy_database"]:
    assert needle in paths, needle
assert "database_path()" in main and "migrate_legacy_database" in main
for needle in ["flet build apk", "tools/quality_gate.py", "qeid-offline-release.apk"]:
    assert needle in workflow, needle
assert f"--build-number {build.group(1)}" in workflow
assert f"--build-version {'.'.join(version.groups())}" in workflow
print("phase6_android_build_contract_smoke_test passed")
