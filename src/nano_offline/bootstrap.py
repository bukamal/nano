"""Shared bootstrap for multi-app Nano suite.

Ensures all suite APKs open the same SQLite file when a shared directory is
writable. Private per-app DBs are promoted into the shared folder once.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import traceback
from pathlib import Path
from typing import Callable

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.core import theme
from nano_offline.core import theme_settings
from nano_offline.core.paths import (
    PRIMARY_DB_NAME,
    apply_shared_data_dir,
    database_path,
    migrate_legacy_database,
)
from nano_offline.core.theme import Colors
from nano_offline.views.activation_view import ActivationGate
from nano_offline.views.login_view import LoginGate
from nano_offline.views.splash_view import SplashGate

_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_CUSTOM_FONTS = {
    "Plex": "fonts/IBMPlexSansArabic-Regular.ttf",
    "Plex SemiBold": "fonts/IBMPlexSansArabic-SemiBold.ttf",
}
APP_FONTS = {
    name: rel
    for name, rel in _CUSTOM_FONTS.items()
    if (_FONTS_DIR / Path(rel).name).exists()
}
APP_FONT_FAMILY = "Plex" if "Plex" in APP_FONTS else None

_SHARED_CANDIDATES = (
    "/storage/emulated/0/Documents/NanoShared",
    "/sdcard/Documents/NanoShared",
    "/storage/emulated/0/NanoShared",
    "/sdcard/NanoShared",
)


def resolve_and_set_theme(page: ft.Page, ctx: AppContext) -> str:
    try:
        system_dark = page.platform_brightness == ft.Brightness.DARK
    except Exception:
        system_dark = False
    effective = theme_settings.resolve_effective_mode(
        ctx.settings, system_is_dark=system_dark
    )
    theme.set_mode(effective)
    return effective


def apply_theme(page: ft.Page) -> None:
    if APP_FONTS:
        page.fonts = APP_FONTS
    page.theme = ft.Theme(
        color_scheme_seed=Colors.PRIMARY, font_family=APP_FONT_FAMILY
    )
    page.dark_theme = page.theme
    page.theme_mode = (
        ft.ThemeMode.DARK if theme.is_dark() else ft.ThemeMode.LIGHT
    )


def _sqlite_can_use_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".nano_sqlite_probe.db"
        conn = sqlite3.connect(str(probe), timeout=2.0)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS _probe (id INTEGER)")
            conn.execute("INSERT INTO _probe(id) VALUES (1)")
            conn.commit()
        finally:
            conn.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                p = Path(str(probe) + suffix) if suffix else probe
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        return True
    except Exception:
        return False


def _private_data_dirs() -> list[Path]:
    dirs: list[Path] = []
    for key in ("FLET_APP_STORAGE_DATA", "NANO_DATA_DIR", "QEID_DATA_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            dirs.append(Path(raw).expanduser())
    # Flet Android typical private location pattern (best-effort scan not needed)
    return dirs


def _copy_db_tree(src_db: Path, dest_db: Path) -> None:
    dest_db.parent.mkdir(parents=True, exist_ok=True)
    # Prefer consistent SQLite backup API when possible
    try:
        src = sqlite3.connect(str(src_db))
        dst = sqlite3.connect(str(dest_db))
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()
        return
    except Exception:
        pass
    shutil.copy2(src_db, dest_db)
    for suffix in ("-wal", "-shm"):
        side = Path(str(src_db) + suffix)
        if side.exists():
            try:
                shutil.copy2(side, Path(str(dest_db) + suffix))
            except Exception:
                pass


def _promote_private_db_into_shared(shared: Path) -> None:
    """If shared nano.db is missing/empty of items but a private DB exists, copy it."""
    shared_db = shared / PRIMARY_DB_NAME
    private_dbs: list[Path] = []
    for d in _private_data_dirs():
        candidate = d / PRIMARY_DB_NAME
        if candidate.is_file():
            private_dbs.append(candidate)

    if not private_dbs:
        return

    def _item_count(db_path: Path) -> int:
        try:
            conn = sqlite3.connect(str(db_path), timeout=2.0)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='items'"
                ).fetchone()
                if not row or row[0] == 0:
                    return 0
                return int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            finally:
                conn.close()
        except Exception:
            return 0

    best_private = max(private_dbs, key=_item_count)
    private_count = _item_count(best_private)
    shared_count = _item_count(shared_db) if shared_db.is_file() else 0

    # Promote when shared is empty but private has data
    if private_count > 0 and shared_count == 0:
        try:
            _copy_db_tree(best_private, shared_db)
        except Exception:
            pass


def pin_shared_data_dir_if_possible() -> Path | None:
    """Force NANO_SHARED_DATA_DIR before opening AppContext when possible."""
    existing = (os.environ.get("NANO_SHARED_DATA_DIR") or "").strip()
    if existing:
        path = Path(existing)
        if _sqlite_can_use_dir(path):
            _promote_private_db_into_shared(path)
            apply_shared_data_dir(path)
            return path
        os.environ.pop("NANO_SHARED_DATA_DIR", None)

    for raw in _SHARED_CANDIDATES:
        path = Path(raw)
        if _sqlite_can_use_dir(path):
            _promote_private_db_into_shared(path)
            apply_shared_data_dir(path)
            return path
    return None


def create_context() -> AppContext:
    """Open the suite database (shared when available)."""

    def _open() -> AppContext:
        db_path = database_path()
        legacy_candidates = [
            Path(__file__).resolve().parent.parent.parent / "data" / "nano.db",
            Path(__file__).resolve().parent.parent.parent / "data" / "qeid.db",
        ]
        for legacy in legacy_candidates:
            if legacy.exists():
                try:
                    migrate_legacy_database(legacy, db_path)
                except Exception:
                    pass
                break
        return AppContext.create(db_path)

    pin_shared_data_dir_if_possible()
    try:
        return _open()
    except sqlite3.OperationalError:
        # Shared path became unusable — fall back to private storage.
        os.environ.pop("NANO_SHARED_DATA_DIR", None)
        return _open()


def _show_boot_error(page: ft.Page, err: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    page.controls.clear()
    page.bgcolor = "#0F172A"
    page.add(
        ft.Container(
            expand=True,
            padding=24,
            content=ft.Column(
                [
                    ft.Text("تعذر بدء نانو", size=22, weight=ft.FontWeight.BOLD, color="#F8FAFC"),
                    ft.Text(str(err), size=14, color="#FCA5A5"),
                    ft.Text(
                        detail[-2500:] if len(detail) > 2500 else detail,
                        size=11,
                        color="#94A3B8",
                        selectable=True,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
        )
    )
    page.update()


def run_app(
    page: ft.Page,
    *,
    app_title: str,
    app_id: str,
    build_shell: Callable,
) -> None:
    page.title = app_title
    page.rtl = True
    page.padding = 0
    page.bgcolor = Colors.BACKGROUND if hasattr(Colors, "BACKGROUND") else "#F8FAFC"

    page.controls.clear()
    page.add(
        ft.Container(
            expand=True,
            alignment=ft.alignment.center,
            content=ft.Column(
                [
                    ft.ProgressRing(),
                    ft.Text("جاري التحميل…", size=16, color="#0F766E"),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
            ),
        )
    )
    page.update()

    native_files = NativeFiles()
    try:
        page.overlay.append(native_files)
        page.update()
    except Exception:
        pass

    current_screen = {"value": "boot"}
    state: dict = {"ctx": None}

    def reset_page() -> None:
        page.controls.clear()
        page.appbar = None
        page.floating_action_button = None
        page.navigation_bar = None
        page.bottom_appbar = None
        page.drawer = None
        page.end_drawer = None
        page.overlay.clear()
        try:
            page.overlay.append(native_files)
        except Exception:
            pass
        page.update()

    def open_shell() -> None:
        current_screen["value"] = "shell"
        reset_page()
        build_shell(
            page,
            state["ctx"],
            on_logout=logout,
            native_files=native_files,
            on_theme_changed=open_shell,
        )

    def handle_brightness_change(_=None):
        ctx = state["ctx"]
        if ctx is None:
            return
        before = theme.get_mode()
        after = resolve_and_set_theme(page, ctx)
        if after == before:
            return
        apply_theme(page)
        if current_screen["value"] == "shell":
            open_shell()
        else:
            page.update()

    try:
        page.on_platform_brightness_change = handle_brightness_change
    except Exception:
        pass

    def logout():
        page.window.prevent_close = False
        try:
            state["ctx"].auth.logout()
        except Exception:
            pass
        show_auth()

    def show_activation():
        current_screen["value"] = "activation"
        reset_page()
        ActivationGate(page, state["ctx"], on_success=show_auth).show()

    def show_auth():
        current_screen["value"] = "auth"
        reset_page()
        LoginGate(page, state["ctx"], on_success=open_shell).show()

    def route_after_splash():
        reset_page()
        ctx = state["ctx"]
        try:
            if ctx.license.status().valid:
                if ctx.auth.has_users() and ctx.auth.restore_saved_session() is not None:
                    open_shell()
                else:
                    show_auth()
            else:
                show_activation()
        except Exception as exc:
            _show_boot_error(page, exc)

    def _boot_sync() -> None:
        try:
            # MUST pin shared dir before AppContext opens SQLite.
            pin_shared_data_dir_if_possible()
            state["ctx"] = create_context()
            resolve_and_set_theme(page, state["ctx"])
            apply_theme(page)
            page.bgcolor = Colors.BACKGROUND
            reset_page()
            current_screen["value"] = "splash"
            SplashGate(page, on_ready=route_after_splash).show()
        except Exception as exc:
            _show_boot_error(page, exc)

    _boot_sync()

    async def _refine_shared_storage() -> None:
        """Native channel may refine the path after the control is attached.

        If the path becomes truly shared only after permission is granted, the
        *next* cold start will open the shared DB. We never reopen live SQLite
        connections here (would corrupt in-flight transactions).
        """
        try:
            from nano_offline.shared_storage_boot import prepare_shared_storage

            status = await asyncio.wait_for(
                prepare_shared_storage(
                    native_files,
                    request_permission_if_needed=False,
                ),
                timeout=8.0,
            )
            # Surface a soft warning when apps would see different DBs
            if status.get("needs_permission"):
                import logging as _logging

                _logging.getLogger("nano.shared_storage").warning(
                    "قاعدة البيانات غير مشتركة بين التطبيقات — "
                    "امنح صلاحية «الوصول إلى كل الملفات» ثم أعد تشغيل التطبيق. "
                    "dir=%s",
                    status.get("dir"),
                )
        except Exception:
            pass

    try:
        page.run_task(_refine_shared_storage)
    except Exception:
        pass



__all__ = [
    "APP_FONTS",
    "APP_FONT_FAMILY",
    "apply_theme",
    "create_context",
    "resolve_and_set_theme",
    "run_app",
    "pin_shared_data_dir_if_possible",
]
