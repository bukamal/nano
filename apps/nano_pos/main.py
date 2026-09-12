"""نانو نقطة البيع — تطبيق مستقل يفتح مباشرة على واجهة البيع.

يشترك في نفس قاعدة البيانات مع تطبيقات المحاسبة والمستودع عبر
``NANO_SHARED_DATA_DIR`` أو المسار الافتراضي ``~/.nano/nano.db``.
"""

from __future__ import annotations

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.bootstrap import apply_theme, resolve_and_set_theme, run_app
from nano_offline.core.theme import Colors
from nano_offline.core.toast import toast
from nano_offline.views.pos_view import POSCenter


def build_pos_shell(
    page: ft.Page,
    ctx: AppContext,
    *,
    on_logout,
    native_files: NativeFiles,
    on_theme_changed,
):
    """Shell مخصص لنقطة البيع فقط — بدون شريط تنقل جانبي أو سفلي."""
    page.title = "نانو | نقطة البيع"
    page.rtl = True
    apply_theme(page)
    page.padding = 0
    page.bgcolor = Colors.BACKGROUND

    content = ft.Container(expand=True, padding=0)

    def set_header(title: str, subtitle: str = "") -> None:
        # POS fullscreen manages its own header; keep a no-op for API parity.
        pass

    def notify(text: str):
        toast(page, text)

    pos_center = POSCenter(
        page,
        ctx,
        content,
        native_files=native_files,
        on_title_change=set_header,
        on_fullscreen_enter=lambda: None,  # already the only screen
        on_fullscreen_exit=on_logout,      # خروج من POS = تسجيل خروج / إغلاق
        on_saved=None,
    )

    # في هذا التطبيق POS هو الشاشة الوحيدة.
    page.add(
        ft.Column(
            [
                content,
            ],
            expand=True,
            spacing=0,
        )
    )
    pos_center.show_center()
    page.update()


def main(page: ft.Page):
    run_app(
        page,
        app_title="نانو | نقطة البيع",
        app_id="pos",
        build_shell=build_pos_shell,
    )


ft.app(target=main)
