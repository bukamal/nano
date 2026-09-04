from __future__ import annotations

"""Centralized, admin-configurable settings for local backups.

Same pattern as ``core/barcode_settings.py``, ``core/invoice_settings.py``,
and ``core/pos_settings.py``: values live in the open-ended ``settings``
key/value table, read fresh with sane defaults, and written only from the
admin "النسخ الاحتياطي" tab (views/admin_view.py).
"""

# --- Automatic backups ---------------------------------------------------#
AUTO_BACKUP_ENABLED_KEY = "backup_auto_on_login"

# --- Local retention -------------------------------------------------------#
RETENTION_COUNT_KEY = "backup_retention_count"

DEFAULT_AUTO_BACKUP_ENABLED = False
DEFAULT_RETENTION_COUNT = 10  # 0 == keep every backup forever (no pruning)

VALID_RETENTION_COUNTS = (0, 5, 10, 20, 50)


def _flag(settings, key: str, default: bool) -> bool:
    raw = settings.get(key, "1" if default else "0")
    return str(raw).strip() == "1"


def auto_backup_enabled(settings) -> bool:
    """Whether Nano should quietly create a backup right after login when
    the existing \"موعد نسخة احتياطية\" reminder rule (see
    ``NotificationService``'s ``backup`` rule) says the last one is overdue.
    Off by default -- a shop that prefers to control exactly when a backup
    file gets written can leave this alone and keep using the manual
    buttons below with no change in behavior."""
    return _flag(settings, AUTO_BACKUP_ENABLED_KEY, DEFAULT_AUTO_BACKUP_ENABLED)


def retention_count(settings) -> int:
    """How many local backup files to keep before the oldest are deleted
    automatically after each new backup (manual or automatic). ``0`` keeps
    every backup forever, matching the app's behavior before this setting
    existed."""
    try:
        value = int(settings.get(RETENTION_COUNT_KEY, str(DEFAULT_RETENTION_COUNT)))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_COUNT
    return value if value in VALID_RETENTION_COUNTS else DEFAULT_RETENTION_COUNT


__all__ = [
    "AUTO_BACKUP_ENABLED_KEY", "RETENTION_COUNT_KEY",
    "DEFAULT_AUTO_BACKUP_ENABLED", "DEFAULT_RETENTION_COUNT",
    "VALID_RETENTION_COUNTS", "auto_backup_enabled", "retention_count",
]
