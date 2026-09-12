"""Shared bootstrap for multi-app Nano suite.

Each standalone app (accounting / inventory / POS) imports from here so that
splash → activation → login → shell flow, theme, fonts, and AppContext
creation stay identical while only the shell content differs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.core import backup_settings
from nano_offline.core import sound
from nano_offline.core import theme
from nano_offline.core import theme_settings
from nano_offline.core.paths import database_path, migrate_legacy_database
from nano_offline.core.theme import Colors
from nano_offline.core.toast import toast
from nano_offline.shared_storage_boot import prepare_shared_storage
from nano_offline.views.activation_view import ActivationGate
from nano_offline.views.login_view import LoginGate
from nano_offline.views.splash_view import SplashGate

# Fonts live next to the original main.py (src/assets/fonts).
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


def create_context() -> AppContext:
    """Open (or create) the shared database and build AppContext."""
    db_path = database_path()
    # One-time migration from old source-tree locations if present.
    legacy_candidates = [
        Path(__file__).resolve().parent.parent.parent / "data" / "nano.db",
        Path(__file__).resolve().parent.parent.parent / "data" / "qeid.db",
    ]
    for legacy in legacy_candidates:
        if legacy.exists():
            migrate_legacy_database(legacy, db_path)
            break
    return AppContext.create(db_path)


def run_app(
    page: ft.Page,
    *,
    app_title: str,
    app_id: str,
    build_shell: Callable,
) -> None:
    """Common entry used by every Nano suite app.

    Parameters
    ----------
    page:
        Flet page.
    app_title:
        Window / taskbar title (e.g. "نانو محاسبة").
    app_id:
        Short identifier used for logging / future telemetry ("accounting",
        "inventory", "pos").
    build_shell:
        Callable(page, ctx, *, on_logout, native_files, on_theme_changed)
        that constructs the app-specific UI after successful login.
    """
    page.title = app_title
    page.rtl = True
    page.padding = 0

    native_files = NativeFiles()
    # Keep the control mounted so method channels stay alive.
    try:
        page.overlay.append(native_files)
        page.update()
    except Exception:
        pass

    current_screen = {"value": "splash"}
    # ctx is created after shared-storage resolve so Android multi-APK
    # suites open the same nano.db under Documents/NanoShared when possible.
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
        state["ctx"].auth.logout()
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
        if ctx.license.status().valid:
            if ctx.auth.has_users() and ctx.auth.restore_saved_session() is not None:
                open_shell()
            else:
                show_auth()
        else:
            show_activation()

    async def _boot() -> None:
        # Resolve cross-APK shared dir before opening SQLite.
        try:
            await prepare_shared_storage(native_files)
        except Exception:
            pass
        state["ctx"] = create_context()
        resolve_and_set_theme(page, state["ctx"])
        apply_theme(page)
        page.bgcolor = Colors.BACKGROUND
        SplashGate(page, on_ready=route_after_splash).show()

    page.run_task(_boot)


__all__ = [
    "APP_FONTS",
    "APP_FONT_FAMILY",
    "apply_theme",
    "create_context",
    "resolve_and_set_theme",
    "run_app",
]
