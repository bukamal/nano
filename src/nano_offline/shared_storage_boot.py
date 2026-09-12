"""Apply Android shared storage before opening the database.

Call ``await prepare_shared_storage(native_files)`` as early as possible in
the Flet ``main`` / ``run_app`` path (before ``AppContext.create``).
"""

from __future__ import annotations

import logging
from typing import Any

from nano_offline.core.paths import apply_shared_data_dir, is_shared_data_dir_active

logger = logging.getLogger("nano.shared_storage")


async def prepare_shared_storage(native_files: Any | None) -> dict:
    """Resolve and activate the cross-APK shared data directory.

    Returns a small status dict suitable for diagnostics / admin UI.
    Safe to call on desktop (no-ops if the native methods are unavailable).
    """
    status: dict = {
        "active": is_shared_data_dir_active(),
        "dir": None,
        "truly_shared": None,
        "has_permission": None,
        "error": None,
    }
    if native_files is None:
        status["error"] = "no_native_files"
        return status

    try:
        shared_dir = await native_files.get_shared_data_dir()
        if shared_dir:
            applied = apply_shared_data_dir(shared_dir)
            status["dir"] = str(applied) if applied else shared_dir
            status["active"] = True
        diag = await native_files.diagnose_shared_storage()
        if isinstance(diag, dict):
            status["truly_shared"] = bool(diag.get("truly_shared"))
            status["has_permission"] = bool(diag.get("has_storage_permission"))
            status["dir"] = diag.get("dir") or status["dir"]
            if status["dir"] and not is_shared_data_dir_active():
                apply_shared_data_dir(status["dir"])
                status["active"] = True
    except Exception as exc:
        status["error"] = str(exc)
        logger.warning("shared storage prepare failed: %s", exc)

    return status


__all__ = ["prepare_shared_storage"]
