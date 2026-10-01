from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")

# Contract: the CI workflow must provision Java 17 + an Android SDK with the
# android-35 platform and build-tools, accept licenses without the
# `yes |` broken-pipe foot-gun, and build with flet while preserving its
# exit code and uploading the log. Implementation details (manual SDK
# provisioning vs android-actions/setup-android) may evolve; the essentials
# below must not.

required = {
    "java 17 setup": "actions/setup-java@v4",
    "java 17 version": "java-version: '17'",
    "android license preparation": "Prepare Android SDK and accept licenses",
    "android sdk root export": "ANDROID_SDK_ROOT=",
    "android 35 platform": "platforms;android-35",
    "android build tools": "build-tools;34.0.0",
    "no broken-pipe yes-pipe on licenses": "yes | ",
    "skip doctor env": "FLET_CLI_SKIP_FLUTTER_DOCTOR",
    "skip doctor cli": "--skip-flutter-doctor",
    "build log": "flet-build.log",
    "always upload log": "if: always()",
    "job timeout": "timeout-minutes: 60",
}

for label, token in required.items():
    if token not in workflow:
        raise AssertionError(f"missing {label}: {token}")

# The legacy `yes | sdkmanager --licenses` pattern kills the pipeline with
# SIGPIPE/broken pipe the moment sdkmanager stops reading stdin -- it already
# broke this exact job once. It must stay gone.
for banned in ('yes | "$SDKMANAGER" --licenses', 'yes | "$SDK_ROOT'):
    if banned in workflow:
        raise AssertionError(f"banned broken-pipe pattern present: {banned}")

# The build must retain pipefail so the `tee` pipeline reports the Flet exit code.
build_section = workflow.split("- name: Build APK", 1)[1].split("- name: Verify native files", 1)[0]
if "set -euo pipefail" not in build_section or "tee flet-build.log" not in build_section:
    raise AssertionError("Build APK step must preserve the real flet exit code while logging")

print("phase7_1_android_ci_environment_smoke_test passed")
