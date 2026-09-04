from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extensions" / "flet_native_files"

required_source = [
    EXT / "pyproject.toml",
    EXT / "src/flet_native_files/native_files.py",
    EXT / "src/flutter/flet_native_files/pubspec.yaml",
    EXT / "src/flutter/flet_native_files/lib/flet_native_files.dart",
    EXT / "src/flutter/flet_native_files/lib/src/create_control.dart",
    EXT / "src/flutter/flet_native_files/lib/src/native_files.dart",
]
for path in required_source:
    assert path.is_file(), path

pubspec = (EXT / "src/flutter/flet_native_files/pubspec.yaml").read_text(encoding="utf-8")
for needle in ["flet: 0.28.3", "file_picker: 10.1.9", "share_plus:", "printing:", "pdf:"]:
    assert needle in pubspec, needle

dart = (EXT / "src/flutter/flet_native_files/lib/src/native_files.dart").read_text(encoding="utf-8")
for needle in ["FilePicker.platform.pickFiles", "Share.shareXFiles", "Printing.layoutPdf", "Printing.convertHtml", "createPdfFile", "case 'create_pdf'"]:
    assert needle in dart, needle

with tempfile.TemporaryDirectory(prefix="qeid-native-wheel-") as td:
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", str(EXT), "-w", td],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Could not build flet-native-files wheel:\n{proc.stdout}")
    wheels = list(Path(td).glob("flet_native_files-*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())
    required_wheel = {
        "flet_native_files/native_files.py",
        "flutter/flet_native_files/pubspec.yaml",
        "flutter/flet_native_files/lib/flet_native_files.dart",
        "flutter/flet_native_files/lib/src/create_control.dart",
        "flutter/flet_native_files/lib/src/native_files.dart",
    }
    missing = required_wheel - names
    assert not missing, f"Wheel missing Flutter payload: {sorted(missing)}"

print("phase7_native_extension_packaging_smoke_test passed")
