#!/usr/bin/env bash
set -euo pipefail

# Build Nano Android APK and copy the installer into dist/.
uv run flet build apk --product "Nano | نانو" --org com.nano --build-number 9 --build-version 0.7.2
APK_PATH="$(find build -name '*.apk' -type f | head -n 1)"
if [ -z "$APK_PATH" ]; then
  echo "Nano APK was not produced." >&2
  exit 1
fi
mkdir -p dist
cp "$APK_PATH" dist/nano-release.apk
printf 'Nano installer: %s\n' "$(pwd)/dist/nano-release.apk"
