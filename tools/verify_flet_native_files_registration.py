from __future__ import annotations

import argparse
import re
from pathlib import Path

PACKAGE = "flet_native_files"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def verify(flutter_root: Path) -> dict[str, str]:
    flutter_root = flutter_root.resolve()
    if not flutter_root.is_dir():
        raise RuntimeError(f"Generated Flutter project does not exist: {flutter_root}")
    packages_root = flutter_root.parent / "flutter-packages"
    extension_root = packages_root / PACKAGE
    required = [
        extension_root / "pubspec.yaml",
        extension_root / "lib" / "flet_native_files.dart",
        extension_root / "lib" / "src" / "create_control.dart",
        extension_root / "lib" / "src" / "native_files.dart",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        discovered = sorted(str(p) for p in packages_root.glob("*/pubspec.yaml")) if packages_root.exists() else []
        raise RuntimeError(
            "Flet did not copy/register flet_native_files.\n"
            f"Missing: {missing}\nDiscovered: {discovered}"
        )
    pubspec = _read(extension_root / "pubspec.yaml")
    if not re.search(r"(?m)^name:\s*flet_native_files\s*$", pubspec):
        raise RuntimeError("Invalid flet_native_files pubspec")
    app_pubspec = _read(flutter_root / "pubspec.yaml")
    if not re.search(r"(?m)^\s+flet_native_files\s*:", app_pubspec):
        raise RuntimeError("Generated app has no flet_native_files dependency")
    dart_files = list((flutter_root / "lib").rglob("*.dart"))
    dart = "\n".join(_read(p) for p in dart_files)
    if "package:flet_native_files/flet_native_files.dart" not in dart and "flet_native_files.createControl" not in dart:
        raise RuntimeError("Generated Dart bootstrap does not register flet_native_files")
    return {"flutter_root": str(flutter_root), "extension_root": str(extension_root), "dart_files": str(len(dart_files))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("flutter_root", nargs="?", default="build/flutter")
    args = parser.parse_args()
    result = verify(Path(args.flutter_root))
    print("flet_native_files registration verified")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
