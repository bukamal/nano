#!/usr/bin/env bash
set -euo pipefail

# Build Nano Android APK and copy the installer into dist/.
#
# NOTE on the pub.dev "authorization failed" flake:
# Dart's pub resolver occasionally reports a transient pub.dev connectivity
# hiccup as "Because <project> depends on <some package> any which doesn't
# exist (authorization failed)". This is misleading -- it is NOT a real auth
# problem with this project (the package named varies run to run and is
# whichever request happened to fail). The fix is to retry after clearing
# the pub cache. See: https://github.com/flet-dev/flet/discussions/3765
#
# NOTE on "<venv>/bin/python: No module named pip":
# `uv sync`/`uv run` create and populate the project venv without "seeding"
# pip/setuptools/wheel (uv manages dependencies itself and doesn't need
# pip). `flet build apk` doesn't know that -- it shells out to
# `<venv python> -m pip` at build time to check/upgrade the flet-cli
# package, so without pip that step fails the same way on every attempt.
# That's not the pub.dev flake the retry loop below is for, so make sure
# pip is present up front instead of retrying into the same failure.
uv sync
uv run python -m ensurepip --upgrade >/dev/null 2>&1 || true

# NOTE on "requires core library desugaring to be enabled for :app":
# extensions/flet_native_files depends on flutter_local_notifications (the
# closed-app smart-notification bridge -- see native_files.dart). Recent
# versions of that plugin use Java 8+ APIs on Android and therefore require
# `isCoreLibraryDesugaringEnabled = true` plus a `coreLibraryDesugaring`
# dependency for :app. Flet's cookiecutter build template has no
# pyproject.toml knob for this (unlike min/target SDK, permissions,
# ProGuard rules, etc.).
#
# A previous version of this script tried to fix this by editing the
# *generated* build/flutter/android/app/build.gradle.kts directly -- first
# right after a failed attempt, then (when that proved "too late") via a
# background watcher polling the file's mtime *while* `flet build apk` was
# still running, to win the race against whatever regenerates/removes it.
# Neither ever actually worked: CI run 90082680400 failed identically on
# all 3 attempts, and the log has zero occurrences of the watcher's own
# "[watcher] ...", "Checking ...", or "Patched ..." lines -- not even the
# very first one, which is a plain `echo` with no external process behind
# it and should be near-instant. That means the race was never close; the
# watcher's `[ -f "$gradle_file" ]` check itself was never observed true,
# which points at the underlying approach being fundamentally unreliable
# in this environment (exact mechanism aside) rather than a timing issue
# to tune further -- trying to out-race a file that a *different, opaque*
# tool process creates/reads/possibly-regenerates is inherently fragile.
#
# The reliable fix is to stop trying to catch that file at all and instead
# hook Gradle itself: any *.gradle[.kts] file dropped into
# `$GRADLE_USER_HOME/init.d/` (default `~/.gradle/init.d/`) is applied by
# Gradle automatically to *every* build it runs on this machine, no matter
# how many times flet (re)generates the project or how the retry loop
# above restarts it. This sidesteps the race entirely: we're not editing
# a generated file and hoping it survives, we're telling Gradle itself
# -- once, up front -- to always enable desugaring for any Android
# Application module it builds here.
GRADLE_INIT_DIR="${GRADLE_USER_HOME:-$HOME/.gradle}/init.d"
mkdir -p "$GRADLE_INIT_DIR"
cat > "$GRADLE_INIT_DIR/nano-core-library-desugaring.init.gradle.kts" <<'EOF'
// Auto-applied by Gradle to every build on this machine (see
// https://docs.gradle.org/current/userguide/init_scripts.html#sec:using_an_init_script).
// flutter_local_notifications (added for Nano's closed-app smart
// notifications, see extensions/flet_native_files) requires core library
// desugaring on the app module; the Flet-generated build.gradle.kts has no
// pyproject.toml knob for it, so it's enabled here instead of by editing
// that generated file.
allprojects {
    plugins.withId("com.android.application") {
        // Init scripts run with a separate classpath that does not include
        // the Android Gradle Plugin, so referencing an AGP type directly
        // (e.g. com.android.build.gradle.BaseExtension) fails to resolve
        // here -- "Unresolved reference: android" -- even though the same
        // reference works fine inside a normal build.gradle.kts. Configure
        // the "android" extension dynamically via Groovy interop instead;
        // that needs no AGP classpath entry, so it also doesn't need to
        // track whichever AGP version Flet happens to pull in.
        extensions.getByName("android").withGroovyBuilder {
            "compileOptions" {
                setProperty("coreLibraryDesugaringEnabled", true)
            }
        }
        dependencies {
            add("coreLibraryDesugaring", "com.android.tools:desugar_jdk_libs:2.1.4")
        }
    }
}
EOF
echo "Installed Gradle init script for core library desugaring at ${GRADLE_INIT_DIR}/nano-core-library-desugaring.init.gradle.kts" >&2

MAX_ATTEMPTS=3
attempt=1
while true; do
  set +e
  uv run flet build apk --product "Nano | نانو" --org com.nano --build-number 14 --build-version 0.8.1
  status=$?
  set -e

  if [ "$status" -eq 0 ]; then
    break
  fi
  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "flet build apk failed after ${MAX_ATTEMPTS} attempts (exit ${status})." >&2
    exit "$status"
  fi
  echo "flet build apk failed (attempt ${attempt}/${MAX_ATTEMPTS}, exit ${status})." >&2
  echo "This is usually a transient pub.dev resolution hiccup -- repairing the pub cache and retrying..." >&2
  if command -v dart >/dev/null 2>&1; then
    dart pub cache repair || true
  fi
  rm -rf "${PUB_CACHE:-$HOME/.pub-cache}" 2>/dev/null || true
  # Desugaring no longer needs any handling here -- the Gradle init script
  # installed above applies on every Gradle invocation regardless of how
  # many times this loop retries or flet regenerates the project.
  #
  # IMPORTANT: flet reuses the existing build/flutter project on retry and
  # does NOT re-run dependency resolution on its own. If we just wiped
  # PUB_CACHE above, build/flutter/.dart_tool/package_config.json (and
  # pubspec.lock) still point at packages (e.g. serious_python) that no
  # longer exist on disk -- flet build apk then fails immediately with
  # "Could not find `bin/main.dart` in package `serious_python`" instead
  # of actually retrying anything.
  #
  # We can't just run `flutter pub get` ourselves here: flet manages its
  # own Flutter SDK install and doesn't necessarily put it on PATH (on a
  # clean CI runner `flutter`/`dart` are NOT on PATH at all -- confirmed
  # by "build_nano_apk.sh: line 115: flutter: command not found" on a
  # real run -- that failure was silently swallowed by `|| true`, so the
  # stale dependency state never actually got refreshed). Instead, delete
  # the stale resolution artifacts so Dart/Flutter's own tooling detects
  # package_config.json is missing/invalid and re-resolves dependencies
  # from scratch the next time flet (using whichever Flutter it manages
  # internally) touches this project -- no need to know its path at all.
  if [ -d build/flutter ]; then
    rm -rf build/flutter/.dart_tool build/flutter/pubspec.lock 2>/dev/null || true
  fi
  attempt=$((attempt + 1))
  sleep 5
done
APK_PATH="$(find build -name '*.apk' -type f | head -n 1)"
if [ -z "$APK_PATH" ]; then
  echo "Nano APK was not produced." >&2
  exit 1
fi
mkdir -p dist
cp "$APK_PATH" dist/nano-release.apk
printf 'Nano installer: %s\n' "$(pwd)/dist/nano-release.apk"
