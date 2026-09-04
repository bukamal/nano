import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';

/// App-wide sound-cue playback, built on `audioplayers`' `AudioPool` --
/// replaces the earlier `flet-audio`-based `core/sound.py` entirely (see
/// the comment on the `audioplayers` dependency in this package's
/// pubspec.yaml for the full history of why).
///
/// Why AudioPool instead of a single reused AudioPlayer (or fta.Audio):
/// AudioPool is `audioplayers`' own purpose-built answer to "extremely
/// quick firing, repetitive ... sounds" (its class doc, verbatim) -- each
/// pool pre-loads one asset into a small rotation of native player
/// instances up front, so a `start()` call never has to wait on a decode
/// or worry about an already-finished player having nowhere left to
/// restart from. That's exactly the failure mode the old flet-audio
/// wrapper hit (a reused control that reached end-of-track just stayed
/// silent forever after -- see https://github.com/flet-dev/flet/discussions/2925),
/// and exactly what matters here: rapid repeated scans in stocktake_view.py
/// firing the same "success" tone many times a minute.
///
/// One pool per tone kind, not one pool shared across kinds: AudioPool's
/// own docs are explicit that all players in a pool share the same source
/// -- "If you want multiple sounds use multiple AudioPools." Seven
/// genuinely different tones (success/error/warning/info/scan/save/delete)
/// means seven pools.
const Map<String, String> kSoundAssetPaths = {
  // Flutter always namespaces a package's own bundled assets as
  // "packages/<package_name>/<path>" in rootBundle -- even for code
  // inside that same package loading its own assets declared in its own
  // pubspec.yaml. Omitting the "packages/flet_native_files/" prefix here
  // is exactly what produced the "Unable to load asset:
  // assets/sounds/<x>.wav" failures the admin diagnostics panel caught
  // (see this package's pubspec.yaml for where these files are now
  // actually declared/bundled).
  'success': 'packages/flet_native_files/assets/sounds/success.wav',
  'error': 'packages/flet_native_files/assets/sounds/error.wav',
  'warning': 'packages/flet_native_files/assets/sounds/warning.wav',
  'info': 'packages/flet_native_files/assets/sounds/info.wav',
  // Two event-specific tones layered on top of the four generic kinds --
  // same asset-loading/AudioPool machinery, just two more entries. 'scan'
  // fires on a successful barcode match (POS + stocktake) instead of the
  // generic 'success' chime: shorter and pitched higher so it stays crisp
  // and non-fatiguing under rapid repeated scanning. 'save' fires on a
  // completed invoice/payment: a fuller 3-note arpeggio for an action
  // that's meaningfully bigger than an ordinary success toast.
  'scan': 'packages/flet_native_files/assets/sounds/scan.wav',
  'save': 'packages/flet_native_files/assets/sounds/save.wav',
  // A seventh, distinct tone for destructive delete actions (invoice/
  // item/party/expense/category/unit/voucher delete) -- lower-pitched and
  // shorter than 'error' so a deletion doesn't sound like something went
  // wrong, and clearly different from the generic 'success' chime a
  // "تم الحذف" message would otherwise infer.
  'delete': 'packages/flet_native_files/assets/sounds/delete.wav',
};

// Empty prefix: kSoundAssetPaths above already supplies the full
// "packages/flet_native_files/assets/..." asset key, so the AudioCache's
// own default "assets/" prefix must be turned off here -- otherwise it
// would look for "assets/packages/flet_native_files/assets/..." instead.
final AudioCache _soundCache = AudioCache(prefix: '');

// Two ready players per kind: comfortably covers the same tone firing
// twice in quick succession (e.g. two rapid barcode scans) without either
// call waiting on the other, while staying tiny in memory -- these are
// all under-a-second bundled tones, not music.
const int _kMaxPlayersPerKind = 2;

final Map<String, AudioPool> _pools = {};
final Set<String> _failedKinds = {};
// Human-readable reason each kind in `_failedKinds` failed to load --
// surfaced verbatim by diagnoseSoundPools() below so the admin diagnostics
// panel can show *why* (missing asset, decode error, etc.) instead of just
// a generic "not working".
final Map<String, String> _failedErrors = {};
Future<void>? _loadingFuture;

/// Loads all four tone assets into their own AudioPool, once per process.
/// Safe to call repeatedly (from every 'init_sound'/'play_sound'
/// handleMethod call) -- later calls just await the same in-flight or
/// already-finished load instead of redoing the work.
///
/// Best-effort per kind: a single tone failing to load (e.g. a corrupt or
/// missing asset) is logged and skipped rather than blocking the other
/// three -- same "sound is always an enhancement, never a requirement"
/// posture as the rest of this bridge and as core/sound.py itself.
Future<void> ensureSoundPoolsLoaded({bool forceRetryFailed = false}) {
  // The diagnostics panel (see 'diagnose_sound' in native_files.dart) passes
  // forceRetryFailed so pressing "إعادة الفحص" actually re-attempts kinds
  // that failed earlier in this session, instead of just re-reporting the
  // same cached failure forever -- normal play()/init_sound() calls never
  // set this, since re-trying a genuinely broken asset on every single
  // toast would be wasted work.
  if (forceRetryFailed && _failedKinds.isNotEmpty) {
    _failedKinds.clear();
    _failedErrors.clear();
    _loadingFuture = null;
  }
  return _loadingFuture ??= () async {
    for (final entry in kSoundAssetPaths.entries) {
      if (_pools.containsKey(entry.key) || _failedKinds.contains(entry.key)) continue;
      try {
        _pools[entry.key] = await AudioPool.createFromAsset(
          path: entry.value,
          maxPlayers: _kMaxPlayersPerKind,
          audioCache: _soundCache,
        );
      } catch (error) {
        _failedKinds.add(entry.key);
        _failedErrors[entry.key] = error.toString();
        debugPrint('nano sound: failed to load ${entry.value} for kind=${entry.key}: $error');
      }
    }
  }();
}

/// Full diagnostic snapshot for the admin "تشخيص المشكلة" panel: attempts
/// to (re)load every kind (respecting `forceRetryFailed`), then for each
/// kind reports whether its AudioPool loaded and, if `alsoTestPlay` is
/// true, whether a silent-volume `pool.start()` actually succeeds --
/// catching runtime playback failures (e.g. platform audio-focus errors)
/// that a successful *load* alone wouldn't reveal.
Future<Map<String, dynamic>> diagnoseSoundPools({
  bool forceRetryFailed = false,
  bool alsoTestPlay = true,
}) async {
  await ensureSoundPoolsLoaded(forceRetryFailed: forceRetryFailed);
  final kinds = <String, dynamic>{};
  for (final entry in kSoundAssetPaths.entries) {
    final kind = entry.key;
    final loaded = _pools.containsKey(kind);
    String? playError;
    if (loaded && alsoTestPlay) {
      try {
        // volume: 0.0 -- proves the native player actually starts (asset
        // decodes, platform accepts the play call) without the admin
        // hearing a stray tone just from opening the diagnostics panel;
        // the dedicated preview buttons already cover "does it actually
        // make sound at an audible volume".
        await _pools[kind]!.start(volume: 0.0);
      } catch (error) {
        playError = error.toString();
      }
    }
    kinds[kind] = {
      'asset': entry.value,
      'loaded': loaded,
      'load_error': _failedErrors[kind],
      'play_error': playError,
    };
  }
  return kinds;
}

/// Plays the given tone kind at `volume` (0.0-1.0). Loads the pools first
/// if `ensureSoundPoolsLoaded` (normally fired once at app startup via the
/// 'init_sound' method, see native_files.py's init_sound()) hasn't
/// finished yet -- so the very first toast of a session still gets sound,
/// just with a one-time decode delay instead of silently doing nothing.
///
/// Never throws: unknown kind, a kind whose asset failed to load, or any
/// native playback error is logged and swallowed. Sound is always a
/// best-effort layer on top of the toast that already conveys the same
/// information visually (see core/sound.py's play()).
Future<void> playPoolSound(String kind, double volume) async {
  await ensureSoundPoolsLoaded();
  final pool = _pools[kind];
  if (pool == null) {
    debugPrint('nano sound: no pool available for kind=$kind');
    return;
  }
  try {
    await pool.start(volume: volume.clamp(0.0, 1.0));
  } catch (error) {
    debugPrint('nano sound playback failed: $error');
  }
}

/// Releases every loaded pool's native players. Called once from
/// FletNativeFilesControl.dispose() -- mirrors AudioPool's own
/// documented DOs and DON'Ts ("DO call release()/dispose() when sounds
/// are no longer useful").
Future<void> disposeSoundPools() async {
  for (final pool in _pools.values) {
    try {
      await pool.dispose();
    } catch (error) {
      debugPrint('nano sound: pool dispose failed: $error');
    }
  }
  _pools.clear();
  _failedKinds.clear();
  _loadingFuture = null;
}
