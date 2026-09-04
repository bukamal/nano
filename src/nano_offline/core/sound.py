from __future__ import annotations

"""App-wide sound-cue system -- seven short, offline-bundled tones (the
four generic success/error/warning/info kinds, plus three event-specific
ones, scan, save and delete) played through the native ``AudioPool``
bridge in ``extensions/flet_native_files`` (see that package's
sound_pool.dart).

Two "smarter" behaviors live entirely in this module (no native changes
needed, since both are just decisions about *when* to call the existing
play_sound(kind, volume) bridge and *what* volume to pass):
  - a short per-kind debounce so the same tone firing twice within a few
    milliseconds (rapid barcode "wedge" scanning, a duplicate toast call)
    doesn't stack into a harsh double-hit -- see _DEBOUNCE_SECONDS below.
  - a small per-play random volume nudge so repeated plays of the same
    sample don't all sound bit-for-bit identical -- see _VOLUME_JITTER.

Why this is different from the "no real beep" notes elsewhere
---------------------------------------------------------------
Several places in this codebase (``pos_view.py``'s ``_add_by_barcode``,
``stocktake_view.py``'s scan handler) have a comment explaining that real
audio/haptic feedback was left as a SnackBar substitute because it needs a
*native* platform channel that can't be written and verified blind, with
no Flutter toolchain or device available here.

That native-channel requirement is real for things like device vibration
or reading the phone's ringer/silent state -- but simply playing a bundled
audio file turned out to have an even simpler answer than a hand-written
platform channel: ``audioplayers`` (see https://pub.dev/packages/audioplayers),
an actively maintained, mainstream Flutter package with Android/iOS/
desktop/web support out of the box, added as a normal dependency of this
project's own ``flet_native_files`` extension (which already exists for
file/share/print/notification bridging -- see that package's
pubspec.yaml). No new native code, no new extension.

Design: one choke point, not fifty call sites
------------------------------------------------
Every view in this app already routes every user-facing message through
exactly one function -- ``core/toast.toast()`` -- which already classifies
each message into a ``ToastKind`` (success/error/warning/info) to pick an
icon and color. Hooking sound playback into that same classification means
every existing ``notify()``/``toast()`` call across the whole app (POS
scans, stocktake, invoice saves, payments, login, admin actions, ...)
gets a matching sound automatically, with zero changes needed at any of
those call sites -- see the one added line calling ``play()`` near the
end of ``toast()`` in core/toast.py.

History: why this isn't built on ``flet-audio`` anymore
------------------------------------------------------------
An earlier version of this module built one persistent ``fta.Audio``
control per kind (the ``flet-audio`` package, a thin Flet-control wrapper
around ``audioplayers``), cached on the page, and replayed the same
control every time via ``release_mode=fta.ReleaseMode.STOP`` (meant to
reset playback position to 0 before each ``.play()``, working around a
known audioplayers-on-Android bug where a reused control that already
reached end-of-track has nowhere left to advance from -- see
https://github.com/flet-dev/flet/discussions/2925 -- so it plays once and
then stays silent forever after).

That fix didn't work either: the ``flet-audio==0.1.0`` pin then required
(the last release compatible with flet==0.28.3 -- 0.80.0+ ships in
lockstep with core flet and can't resolve against this project's pin)
does not export ``ReleaseMode`` at all, so referencing it raised
``AttributeError``. A version rebuilding a fresh ``fta.Audio`` control per
``play()`` call instead (dropped into ``page.overlay``, played once, then
removed) fixed *that*, but ``flet-audio`` being a Flet-control wrapper
around a pip package also meant `flet build apk` needed an explicit
``[tool.flet.flutter] dependencies = ["flet_audio"]`` declaration in
pyproject.toml just to add the matching Flutter package to the built
APK -- easy to forget, and exactly what silently no-ops every ``play()``
call if it's missing (see https://github.com/flet-dev/flet/issues/2663).

Switching the native side to call ``audioplayers`` directly (via an
``AudioPool`` per tone -- see sound_pool.dart) inside the
``flet_native_files`` extension removes every one of those failure modes
at once: no Flet-control wrapper to go stale/mismatched against the core
``flet`` pin, no separate pyproject.toml Flutter-packaging declaration
(a normal Flutter plugin dependency of an already-registered
``[tool.flet.dev_packages]`` extension is picked up automatically), and
``AudioPool`` is *designed* for "fired repeatedly/rapidly" short sounds,
so there's no reused-control replay bug to work around in the first
place.

Best-effort by design: same as before
------------------------------------------
If the native side hasn't loaded a given tone yet, if a settings lookup
fails, or if the platform genuinely can't play audio, this silently does
nothing rather than raising -- sound is always an enhancement layered on
top of the toast that already conveys the same information visually,
never a requirement for the app to keep working.
"""

from typing import Literal
import random
import time

import flet as ft

from nano_offline.core import sound_settings

SoundKind = Literal[
    "success", "error", "warning", "info", "scan", "save", "delete",
    "login", "notify", "barcode_error",
]

# Kept here (rather than only in sound_pool.dart) as the single source of
# truth Python-side code and the smoke test can check against, and so a
# typo'd kind is caught before ever reaching invoke_method_async. Must stay
# in sync with kSoundAssetPaths' keys in
# extensions/flet_native_files/.../lib/src/sound_pool.dart, which is what
# actually resolves these to "sounds/<kind>.wav" under src/assets/.
#
# Three more event-specific kinds on top of the original seven (see this
# module's history section above for success/error/warning/info/scan/save,
# and SOUND_BARCODE_DELETE_FIX_AR.md for delete): 'login' (a session
# actually starting -- login_view.py's on_success paths), 'notify' (a
# genuinely new alert landing in the notification center -- low stock,
# backup due, license, receivables, insights; see
# notifications_view.py's refresh_badge()), and 'barcode_error' (a scan
# that matched nothing -- split off from the generic 'error' tone so a
# cashier mid-scan hears "no match" as a distinct, shorter cue rather than
# the same tone a database/validation failure would produce).
_SOUND_KINDS: frozenset[str] = frozenset(
    {"success", "error", "warning", "info", "scan", "save", "delete", "login", "notify", "barcode_error"}
)

_CTX_ATTR = "_nano_ctx"
_NATIVE_FILES_ATTR = "_nano_native_files"
_LAST_PLAYED_ATTR = "_nano_sound_last_played"

# --- Debounce -------------------------------------------------------------
# A barcode scanner firing in rapid "wedge" mode, or a double toast() call
# from the same user action, can trigger the same tone twice within a few
# milliseconds -- inaudible as two distinct dings, just a harsh overlapped
# stack. Skipping a repeat of the *same kind* within this window keeps
# rapid real-world use (continuous scanning) sounding clean instead of
# "machine-gunning" the audio pool. Short enough that two genuinely
# separate actions (two different scans a beat apart) are never dropped.
_DEBOUNCE_SECONDS = 0.06

# --- Micro volume variation ------------------------------------------------
# Playing the exact same sample at the exact same volume dozens of times a
# minute (every scan, every toast) reads as mechanical. A small per-play
# random nudge -- inaudible as "randomness", just enough that two plays in
# a row are never bit-for-bit identical -- is a cheap, well-worn "juice"
# trick (see e.g. game-audio design) for making a repeated UI sound feel
# less like a loop and more alive. Purely a playback-time multiplier on
# top of the admin-configured volume; never changes the asset itself.
_VOLUME_JITTER = 0.06  # +/- 6%


def attach_context(page: ft.Page, ctx, native_files) -> None:
    """Call once per page (main.py, right after AppContext and NativeFiles
    are both created) so play() -- called from deep inside toast(), which
    only ever receives ``page`` -- can reach current settings and the
    native sound bridge without every one of the ~50 existing
    toast()/notify() call sites needing to start passing them.

    Stores ``ctx`` itself, not ``ctx.settings`` -- AppContext.reload()
    (used after a backup restore) mutates the same ``ctx`` object's fields
    in place rather than replacing it, exactly so every existing
    ``self.ctx.settings`` access across the app picks up the restored
    settings automatically. Grabbing ``ctx.settings`` once here and
    holding onto that sub-object instead would go stale the moment a
    restore swaps it out from under us.

    ``native_files`` is the single ``NativeFiles`` control instance main.py
    already creates and adds to ``page.overlay`` for file/share/print/
    notification bridging -- reused here rather than creating a second
    instance, since a control needs to be mounted in the page's control
    tree for ``invoke_method_async`` to reach anything on the Dart side.
    """
    setattr(page, _CTX_ATTR, ctx)
    setattr(page, _NATIVE_FILES_ATTR, native_files)


async def _play_async(native_files, kind: str, volume: float) -> None:
    try:
        await native_files.play_sound(kind=kind, volume=volume)
    except Exception as exc:
        # Never let a sound failure surface to the user or break the flow
        # that triggered it -- same posture as every other best-effort
        # background task in this codebase (auto-backup, notification
        # sync in main.py). Still worth a line in the device log (visible
        # via `adb logcat` -- serious_python routes Python stdout there)
        # since a silently-swallowed exception here is otherwise
        # impossible to tell apart from "sound is just muted/disabled".
        print(f"nano sound playback failed: {exc!r}")


def play(page: ft.Page, kind: SoundKind) -> None:
    """Play the tone for ``kind`` if the sound system and this specific
    kind are both enabled in settings. No-op if attach_context() was never
    called for this page, the native bridge hasn't loaded that tone yet,
    the kind is muted, or the same kind just played within the debounce
    window (see _DEBOUNCE_SECONDS)."""
    ctx = getattr(page, _CTX_ATTR, None)
    native_files = getattr(page, _NATIVE_FILES_ATTR, None)
    if ctx is None or native_files is None:
        print("nano sound: no ctx/native_files attached to this page -- attach_context() was never called for it")
        return
    if kind not in _SOUND_KINDS:
        print(f"nano sound: unknown kind={kind!r}")
        return
    now = time.monotonic()
    last_played: dict[str, float] = getattr(page, _LAST_PLAYED_ATTR, None) or {}
    if now - last_played.get(kind, -1.0) < _DEBOUNCE_SECONDS:
        return
    last_played[kind] = now
    setattr(page, _LAST_PLAYED_ATTR, last_played)
    try:
        settings = ctx.settings
        if not sound_settings.sound_enabled(settings):
            return
        if not sound_settings.kind_enabled(settings, kind):
            return
        base_volume = sound_settings.sound_volume(settings)
    except Exception as exc:
        print(f"nano sound gate failed: {exc!r}")
        return
    jitter = 1.0 + random.uniform(-_VOLUME_JITTER, _VOLUME_JITTER)
    volume = max(0.0, min(1.0, base_volume * jitter))
    page.run_task(_play_async, native_files, kind, volume)


def play_preview(page: ft.Page, kind: SoundKind, volume_percent: int) -> None:
    """Bypass the enabled/kind-enabled settings gate entirely and play at
    an explicit volume. Used only by the admin settings screen's "معاينة"
    buttons, so an admin can hear a tone at whatever volume/kind they're
    currently dragging the slider to -- including while the system (or
    that specific kind) is toggled off, and before hitting "save"."""
    native_files = getattr(page, _NATIVE_FILES_ATTR, None)
    if native_files is None or kind not in _SOUND_KINDS:
        return
    volume = max(0.0, min(1.0, volume_percent / 100.0))
    page.run_task(_play_async, native_files, kind, volume)


__all__ = ["SoundKind", "attach_context", "play", "play_preview"]
