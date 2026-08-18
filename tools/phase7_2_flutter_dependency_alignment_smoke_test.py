from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ext_pubspec = (ROOT / "extensions/flet_native_files/src/flutter/flet_native_files/pubspec.yaml").read_text(encoding="utf-8")
root_pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
workflow = (ROOT / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")
dart = (ROOT / "extensions/flet_native_files/src/flutter/flet_native_files/lib/src/native_files.dart").read_text(encoding="utf-8")

# Flet 0.28.3 itself resolves file_picker from ^10.1.9.  The extension must
# select a version inside the same constraint range or Dart pub will reject the graph.
assert "flet: 0.28.3" in ext_pubspec
assert "file_picker: 10.1.9" in ext_pubspec
assert "file_picker: ^8.3.7" not in ext_pubspec

# The API used by this extension is compatible with file_picker 10.1.x/10.3.x
# (the accidental static-only API in 10.3.9 was reverted in 10.3.10).
assert "FilePicker.platform.pickFiles" in dart

# Bump the local package so stale editable/wheel metadata cannot silently win.
assert 'version = "0.7.1"' in root_pyproject
assert 'build_number = 8' in root_pyproject
assert '"flet-native-files==0.1.1"' in root_pyproject
assert "--build-number 8" in workflow
assert "--build-version 0.7.1" in workflow

print("phase7_2_flutter_dependency_alignment_smoke_test passed")
