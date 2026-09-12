#!/usr/bin/env bash
# Build one Nano suite APK (accounting | inventory | pos | full).
# Reliable approach for Flet: temporarily replace src/main.py with the
# selected entry point, patch org/product in pyproject.toml, build, restore.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP="${1:-full}"

case "$APP" in
  accounting|acc)
    MODULE_FILE="src/main_accounting.py"
    ORG="com.nano.accounting"
    PRODUCT="نانو محاسبة"
    APK_NAME="nano-accounting-release.apk"
    ;;
  inventory|inv)
    MODULE_FILE="src/main_inventory.py"
    ORG="com.nano.inventory"
    PRODUCT="نانو المستودع"
    APK_NAME="nano-inventory-release.apk"
    ;;
  pos)
    MODULE_FILE="src/main_pos.py"
    ORG="com.nano.pos"
    PRODUCT="نانو نقطة البيع"
    APK_NAME="nano-pos-release.apk"
    ;;
  full|"")
    MODULE_FILE="src/main.py"
    ORG="com.nano"
    PRODUCT="Nano | نانو"
    APK_NAME="nano-release.apk"
    ;;
  *)
    echo "Unknown app: $APP  (use: accounting|inventory|pos|full)" >&2
    exit 1
    ;;
esac

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
echo "    entry=$MODULE_FILE  org=$ORG  product=$PRODUCT"
echo "    version=$BUILD_VERSION  build=$BUILD_NUMBER"

MAIN_SRC="src/main.py"
MAIN_BAK="src/main.py.bak.suite"
PYPROJECT="pyproject.toml"
PYPROJECT_BAK="${PYPROJECT}.bak.suite"

restore_all() {
  if [ -f "$MAIN_BAK" ]; then
    mv -f "$MAIN_BAK" "$MAIN_SRC"
  fi
  if [ -f "$PYPROJECT_BAK" ]; then
    mv -f "$PYPROJECT_BAK" "$PYPROJECT"
  fi
}
trap restore_all EXIT

cp -f "$MAIN_SRC" "$MAIN_BAK"
cp -f "$PYPROJECT" "$PYPROJECT_BAK"

if [ "$APP" != "full" ] && [ -n "$APP" ]; then
  if [ ! -f "$MODULE_FILE" ]; then
    echo "Missing entry point: $MODULE_FILE" >&2
    exit 1
  fi
  cp -f "$MODULE_FILE" "$MAIN_SRC"
  echo "    swapped src/main.py <- $MODULE_FILE"
fi

python3 - "$ORG" "$PRODUCT" <<'PY'
import re, sys
from pathlib import Path
org, product = sys.argv[1], sys.argv[2]
path = Path("pyproject.toml")
text = path.read_text(encoding="utf-8")
text = re.sub(r'(?m)^(org\s*=\s*).*$', rf'\1"{org}"', text, count=1)
text = re.sub(r'(?m)^(product\s*=\s*).*$', rf'\1"{product}"', text, count=1)
if re.search(r'(?m)^module\s*=', text):
    text = re.sub(r'(?m)^module\s*=\s*".*"', 'module = "main"', text)
path.write_text(text, encoding="utf-8")
print(f"    pyproject org={org} product={product} module=main")
PY

uv sync
uv run python -m ensurepip --upgrade >/dev/null 2>&1 || true

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

find . -name "NanoGlanceWidget.kt" -type f -delete 2>/dev/null || true
rm -rf build/flutter-packages 2>/dev/null || true
rm -rf build 2>/dev/null || true

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
  set -o pipefail
  uv run flet build apk \
    --product "$PRODUCT" \
    --org "$ORG" \
    --build-number "$BUILD_NUMBER" \
    --build-version "$BUILD_VERSION" \
    "${EXTRA_ARGS[@]}" 2>&1 | tee "flet-build-${APP}.log"
  status=$?
  set +o pipefail
  set -e

  if [ "$status" -eq 0 ]; then
    break
  fi
  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "flet build apk failed after ${MAX_ATTEMPTS} attempts (exit ${status})." >&2
    exit "$status"
  fi
  echo "flet build apk failed (attempt ${attempt}/${MAX_ATTEMPTS}). Retrying..." >&2
  if command -v dart >/dev/null 2>&1; then
    dart pub cache clean -f 2>/dev/null || true
  fi
  rm -rf build 2>/dev/null || true
  attempt=$((attempt + 1))
done

APK_PATH="$(find build -name '*.apk' -type f 2>/dev/null | head -n 1 || true)"
if [ -z "$APK_PATH" ]; then
  echo "Nano APK was not produced for app=$APP." >&2
  exit 1
fi
mkdir -p dist
cp "$APK_PATH" "dist/${APK_NAME}"
cp "$APK_PATH" "dist/nano-${APP}.apk"
echo "Nano installer: $(pwd)/dist/${APK_NAME}"
ls -lh "dist/${APK_NAME}"

{
  echo "app=$APP"
  echo "org=$ORG"
  echo "product=$PRODUCT"
  echo "entry=$MODULE_FILE"
  echo "apk=$APK_NAME"
  echo "version=$BUILD_VERSION"
  echo "build=$BUILD_NUMBER"
} > "dist/${APP}-build-info.txt"
cat "dist/${APP}-build-info.txt"
