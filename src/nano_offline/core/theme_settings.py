from __future__ import annotations

"""Admin-configurable settings for the app's night-mode (dark) theme.

Same pattern as ``core/sound_settings.py`` / ``core/barcode_settings.py``:
values live in the open-ended ``settings`` key/value table, read fresh
wherever needed with sane defaults, and written only from the admin
"المظهر" tab (views/admin_view.py).

This module only knows about *preferences* (what the user asked for) and
how to *resolve* them into one concrete answer ("light" or "dark") given
the current time and the device's system brightness. It has no idea how to
actually repaint the app — that's ``core/theme.py`` (the token tables) and
``main.py`` (the "rebuild everything" glue), both of which read
``resolve_effective_mode()`` below.

Two independent knobs, combined:
  1. ``mode`` — light / dark / system (follow the OS).
  2. an optional smart *schedule* — "force dark between these two hours
     regardless of the mode above", e.g. 19:00-06:00. This is the "modern"
     touch on top of a plain toggle: it activates automatically, on a
     timer, without the user having to remember to flip anything by hand.
"""

from datetime import datetime

MODE_KEY = "theme_mode"
SCHEDULE_ENABLED_KEY = "theme_schedule_enabled"
SCHEDULE_START_KEY = "theme_schedule_start_hour"
SCHEDULE_END_KEY = "theme_schedule_end_hour"

MODE_LIGHT = "light"
MODE_DARK = "dark"
MODE_SYSTEM = "system"
VALID_MODES = (MODE_LIGHT, MODE_DARK, MODE_SYSTEM)

DEFAULT_MODE = MODE_SYSTEM
DEFAULT_SCHEDULE_ENABLED = False
# 7pm to 6am: covers a typical evening/night usage window without needing
# per-user tuning as a first default — still fully editable from the admin
# "المظهر" tab.
DEFAULT_SCHEDULE_START = 19
DEFAULT_SCHEDULE_END = 6

MODE_LABELS = {
    MODE_LIGHT: "فاتح",
    MODE_DARK: "داكن",
    MODE_SYSTEM: "تلقائي حسب النظام",
}


def get_mode_preference(settings) -> str:
    """The raw user choice: ``"light"``, ``"dark"``, or ``"system"``."""
    raw = str(settings.get(MODE_KEY, DEFAULT_MODE)).strip().lower()
    return raw if raw in VALID_MODES else DEFAULT_MODE


def set_mode_preference(settings, mode: str) -> None:
    settings.set(MODE_KEY, mode if mode in VALID_MODES else DEFAULT_MODE)


def schedule_enabled(settings) -> bool:
    return str(settings.get(SCHEDULE_ENABLED_KEY, "1" if DEFAULT_SCHEDULE_ENABLED else "0")).strip() == "1"


def schedule_hours(settings) -> tuple[int, int]:
    """(start_hour, end_hour), each 0-23. May wrap past midnight (e.g. 19 -> 6)."""

    def _hour(key: str, default: int) -> int:
        try:
            value = int(float(settings.get(key, str(default))))
        except (TypeError, ValueError):
            return default
        return max(0, min(23, value))

    return _hour(SCHEDULE_START_KEY, DEFAULT_SCHEDULE_START), _hour(SCHEDULE_END_KEY, DEFAULT_SCHEDULE_END)


def set_schedule(settings, *, enabled: bool, start_hour: int, end_hour: int) -> None:
    settings.set_many({
        SCHEDULE_ENABLED_KEY: "1" if enabled else "0",
        SCHEDULE_START_KEY: str(max(0, min(23, int(start_hour)))),
        SCHEDULE_END_KEY: str(max(0, min(23, int(end_hour)))),
    })


def resolve_effective_mode(settings, *, system_is_dark: bool, now: datetime | None = None) -> str:
    """Combine the stored preference + schedule into one ``"light"``/``"dark"`` answer.

    The schedule (when enabled) wins over the plain mode preference while
    the current hour falls inside its window — the idea being "always dark
    at night" as a standing rule, on top of whichever base choice
    (light/dark/system) applies the rest of the day. Outside the window, or
    with the schedule off, this falls back to the plain preference (with
    "system" resolved against ``system_is_dark``).
    """
    if schedule_enabled(settings):
        start, end = schedule_hours(settings)
        hour = (now or datetime.now()).hour
        in_window = (start <= hour < end) if start < end else (hour >= start or hour < end)
        if in_window:
            return MODE_DARK

    pref = get_mode_preference(settings)
    if pref == MODE_SYSTEM:
        return MODE_DARK if system_is_dark else MODE_LIGHT
    return pref


__all__ = [
    "MODE_KEY", "SCHEDULE_ENABLED_KEY", "SCHEDULE_START_KEY", "SCHEDULE_END_KEY",
    "MODE_LIGHT", "MODE_DARK", "MODE_SYSTEM", "VALID_MODES",
    "DEFAULT_MODE", "DEFAULT_SCHEDULE_ENABLED", "DEFAULT_SCHEDULE_START", "DEFAULT_SCHEDULE_END",
    "MODE_LABELS",
    "get_mode_preference", "set_mode_preference",
    "schedule_enabled", "schedule_hours", "set_schedule",
    "resolve_effective_mode",
]
