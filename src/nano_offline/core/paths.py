from __future__ import annotations

import os
import sqlite3
from pathlib import Path

APP_DIR_NAME = "nano-offline"
PRIMARY_DB_NAME = "nano.db"
LEGACY_DB_NAME = "qeid.db"


def app_data_dir() -> Path:
    """Return the persistent writable application data directory.

    Priority order (first match wins):

    1. ``NANO_SHARED_DATA_DIR`` — multi-app shared location (only if usable).
    2. ``FLET_APP_STORAGE_DATA`` — Flet private storage on packaged mobile.
    3. ``NANO_DATA_DIR`` / ``QEID_DATA_DIR`` — desktop override.
    4. Fallback ``~/.nano``.
    """
    candidates: list[Path] = []
    for key in (
        "NANO_SHARED_DATA_DIR",
        "FLET_APP_STORAGE_DATA",
        "NANO_DATA_DIR",
        "QEID_DATA_DIR",
    ):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            candidates.append(Path(raw).expanduser())
    candidates.append(Path.home() / ".nano")

    last_err: Exception | None = None
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            # Ensure the process can create files here (not only the directory).
            probe = path / ".nano_dir_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return path
        except Exception as exc:
            last_err = exc
            continue
    # Last resort: relative ./data next to cwd
    fallback = Path("data").resolve()
    try:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    except Exception:
        if last_err:
            raise last_err
        raise RuntimeError("لا يمكن إنشاء مجلد بيانات قابل للكتابة")


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


def apply_shared_data_dir(path: str | Path | None) -> Path | None:
    """Pin ``NANO_SHARED_DATA_DIR`` so every subsequent ``app_data_dir()`` call
    resolves to the cross-APK shared location returned by the native layer.

    Call this once at startup on Android after ``NativeFiles.get_shared_data_dir()``
    succeeds. Returns the resolved directory, or ``None`` if *path* is empty.
    """
    if not path:
        return None
    resolved = Path(str(path)).expanduser()
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    os.environ["NANO_SHARED_DATA_DIR"] = str(resolved)
    return resolved


def is_shared_data_dir_active() -> bool:
    """True when an explicit shared directory has been configured."""
    return bool(os.environ.get("NANO_SHARED_DATA_DIR", "").strip())


__all__ = [
    "app_data_dir",
    "database_path",
    "backups_dir",
    "migrate_legacy_database",
    "apply_shared_data_dir",
    "is_shared_data_dir_active",
    "APP_DIR_NAME",
    "PRIMARY_DB_NAME",
]
