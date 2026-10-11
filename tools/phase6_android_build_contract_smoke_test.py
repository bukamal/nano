from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
workflow = (root / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")
version_py = (root / "src/nano_offline/version.py").read_text(encoding="utf-8")
main = (root / "src/main.py").read_text(encoding="utf-8")
paths = (root / "src/nano_offline/core/paths.py").read_text(encoding="utf-8")

# Single source of truth: src/nano_offline/version.py (not a literal in pyproject).
version = re.search(r'APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', version_py)
assert version and tuple(map(int, version.groups())) >= (0, 6, 0)
build = re.search(r'BUILD_NUMBER\s*=\s*(\d+)', version_py)
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
# The workflow must DERIVE the version/build from version.py (via
# tools/app_version.py) instead of hardcoding it -- that hardcoded pair is
# what used to drift out of sync with the app's own reported version.
assert "tools/app_version.py --shell" in workflow
assert "steps.appver.outputs.build_number" in workflow
assert "steps.appver.outputs.build_version" in workflow
print("phase6_android_build_contract_smoke_test passed")
