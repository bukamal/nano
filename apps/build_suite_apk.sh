#!/usr/bin/env bash
# Build one Nano suite APK (accounting | inventory | pos | full).
# Designed to be called from GitHub Actions or locally.
#
# Usage:
#   ./apps/build_suite_apk.sh accounting
#   ./apps/build_suite_apk.sh inventory
#   ./apps/build_suite_apk.sh pos
#   ./apps/build_suite_apk.sh full
#
# Environment overrides:
#   BUILD_VERSION   (default: from src/nano_offline/version.py APP_VERSION)
#   BUILD_NUMBER    (default: from version.py BUILD_NUMBER)
#   SKIP_FLUTTER_DOCTOR=1  (recommended on CI)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP="${1:-full}"

# ---------------------------------------------------------------------------
# App matrix: module / org / product / apk artifact name
# ---------------------------------------------------------------------------
case "$APP" in
  accounting|acc)
    MODULE="main_accounting"
    ORG="com.nano.accounting"
    PRODUCT="نانو محاسبة"
    APK_NAME="nano-accounting-release.apk"
    ;;
  inventory|inv)
    MODULE="main_inventory"
    ORG="com.nano.inventory"
    PRODUCT="نانو المستودع"
    APK_NAME="nano-inventory-release.apk"
    ;;
  pos)
    MODULE="main_pos"
    ORG="com.nano.pos"
    PRODUCT="نانو نقطة البيع"
    APK_NAME="nano-pos-release.apk"
    ;;
  full|"")
    MODULE="main"
    ORG="com.nano"
    PRODUCT="Nano | نانو"
    APK_NAME="nano-release.apk"
    ;;
  *)
    echo "Unknown app: $APP  (use: accounting|inventory|pos|full)" >&2
    exit 1
    ;;
esac

# ---------------------------------------------------------------------------
# Version numbers
# ---------------------------------------------------------------------------
if [ -z "${BUILD_VERSION:-}" ] || [ -z "${BUILD_NUMBER:-}" ]; then
  eval "$(python3 - <<'PY'
from pathlib import Path
import re
text = Path("src/nano_offline/version.py").read_text(encoding="utf-8")
ver = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
num = re.search(r'BUILD_NUMBER\s*=\s*(\d+)', text)
print(f'BUILD_VERSION="{ver.group(1) if ver else "0.0.0"}"')
print(f'BUILD_NUMBER="{num.group(1) if num else "1"}"')
PY
)"
fi
BUILD_VERSION="${BUILD_VERSION:-0.0.0}"
BUILD_NUMBER="${BUILD_NUMBER:-1}"

echo "==> Building Nano suite app: $APP"
echo "    module=$MODULE  org=$ORG  product=$PRODUCT"
echo "    version=$BUILD_VERSION  build=$BUILD_NUMBER"

# ---------------------------------------------------------------------------
# Point Flet at the correct entry module (in-place edit of pyproject.toml)
# ---------------------------------------------------------------------------
PYPROJECT="pyproject.toml"
BACKUP="${PYPROJECT}.bak.suite"
cp "$PYPROJECT" "$BACKUP"

python3 - "$MODULE" <<'PY'
import sys
from pathlib import Path
import re
module = sys.argv[1]
path = Path("pyproject.toml")
text = path.read_text(encoding="utf-8")
if re.search(r"(?m)^module\s*=", text):
    text = re.sub(r'(?m)^module\s*=\s*".*"', f'module = "{module}"', text)
else:
    text = re.sub(
        r"(\[tool\.flet\.app\]\s*\n)",
        rf'\1module = "{module}"\n',
        text,
        count=1,
    )
path.write_text(text, encoding="utf-8")
print(f"pyproject.toml module -> {module}")
PY

restore_pyproject() {
  if [ -f "$BACKUP" ]; then
    mv -f "$BACKUP" "$PYPROJECT"
  fi
}
trap restore_pyproject EXIT

# ---------------------------------------------------------------------------
# Dependencies (same as original build_nano_apk.sh)
# ---------------------------------------------------------------------------
uv sync
uv run python -m ensurepip --upgrade >/dev/null 2>&1 || true

# Core library desugaring init script (required by flet_native_files)
GRADLE_INIT_DIR="${GRADLE_USER_HOME:-$HOME/.gradle}/init.d"
mkdir -p "$GRADLE_INIT_DIR"
cat > "$GRADLE_INIT_DIR/nano-core-library-desugaring.init.gradle.kts" <<'EOF'
gradle.beforeProject {
    if (name != "app") return@beforeProject
    plugins.withId("com.android.application") {
        extensions.getByName("android").withGroovyBuilder {
            "compileOptions" {
                "isCoreLibraryDesugaringEnabled" to true
            }
        }
        dependencies.add("coreLibraryDesugaring", "com.android.tools:desugar_jdk_libs:2.0.4")
    }
}
EOF

# Remove stale Glance widget that breaks builds
find . -name "NanoGlanceWidget.kt" -type f -delete 2>/dev/null || true
rm -rf build/flutter-packages 2>/dev/null || true

# ---------------------------------------------------------------------------
# flet build with retries (pub.dev flakes)
# ---------------------------------------------------------------------------
export FLET_CLI_NO_RICH_OUTPUT="${FLET_CLI_NO_RICH_OUTPUT:-1}"
export FLET_CLI_SKIP_FLUTTER_DOCTOR="${FLET_CLI_SKIP_FLUTTER_DOCTOR:-1}"

EXTRA_ARGS=()
if [ "${SKIP_FLUTTER_DOCTOR:-1}" = "1" ]; then
  EXTRA_ARGS+=(--skip-flutter-doctor)
fi

MAX_ATTEMPTS=3
attempt=1
status=1
while true; do
  set +e
  uv run flet build apk \
    --product "$PRODUCT" \
    --org "$ORG" \
    --build-number "$BUILD_NUMBER" \
    --build-version "$BUILD_VERSION" \
    "${EXTRA_ARGS[@]}" 2>&1 | tee flet-build-${APP}.log
  status=${PIPESTATUS[0]}
  set -e

  if [ "$status" -eq 0 ]; then
    break
  fi
  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "flet build apk failed after ${MAX_ATTEMPTS} attempts (exit ${status})." >&2
    exit "$status"
  fi
  echo "flet build apk failed (attempt ${attempt}/${MAX_ATTEMPTS}). Clearing pub cache and retrying..." >&2
  if command -v dart >/dev/null 2>&1; then
    dart pub cache clean -f 2>/dev/null || true
  fi
  rm -rf build 2>/dev/null || true
  attempt=$((attempt + 1))
done

# ---------------------------------------------------------------------------
# Collect APK
# ---------------------------------------------------------------------------
APK_PATH="$(find build -name '*.apk' -type f 2>/dev/null | head -n 1 || true)"
if [ -z "$APK_PATH" ]; then
  echo "Nano APK was not produced for app=$APP." >&2
  exit 1
fi
mkdir -p dist
cp "$APK_PATH" "dist/${APK_NAME}"
echo "Nano installer: $(pwd)/dist/${APK_NAME}"
ls -lh "dist/${APK_NAME}"
