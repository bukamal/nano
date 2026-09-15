from __future__ import annotations

import os
import sqlite3
from pathlib import Path

APP_DIR_NAME = "nano-offline"
PRIMARY_DB_NAME = "nano.db"
LEGACY_DB_NAME = "qeid.db"


def app_data_dir() -> Path:
    """Return the persistent writable application data directory.

    Flet exposes ``FLET_APP_STORAGE_DATA`` on packaged mobile apps.  Desktop
    development can override the location with ``NANO_DATA_DIR`` (with ``QEID_DATA_DIR`` retained for backward compatibility).  The fallback
    deliberately lives outside the source tree so packaged assets are never
    treated as writable data.
    """
    configured = (
        os.environ.get("FLET_APP_STORAGE_DATA")
        or os.environ.get("NANO_DATA_DIR")
        or os.environ.get("QEID_DATA_DIR")
        or ""
    ).strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        path = Path.home() / ".nano"
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_database(legacy_path: str | Path, target_path: str | Path | None = None) -> bool:
    """One-time migration from the phase-1..5 source-tree database location.

    SQLite's backup API is used instead of a raw file copy so a legacy WAL
    database is migrated consistently. Existing target data is never replaced.
    """
    legacy = Path(legacy_path)
    target = Path(target_path) if target_path is not None else database_path()
    if target.exists() or not legacy.is_file() or legacy.resolve() == target.resolve():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".migrating")
    if temp.exists():
        temp.unlink()
    source = sqlite3.connect(legacy)
    destination = sqlite3.connect(temp)
    try:
        source.backup(destination)
        destination.commit()
        integrity = str(destination.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.lower() != "ok":
            raise RuntimeError(f"فشل ترحيل قاعدة البيانات القديمة: {integrity}")
    finally:
        destination.close()
        source.close()
    os.replace(temp, target)
    return True


def database_path() -> Path:
    base = app_data_dir()
    new_path = base / PRIMARY_DB_NAME
    legacy_path = base / LEGACY_DB_NAME
    if new_path.exists():
        return new_path
    if legacy_path.exists():
        return legacy_path
    return new_path


def backups_dir() -> Path:
    path = app_data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


__all__ = ["app_data_dir", "database_path", "backups_dir", "migrate_legacy_database", "APP_DIR_NAME"]
