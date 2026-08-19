from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
db = (ROOT / "src/nano_offline/core/database.py").read_text(encoding="utf-8")
workflow = (ROOT / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")
preflight = (ROOT / "tools/apk_release_preflight.py").read_text(encoding="utf-8")

for needle in [
    'version = "0.7.4"',
    'build_number = 11',
    '"flet-native-files==0.1.1"',
    '[tool.flet.dev_packages]',
    '"flet-native-files" = "extensions/flet_native_files"',
]:
    assert needle in pyproject, needle
assert "SCHEMA_VERSION = 6" in db
for needle in [
    "pip install -e extensions/flet_native_files",
    "--build-number 11",
    "--build-version 0.7.4",
    "verify_flet_native_files_registration.py build/flutter",
]:
    assert needle in workflow, needle
assert 'version = "0.7.4"' in preflight
assert "flet-native-files" in preflight

print("phase7_project_contract_smoke_test passed")
