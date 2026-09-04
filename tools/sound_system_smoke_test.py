from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.app_context import AppContext
from nano_offline.core import sound_settings

with tempfile.TemporaryDirectory(prefix="nano-sound-") as td:
    ctx = AppContext.create(Path(td) / "nano.db")
    settings = ctx.settings

    # Defaults: system on, success/error/warning on, info off (see
    # sound_settings.DEFAULT_KIND_INFO's docstring for why info differs).
    assert sound_settings.sound_enabled(settings) is True
    assert sound_settings.sound_volume_percent(settings) == sound_settings.DEFAULT_VOLUME
    assert sound_settings.sound_volume(settings) == sound_settings.DEFAULT_VOLUME / 100.0
    assert sound_settings.kind_enabled(settings, "success") is True
    assert sound_settings.kind_enabled(settings, "error") is True
    assert sound_settings.kind_enabled(settings, "warning") is True
    assert sound_settings.kind_enabled(settings, "info") is False
    assert sound_settings.kind_enabled(settings, "scan") is True
    assert sound_settings.kind_enabled(settings, "save") is True
    assert sound_settings.kind_enabled(settings, "delete") is True
    # An unknown kind is never enabled -- fails closed, not open.
    assert sound_settings.kind_enabled(settings, "bogus") is False

    # Admin saves new settings via the same set_many() call admin_view.py
    # uses -- every setting takes effect on the very next read, exactly
    # like every other *_settings.py module in this codebase.
    settings.set_many({
        sound_settings.ENABLED_KEY: "0",
        sound_settings.VOLUME_KEY: "35",
        sound_settings.KIND_INFO_KEY: "1",
        sound_settings.KIND_ERROR_KEY: "0",
    })
    assert sound_settings.sound_enabled(settings) is False
    assert sound_settings.sound_volume_percent(settings) == 35
    assert abs(sound_settings.sound_volume(settings) - 0.35) < 1e-9
    assert sound_settings.kind_enabled(settings, "info") is True
    assert sound_settings.kind_enabled(settings, "error") is False
    # Untouched kinds keep their own defaults independently.
    assert sound_settings.kind_enabled(settings, "success") is True
    assert sound_settings.kind_enabled(settings, "warning") is True

    # Volume is clamped into range against garbage/out-of-range input --
    # same defensive pattern as barcode_settings.label_columns().
    settings.set(sound_settings.VOLUME_KEY, "150")
    assert sound_settings.sound_volume_percent(settings) == 100
    settings.set(sound_settings.VOLUME_KEY, "-20")
    assert sound_settings.sound_volume_percent(settings) == 0
    settings.set(sound_settings.VOLUME_KEY, "not-a-number")
    assert sound_settings.sound_volume_percent(settings) == sound_settings.DEFAULT_VOLUME

    # The six bundled tone files core/sound.py references by relative
    # path must actually exist and be non-empty WAV data, or the whole
    # feature silently does nothing on a real device.
    sounds_dir = ROOT / "src" / "assets" / "sounds"
    for name in ("success.wav", "error.wav", "warning.wav", "info.wav", "scan.wav", "save.wav", "delete.wav"):
        path = sounds_dir / name
        assert path.is_file(), f"missing sound asset: {path}"
        data = path.read_bytes()
        assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", f"{name} is not a valid WAV file"
        assert len(data) > 1000, f"{name} looks suspiciously empty ({len(data)} bytes)"

    # core/sound.py's _SOUND_KINDS must list exactly these four kinds -- the
    # single source of truth Python-side code (and this test) check a kind
    # against before ever calling into the native bridge.
    # This import needs `flet` itself (a hard app dependency, used for the
    # `ft.Page` type hint) which isn't installed in every environment this
    # smoke test might run in (e.g. no network/toolchain sandbox) -- skip
    # this one check gracefully rather than failing the whole test on a
    # missing dependency unrelated to what's actually being verified.
    try:
        from nano_offline.core import sound as sound_engine
    except ImportError as exc:
        print(f"sound_system_smoke_test: skipped core/sound.py import check ({exc})")
    else:
        assert sound_engine._SOUND_KINDS == frozenset({"success", "error", "warning", "info", "scan", "save", "delete"})
        # attach_context()'s signature changed when sound playback moved off
        # flet-audio onto the native AudioPool bridge (see sound.py's module
        # docstring) -- it now takes the shared NativeFiles instance as a
        # third argument. Checking the parameter count here catches main.py
        # and sound.py drifting out of sync with each other again, the same
        # way this test's settings assertions above catch admin_view.py and
        # sound_settings.py drifting.
        import inspect
        params = list(inspect.signature(sound_engine.attach_context).parameters)
        assert params == ["page", "ctx", "native_files"], params

    # sound.py no longer owns the "kind -> asset path" mapping itself --
    # that now lives on the Dart side (sound_pool.dart's kSoundAssetPaths),
    # since it's the Flutter/AudioPool code that actually resolves these
    # paths against the bundled assets. Reading it as plain text (rather
    # than needing Dart tooling this smoke test can't assume is installed)
    # still catches the two ways this has silently broken before: a kind
    # missing entirely, or a path that doesn't match the
    # "packages/flet_native_files/assets/sounds/<kind>.wav" convention this
    # package's own assets require (see kSoundAssetPaths' comment for why
    # the "packages/<name>/" prefix is mandatory here, unlike main.py's own
    # bundled fonts).
    sound_pool_dart = (
        ROOT / "extensions" / "flet_native_files" / "src" / "flutter" / "flet_native_files"
        / "lib" / "src" / "sound_pool.dart"
    )
    assert sound_pool_dart.is_file(), f"missing native sound bridge: {sound_pool_dart}"
    dart_source = sound_pool_dart.read_text(encoding="utf-8")
    for kind in ("success", "error", "warning", "info", "scan", "save", "delete"):
        expected_entry = f"'{kind}': 'packages/flet_native_files/assets/sounds/{kind}.wav'"
        assert expected_entry in dart_source, (
            f"sound_pool.dart is missing or has changed the mapping for {kind!r} "
            f"(expected to find: {expected_entry!r})"
        )

    # The two new event-specific tones must be physically bundled in the
    # Flutter package's own assets/ dir too (a separate copy from
    # src/assets/sounds/ -- see pubspec.yaml's "assets: - assets/sounds/"
    # declaration), or ensureSoundPoolsLoaded() fails to load them on a
    # real build even though the Python-side asset and the Dart mapping
    # both look correct.
    flutter_sounds_dir = (
        ROOT / "extensions" / "flet_native_files" / "src" / "flutter" / "flet_native_files"
        / "assets" / "sounds"
    )
    for name in ("success.wav", "error.wav", "warning.wav", "info.wav", "scan.wav", "save.wav", "delete.wav"):
        path = flutter_sounds_dir / name
        assert path.is_file(), f"missing bundled Flutter sound asset: {path}"

    # The pubspec.yaml declaring flet_native_files' Flutter-side
    # dependencies must actually list audioplayers -- the package
    # sound_pool.dart imports to build its AudioPools. Without this line,
    # `flet build apk` never adds it to the generated Flutter project and
    # every AudioPool.createFromAsset() call in sound_pool.dart fails at
    # import time, the exact same class of "silently no-op on a real
    # device, no error anywhere in Python" symptom flet-audio's missing
    # [tool.flet.flutter] declaration used to produce (see sound.py's
    # module docstring for that history).
    pubspec = (
        ROOT / "extensions" / "flet_native_files" / "src" / "flutter" / "flet_native_files" / "pubspec.yaml"
    )
    assert pubspec.is_file(), f"missing pubspec.yaml: {pubspec}"
    pubspec_text = pubspec.read_text(encoding="utf-8")
    assert "audioplayers:" in pubspec_text, "flet_native_files' pubspec.yaml is missing the audioplayers dependency"
    # flet-audio must be fully gone as an actual dependency (a historical
    # mention in an explanatory comment, like sound.py's own module
    # docstring, is fine and expected) -- a leftover *declaration* here
    # (pyproject.toml's [project.dependencies] pin, or a
    # [tool.flet.flutter] dependencies entry) would mean two sound systems
    # are wired in at once instead of a clean cutover.
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "flet-audio==" not in pyproject_text, "pyproject.toml still declares the retired flet-audio pip dependency"
    assert '"flet_audio"' not in pyproject_text, "pyproject.toml still declares the retired flet_audio Flutter package"

print("sound_system_smoke_test passed")
