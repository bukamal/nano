"""Apply Android shared storage before / during opening the database.

Call ``await prepare_shared_storage(native_files)`` as early as possible in
the Flet ``main`` / ``run_app`` path. On Android suite APKs this is what
makes accounting / inventory / POS open the *same* ``nano.db``.

Without ``MANAGE_EXTERNAL_STORAGE`` (All files access) on Android 11+, the
native layer falls back to a private per-app directory → each APK sees an
empty or different database. That is the root cause of "التطبيقات لا تقرأ
قاعدة البيانات".
"""

from __future__ import annotations

import logging
from typing import Any

from nano_offline.core.paths import apply_shared_data_dir, is_shared_data_dir_active

logger = logging.getLogger("nano.shared_storage")


async def prepare_shared_storage(
    native_files: Any | None,
    *,
    request_permission_if_needed: bool = False,
) -> dict:
    """Resolve and activate the cross-APK shared data directory.

    Returns a status dict suitable for diagnostics / admin UI:

    - ``active``: NANO_SHARED_DATA_DIR is set
    - ``dir``: resolved directory path
    - ``truly_shared``: path is outside private app sandboxes
    - ``has_permission``: All-files / legacy storage permission granted
    - ``needs_permission``: True when path is not truly shared and permission missing
    - ``error``: optional error string

    Safe to call on desktop (no-ops if native methods are unavailable).
    """
    status: dict = {
        "active": is_shared_data_dir_active(),
        "dir": None,
        "truly_shared": None,
        "has_permission": None,
        "needs_permission": False,
        "error": None,
    }
    if native_files is None:
        status["error"] = "no_native_files"
        return status

    try:
        # 1) Ask native for the best available directory
        shared_dir = await native_files.get_shared_data_dir()
        if shared_dir:
            applied = apply_shared_data_dir(shared_dir)
            status["dir"] = str(applied) if applied else shared_dir
            status["active"] = True

        # 2) Full diagnostics (path, size, permission, truly_shared flag)
        diag = await native_files.diagnose_shared_storage()
        if isinstance(diag, dict):
            status["truly_shared"] = bool(diag.get("truly_shared"))
            status["has_permission"] = bool(diag.get("has_storage_permission"))
            status["dir"] = diag.get("dir") or status["dir"]
            if status["dir"] and not is_shared_data_dir_active():
                apply_shared_data_dir(status["dir"])
                status["active"] = True

        # 3) Detect the classic failure mode: private fallback
        if status.get("truly_shared") is False and not status.get("has_permission"):
            status["needs_permission"] = True
            logger.warning(
                "shared storage is NOT cross-app (private fallback). "
                "dir=%s has_permission=%s — grant All files access then restart",
                status.get("dir"),
                status.get("has_permission"),
            )
            if request_permission_if_needed:
                try:
                    await native_files.request_manage_storage()
                    status["permission_prompt"] = "opened"
                except Exception as exc:
                    status["permission_prompt_error"] = str(exc)

        logger.info(
            "shared storage status: active=%s truly_shared=%s dir=%s",
            status.get("active"),
            status.get("truly_shared"),
            status.get("dir"),
        )
    except Exception as exc:
        status["error"] = str(exc)
        logger.warning("shared storage prepare failed: %s", exc)

    return status


__all__ = ["prepare_shared_storage"]
