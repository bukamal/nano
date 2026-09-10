import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
db = (ROOT / "src/nano_offline/core/database.py").read_text(encoding="utf-8")
workflow = (ROOT / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")
preflight = (ROOT / "tools/apk_release_preflight.py").read_text(encoding="utf-8")

for needle in [
    'version = "0.9.6"',
    'build_number = 24',
    '[tool.flet.dev_packages]',
    '"flet-native-files" = "extensions/flet_native_files"',
]:
    assert needle in pyproject, needle
assert "flet-native-files==" in pyproject
schema_match = re.search(r'^SCHEMA_VERSION\s*=\s*(\d+)', db, re.M)
assert schema_match and int(schema_match.group(1)) >= 9, "SCHEMA_VERSION must be >= 9"
for needle in [
    "pip install -e extensions/flet_native_files",
    "--build-number 24",
    "--build-version 0.9.6",
    "verify_flet_native_files_registration.py build/flutter",
]:
    assert needle in workflow, needle
assert 'version = "0.9.6"' in preflight
assert "flet-native-files" in preflight

print("phase7_project_contract_smoke_test passed")
