from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github/workflows/build-android-apk.yml").read_text(encoding="utf-8")

required = {
    "java 17 setup": "actions/setup-java@v4",
    "java 17 version": "java-version: '17'",
    "android license preparation": "Prepare Android SDK and accept licenses",
    "android sdk root": 'ANDROID_SDK_ROOT="$SDK_ROOT"',
    "android 35 platform": '"platforms;android-35"',
    "android build tools": '"build-tools;34.0.0"',
    "accept licenses": 'yes | "$SDKMANAGER" --licenses',
    "skip doctor env": 'FLET_CLI_SKIP_FLUTTER_DOCTOR: "1"',
    "skip doctor cli": "--skip-flutter-doctor",
    "plain ci output": 'FLET_CLI_NO_RICH_OUTPUT: "1"',
    "build log": "flet-build.log",
    "always upload log": "if: always()",
    "job timeout": "timeout-minutes: 60",
}

for label, token in required.items():
    if token not in workflow:
        raise AssertionError(f"missing {label}: {token}")

# The build must retain pipefail so the `tee` pipeline reports the Flet exit code.
build_section = workflow.split("- name: Build APK", 1)[1].split("- name: Verify native files", 1)[0]
if "set -euo pipefail" not in build_section or "2>&1 | tee flet-build.log" not in build_section:
    raise AssertionError("Build APK step must preserve the real flet exit code while logging")

print("phase7_1_android_ci_environment_smoke_test passed")
