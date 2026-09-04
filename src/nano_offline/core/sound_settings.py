from __future__ import annotations

"""Centralized, admin-configurable settings for the app-wide sound system.

Same pattern as ``core/barcode_settings.py`` / ``core/pos_settings.py``:
values live in the open-ended ``settings`` key/value table, read fresh
wherever needed with sane defaults, and written only from the admin
"الصوت" tab (views/admin_view.py).

This module only knows about *reading* preferences. The actual playback
engine (choosing which audio file to play and calling into flet-audio)
lives in ``core/sound.py``, which is the module that reads these.
"""

# --- Master switches ---------------------------------------------------#
ENABLED_KEY = "sound_system_enabled"
VOLUME_KEY = "sound_system_volume"

# --- Per-category toggles ------------------------------------------------#
# These map 1:1 onto the four ``ToastKind`` values in core/toast.py, since
# every sound in the app is triggered through that single choke point --
# see core/sound.py's module docstring for why.
KIND_SUCCESS_KEY = "sound_kind_success_enabled"
KIND_ERROR_KEY = "sound_kind_error_enabled"
KIND_WARNING_KEY = "sound_kind_warning_enabled"
KIND_INFO_KEY = "sound_kind_info_enabled"
# Two event-specific kinds layered on top of the four generic toast kinds
# -- 'scan' (barcode matched in POS/stocktake) and 'save' (invoice/payment
# committed) each get their own tone and their own on/off switch, since a
# cashier may want scan feedback on every item but not want a chime on
# every minor info toast, or vice versa.
KIND_SCAN_KEY = "sound_kind_scan_enabled"
KIND_SAVE_KEY = "sound_kind_save_enabled"
# A third event-specific kind: destructive delete actions (invoice/item/
# party/expense/category/unit/voucher). Kept separate from 'error' (a
# delete succeeding is not a failure) and from 'success' (an admin may
# want the two audibly distinct, since one is routine and the other is
# irreversible) with its own on/off switch, same reasoning as scan/save.
KIND_DELETE_KEY = "sound_kind_delete_enabled"

DEFAULT_ENABLED = True
DEFAULT_VOLUME = 70  # percent, 0-100
DEFAULT_KIND_SUCCESS = True
DEFAULT_KIND_ERROR = True
DEFAULT_KIND_WARNING = True
# "info" toasts are the most frequent/least significant of the four in this
# app's actual message mix (see toast.py's _infer_kind) -- defaulting this
# one off keeps the sound system feeling deliberate rather than chatty,
# while success/error/warning (which each mark something the user should
# actually notice) stay on. Purely a starting point -- admin can flip it.
DEFAULT_KIND_INFO = False
# scan/save default on: they're the two events this update specifically
# added distinct tones for, so a fresh install should actually hear them.
DEFAULT_KIND_SCAN = True
DEFAULT_KIND_SAVE = True
# Default on, same reasoning as scan/save: this update specifically added
# a distinct tone for delete actions, so a fresh install should hear it.
DEFAULT_KIND_DELETE = True

VALID_VOLUME_RANGE = (0, 100)

_KIND_KEYS = {
    "success": (KIND_SUCCESS_KEY, DEFAULT_KIND_SUCCESS),
    "error": (KIND_ERROR_KEY, DEFAULT_KIND_ERROR),
    "warning": (KIND_WARNING_KEY, DEFAULT_KIND_WARNING),
    "info": (KIND_INFO_KEY, DEFAULT_KIND_INFO),
    "scan": (KIND_SCAN_KEY, DEFAULT_KIND_SCAN),
    "save": (KIND_SAVE_KEY, DEFAULT_KIND_SAVE),
    "delete": (KIND_DELETE_KEY, DEFAULT_KIND_DELETE),
}


def _flag(settings, key: str, default: bool) -> bool:
    raw = settings.get(key, "1" if default else "0")
    return str(raw).strip() == "1"


def sound_enabled(settings) -> bool:
    """Master on/off switch for the whole sound system."""
    return _flag(settings, ENABLED_KEY, DEFAULT_ENABLED)


def sound_volume_percent(settings) -> int:
    try:
        value = int(float(settings.get(VOLUME_KEY, str(DEFAULT_VOLUME))))
    except (TypeError, ValueError):
        return DEFAULT_VOLUME
    lo, hi = VALID_VOLUME_RANGE
    return max(lo, min(hi, value))


def sound_volume(settings) -> float:
    """Volume as a 0.0-1.0 fraction, the unit flet-audio's ``Audio.volume`` expects."""
    return sound_volume_percent(settings) / 100.0


def kind_enabled(settings, kind: str) -> bool:
    entry = _KIND_KEYS.get(kind)
    if entry is None:
        return False
    key, default = entry
    return _flag(settings, key, default)


__all__ = [
    "ENABLED_KEY", "VOLUME_KEY",
    "KIND_SUCCESS_KEY", "KIND_ERROR_KEY", "KIND_WARNING_KEY", "KIND_INFO_KEY",
    "KIND_SCAN_KEY", "KIND_SAVE_KEY", "KIND_DELETE_KEY",
    "DEFAULT_ENABLED", "DEFAULT_VOLUME",
    "DEFAULT_KIND_SUCCESS", "DEFAULT_KIND_ERROR", "DEFAULT_KIND_WARNING", "DEFAULT_KIND_INFO",
    "DEFAULT_KIND_SCAN", "DEFAULT_KIND_SAVE", "DEFAULT_KIND_DELETE",
    "VALID_VOLUME_RANGE",
    "sound_enabled", "sound_volume_percent", "sound_volume", "kind_enabled",
]
