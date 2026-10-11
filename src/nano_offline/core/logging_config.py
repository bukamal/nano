"""Central logging + uncaught-exception capture for Nano.

Why this exists
---------------
The codebase has hundreds of ``except Exception`` handlers, many of which used
to silently ``pass``. When a write path in the accounting engine fails there is
currently no trace anywhere -- the UI just shows stale data and the bug is lost.
This module gives every entry point (the legacy ``src/main.py`` app and all
suite apps through ``bootstrap.run_app``) one consistent place to record
warnings/errors, plus a small rotating log file on the device that can be
exported from the admin center for support.

Design
------
* :func:`setup_logging` is idempotent and safe to call from every entry point;
  the first call wins.
* A rotating file handler under ``app_data_dir()/logs/nano.log`` keeps the
  on-device footprint bounded (1 MB x 3 backups). If the directory is not
  writable the app keeps running with only the console handler -- logging must
  never be able to crash startup.
* Uncaught exceptions (main thread and worker threads) are logged and appended
  to ``logs/crash.log`` with the app version, so a "the app closed by itself"
  report can be diagnosed after the fact.
* Level is controlled by ``NANO_LOG_LEVEL`` (default ``INFO``).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from nano_offline.core.paths import app_data_dir
from nano_offline.version import APP_VERSION, BUILD_NUMBER

__all__ = [
    "setup_logging",
    "get_logger",
    "log_file_path",
    "crash_file_path",
    "read_crash_log",
]

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_LOG_DIR_NAME = "logs"
_LOG_FILE_NAME = "nano.log"
_CRASH_FILE_NAME = "crash.log"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_configured = False
_lock = threading.Lock()
_log_dir: Path | None = None


def _resolve_log_dir() -> Path | None:
    try:
        path = app_data_dir() / _LOG_DIR_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def log_file_path() -> Path | None:
    return (_log_dir / _LOG_FILE_NAME) if _log_dir is not None else None


def crash_file_path() -> Path | None:
    return (_log_dir / _CRASH_FILE_NAME) if _log_dir is not None else None


def _level_from_env() -> int:
    raw = (os.environ.get("NANO_LOG_LEVEL") or "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


def _append_crash_report(kind: str, exc_type, exc, tb) -> None:
    """Persist one uncaught exception to ``crash.log`` (best-effort)."""
    path = crash_file_path()
    if path is None:
        return
    try:
        header = (
            f"\n===== {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
            f"[{kind}] Nano {APP_VERSION} (build {BUILD_NUMBER}) =====\n"
        )
        body = "".join(traceback.format_exception(exc_type, exc, tb))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(header)
            fh.write(body)
    except Exception:
        pass


def _install_excepthooks() -> None:
    original_hook = sys.excepthook
    original_thread_hook = getattr(threading, "excepthook", None)

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("nano.crash").critical(
            "uncaught exception", exc_info=(exc_type, exc, tb)
        )
        _append_crash_report("main", exc_type, exc, tb)
        original_hook(exc_type, exc, tb)

    def _thread_excepthook(args):
        logging.getLogger("nano.crash").critical(
            "uncaught exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _append_crash_report("thread", args.exc_type, args.exc_value, args.exc_traceback)
        if original_thread_hook is not None:
            original_thread_hook(args)

    sys.excepthook = _excepthook
    if original_thread_hook is not None:
        threading.excepthook = _thread_excepthook


def setup_logging(*, level: int | None = None, console: bool = True) -> None:
    """Configure the root logger once. Safe to call from every entry point."""
    global _configured, _log_dir
    with _lock:
        if _configured:
            return
        _configured = True

    _log_dir = _resolve_log_dir()
    resolved_level = level if level is not None else _level_from_env()
    formatter = logging.Formatter(_LOG_FORMAT)

    root = logging.getLogger()
    # Replace anything a host runtime (Flet, pytest, ...) may have pre-installed
    # so our format/handlers are the single source, but never below the
    # requested level.
    root.handlers.clear()
    root.setLevel(min(resolved_level, logging.DEBUG))

    file_path = log_file_path()
    if file_path is not None:
        file_handler = logging.handlers.RotatingFileHandler(
            file_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(resolved_level)
        root.addHandler(file_handler)

    if console:
        # stderr only: Flet owns stdout for its own control protocol.
        console_handler = logging.StreamHandler(stream=sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(resolved_level)
        root.addHandler(console_handler)

    _install_excepthooks()
    logging.getLogger("nano.startup").info(
        "logging ready (Nano %s build %s) -> %s",
        APP_VERSION,
        BUILD_NUMBER,
        file_path or "console-only",
    )


def get_logger(name: str = "nano_offline") -> logging.Logger:
    return logging.getLogger(name)


def read_crash_log(max_chars: int = 20_000) -> str:
    """Return the tail of ``crash.log`` for the admin/support screen ('' if none)."""
    path = crash_file_path()
    if path is None or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-max_chars:]
