"""FIX_0.9.1 static verification: XML well-formedness, no lingering Glance
code references, manifest receiver still exported, version numbers synced."""
from __future__ import annotations

import xml.dom.minidom
from pathlib import Path

ROOT = Path("extensions/flet_native_files/src/flutter/flet_native_files/android/src/main")

failures: list[str] = []

xmls = [
    ROOT / "res/layout/nano_widget.xml",
    ROOT / "res/drawable/nano_widget_bg.xml",
    ROOT / "AndroidManifest.xml",
    ROOT / "res/xml/nano_widget_info.xml",
]
for f in xmls:
    try:
        xml.dom.minidom.parse(str(f))
        print("XML OK:", f.relative_to(ROOT))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"XML parse failed for {f}: {exc}")

kt_dir = ROOT / "kotlin/com/nano/homewidget"
glance_imports = []
for p in sorted(kt_dir.rglob("*.kt")):
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("import") and "glance" in line.lower():
            glance_imports.append(f"{p.name}: {line.strip()}")
print("Glance imports:", glance_imports if glance_imports else "NONE")
if glance_imports:
    failures.append(f"Glance imports still present: {glance_imports}")

refs = []
for base in ["extensions", "src", "build_nano_apk.sh", "pyproject.toml", "README.md"]:
    p = Path(base)
    if p.is_file():
        if "NanoGlanceWidget" in p.read_text(encoding="utf-8", errors="replace"):
            refs.append(str(p))
    elif p.is_dir():
        for f in p.rglob("*"):
            if f.suffix in {".kt", ".py", ".dart", ".sh", ".yaml", ".toml", ".xml", ".md"}:
                if "NanoGlanceWidget" in f.read_text(encoding="utf-8", errors="replace"):
                    refs.append(str(f))
print("NanoGlanceWidget references:", refs if refs else "NONE")
if refs:
    failures.append(f"NanoGlanceWidget still referenced in: {refs}")

manifest = (ROOT / "AndroidManifest.xml").read_text(encoding="utf-8")
if 'android:name="com.nano.homewidget.NanoWidgetReceiver"' not in manifest:
    failures.append("Manifest missing NanoWidgetReceiver")
if 'android:exported="true"' not in manifest:
    failures.append("Manifest receiver not exported")

for f in ["build_nano_apk.sh", "pyproject.toml", "src/nano_offline/version.py", "README.md"]:
    text = Path(f).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        sl = line.strip()
        if ("0.9.1" in sl or "22" in sl) and ("build" in sl.lower() or "version" in sl.lower() or "APP_VERSION" in sl or "BUILD_NUMBER" in sl):
            print("VERSION", f, "->", sl)
    if "0.8.1" in text and f != "FIX_0.9.1_HOME_WIDGET_APPPROVIDER_AR.md":
        if "0.9.1" not in text:
            failures.append(f"{f} still has 0.8.1 without 0.9.1")

print("RESULT:", "FAIL" if failures else "PASS")
if failures:
    raise SystemExit("\n".join(failures))
