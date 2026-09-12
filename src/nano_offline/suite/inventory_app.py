"""نانو المستودع — مواد + جرد + فواتير شراء.

تطبيق مستقل يشترك في نفس قاعدة البيانات مع باقي تطبيقات نانو.
"""

from __future__ import annotations

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.bootstrap import apply_theme, run_app
from nano_offline.core.theme import Colors
from nano_offline.core.toast import toast
from nano_offline.views.items_view import ItemsCenter
from nano_offline.views.invoice_view import InvoiceCenter
from nano_offline.views.stocktake_view import StocktakeCenter
from nano_offline.views.notifications_view import NotificationCenter


def build_inventory_shell(
    page: ft.Page,
    ctx: AppContext,
    *,
    on_logout,
    native_files: NativeFiles,
    on_theme_changed,
):
    page.title = "نانو | المستودع"
    page.rtl = True
    apply_theme(page)
    page.padding = 0
    page.bgcolor = Colors.BACKGROUND

    content = ft.Container(
        expand=True,
        padding=ft.padding.only(left=14, right=14, top=10, bottom=14),
    )

    header_title = ft.Text(
        "المواد", size=20, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY
    )
    header_subtitle = ft.Text("", size=12, color=Colors.TEXT_SECONDARY)

    def set_header(title: str, subtitle: str = "") -> None:
        header_title.value = title
        header_subtitle.value = subtitle or ""
        page.update()

    def notify(text: str):
        toast(page, text)

    selected = {"key": "items"}

    # Centers
    notification_center = NotificationCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_navigate=lambda key: navigate(key),
    )
    invoice_center = InvoiceCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header
    )
    items_center = ItemsCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_open_stocktake=lambda: navigate("stocktake"),
    )
    stocktake_center = StocktakeCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_exit=lambda: navigate("items"),
    )

    centers = {
        "items": items_center.show_center,
        "stocktake": stocktake_center.show_center,
        "purchases": lambda: (
            invoice_center.show_center(),
            # optionally filter to purchase docs if the center supports it
        ),
    }

    def navigate(key: str) -> None:
        selected["key"] = key
        fn = centers.get(key)
        if fn:
            fn()
        refresh_nav()
        page.update()

    def refresh_nav() -> None:
        for btn in nav_row.controls:
            if isinstance(btn, ft.Container) and hasattr(btn, "data"):
                active = btn.data == selected["key"]
                btn.bgcolor = Colors.PRIMARY if active else None
                if btn.content and isinstance(btn.content, ft.Column):
                    for c in btn.content.controls:
                        if isinstance(c, ft.Icon):
                            c.color = Colors.WHITE if active else Colors.TEXT_SECONDARY
                        if isinstance(c, ft.Text):
                            c.color = Colors.WHITE if active else Colors.TEXT_SECONDARY

    def nav_item(key: str, label: str, icon) -> ft.Container:
        return ft.Container(
            data=key,
            content=ft.Column(
                [
                    ft.Icon(icon, size=22, color=Colors.TEXT_SECONDARY),
                    ft.Text(label, size=11, color=Colors.TEXT_SECONDARY),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=8),
            border_radius=12,
            on_click=lambda e, k=key: navigate(k),
        )

    nav_row = ft.Row(
        [
            nav_item("items", "المواد", ft.Icons.INVENTORY_2_OUTLINED),
            nav_item("stocktake", "الجرد", ft.Icons.FACT_CHECK_OUTLINED),
            nav_item("purchases", "المشتريات", ft.Icons.ADD_SHOPPING_CART),
        ],
        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
    )

    bottom_nav = ft.Container(
        content=nav_row,
        bgcolor=Colors.BACKGROUND_ALT,
        border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
        padding=ft.padding.only(top=6, bottom=10),
    )

    header = ft.Container(
        content=ft.Row(
            [
                ft.Column([header_title, header_subtitle], spacing=2, expand=True),
                ft.IconButton(
                    ft.Icons.LOGOUT,
                    tooltip="تسجيل الخروج",
                    on_click=lambda _: on_logout(),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.only(left=16, right=8, top=12, bottom=8),
    )

    page.add(
        ft.Column(
            [header, content, bottom_nav],
            expand=True,
            spacing=0,
        )
    )
    navigate("items")


def main(page: ft.Page):
    run_app(
        page,
        app_title="نانو | المستودع",
        app_id="inventory",
        build_shell=build_inventory_shell,
    )


