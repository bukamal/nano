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

    # PHASE10: confirm Gradle's manifest merger actually folded the home
    # screen widget receiver from android/src/main/AndroidManifest.xml into
    # the generated app manifest -- a silent merge failure here would leave
    # push_home_widget()/the periodic WorkManager pass calling into a
    # channel with nothing listening on the widget side, without any build
    # error to catch it.
    merged_manifest = flutter_root / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    if merged_manifest.is_file():
        manifest_text = _read(merged_manifest)
        if "com.nano.homewidget.NanoWidgetReceiver" not in manifest_text:
            raise RuntimeError(
                "Generated AndroidManifest.xml is missing the PHASE10 home widget receiver "
                "(com.nano.homewidget.NanoWidgetReceiver) -- check "
                "extensions/flet_native_files/.../android/src/main/AndroidManifest.xml and "
                "the plugin.platforms.android section of that package's pubspec.yaml"
            )

        # The receiver being present is not enough on its own: it must also
        # be exported, since it's invoked by the launcher/System Server (a
        # different process) via the APPWIDGET_UPDATE broadcast. A merged
        # exported="false" builds and installs fine -- the widget just shows
        # the "Couldn't load widget" placeholder forever because the update
        # broadcast never reaches it. Match the specific <receiver> block
        # instead of scanning the whole file, since some other exported
        # component could otherwise mask a false here.
        receiver_match = re.search(
            r"<receiver\b[^>]*android:name=\"com\.nano\.homewidget\.NanoWidgetReceiver\"[^>]*/?>"
            r"|<receiver\b[^>]*android:name=\"\.homewidget\.NanoWidgetReceiver\"[^>]*/?>",
            manifest_text,
        )
        if receiver_match is None or 'android:exported="true"' not in receiver_match.group(0):
            raise RuntimeError(
                "PHASE10 NanoWidgetReceiver is present in the merged manifest but not "
                'android:exported="true" -- the launcher cannot deliver the '
                "APPWIDGET_UPDATE broadcast across processes with exported=false, so the "
                "widget will be added to the home screen but never render. Fix "
                "android:exported on the <receiver> in "
                "extensions/flet_native_files/.../android/src/main/AndroidManifest.xml"
            )

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
