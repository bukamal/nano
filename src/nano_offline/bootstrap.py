"""Shared bootstrap for multi-app Nano suite.

Splash → activation → login → shell. Designed to never leave a blank white
screen: the first paint is synchronous, and any boot error is shown on-page.
"""

from __future__ import annotations

import asyncio
import os
import traceback
from pathlib import Path
from typing import Callable

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.core import theme
from nano_offline.core import theme_settings
from nano_offline.core.paths import (
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


def _try_default_android_shared_dir() -> None:
    """Best-effort shared path without waiting on native channels.

    Avoids a blank screen if MethodChannel is not ready yet at first frame.
    """
    if os.environ.get("NANO_SHARED_DATA_DIR", "").strip():
        return
    candidates = [
        "/storage/emulated/0/Documents/NanoShared",
        "/sdcard/Documents/NanoShared",
        "/storage/emulated/0/NanoShared",
        "/sdcard/NanoShared",
    ]
    for raw in candidates:
        path = Path(raw)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".nano_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            apply_shared_data_dir(path)
            return
        except Exception:
            continue


def create_context() -> AppContext:
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


def _show_boot_error(page: ft.Page, err: BaseException) -> None:
    """Visible fallback so users never stare at a pure white screen."""
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

    # First paint immediately — never leave an empty page.
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
        """Synchronous boot path — reliable on Android packaged builds."""
        try:
            # Do not block on native MethodChannel at first launch.
            _try_default_android_shared_dir()
            state["ctx"] = create_context()
            resolve_and_set_theme(page, state["ctx"])
            apply_theme(page)
            page.bgcolor = Colors.BACKGROUND
            reset_page()
            current_screen["value"] = "splash"
            SplashGate(page, on_ready=route_after_splash).show()
        except Exception as exc:
            _show_boot_error(page, exc)

    # Prefer sync boot so SeriousPython / Android never waits forever on
    # an async task that never gets scheduled.
    _boot_sync()

    # Optional: refine shared dir via native channel after UI is up (non-blocking).
    async def _refine_shared_storage() -> None:
        try:
            from nano_offline.shared_storage_boot import prepare_shared_storage

            await asyncio.wait_for(prepare_shared_storage(native_files), timeout=5.0)
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
]
