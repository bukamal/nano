from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
workflow = (root / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")
main = (root / "src/main.py").read_text(encoding="utf-8")
paths = (root / "src/nano_offline/core/paths.py").read_text(encoding="utf-8")

version = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', pyproject, re.M)
assert version and tuple(map(int, version.groups())) >= (0, 6, 0)
build = re.search(r'^build_number\s*=\s*(\d+)', pyproject, re.M)
assert build and int(build.group(1)) >= 6
for needle in ['"android.permission.INTERNET"', 'allowBackup = "false"']:
    assert needle in pyproject, needle
for needle in ["FLET_APP_STORAGE_DATA", "migrate_legacy_database"]:
    assert needle in paths, needle
assert "database_path()" in main and "migrate_legacy_database" in main
for needle in ["flet build apk", "tools/quality_gate.py", "actions/upload-artifact"]:
    assert needle in workflow, needle
# The APK must actually be uploaded as an artifact, and a missing file must
# fail the job loudly rather than reporting a hollow success (that hollow
# success already shipped a build with no downloadable APK once).
assert "nano-release-apk" in workflow
assert "if-no-files-found: error" in workflow
assert "*.apk" in workflow
assert f"--build-number {build.group(1)}" in workflow
assert f"--build-version {'.'.join(version.groups())}" in workflow
print("phase6_android_build_contract_smoke_test passed")
