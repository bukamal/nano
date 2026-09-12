"""نانو المحاسبة — عملاء + موردون + مالية + تقارير + إدارة.

تطبيق مستقل يشترك في نفس قاعدة البيانات مع باقي تطبيقات نانو.
"""

from __future__ import annotations

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.bootstrap import apply_theme, run_app
from nano_offline.core.theme import Colors
from nano_offline.core.toast import toast
from nano_offline.views.admin_view import AdminCenter
from nano_offline.views.dashboard_view import DashboardCenter
from nano_offline.views.finance_view import FinanceCenter
from nano_offline.views.invoice_view import InvoiceCenter
from nano_offline.views.notifications_view import NotificationCenter
from nano_offline.views.parties_view import PartyCenter
from nano_offline.views.reports_view import ReportsCenter
from nano_offline.views.security_view import SecurityCenter


def build_accounting_shell(
    page: ft.Page,
    ctx: AppContext,
    *,
    on_logout,
    native_files: NativeFiles,
    on_theme_changed,
):
    page.title = "نانو | المحاسبة"
    page.rtl = True
    apply_theme(page)
    page.padding = 0
    page.bgcolor = Colors.BACKGROUND

    content = ft.Container(
        expand=True,
        padding=ft.padding.only(left=14, right=14, top=10, bottom=14),
    )

    header_title = ft.Text(
        "لوحة التحكم", size=20, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY
    )
    header_subtitle = ft.Text(
        "نظرة عامة", size=12, color=Colors.TEXT_SECONDARY
    )

    def set_header(title: str, subtitle: str = "") -> None:
        header_title.value = title
        header_subtitle.value = subtitle or ""
        page.update()

    def notify(text: str):
        toast(page, text)

    selected = {"key": "dashboard"}

    notification_center = NotificationCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_navigate=lambda key: navigate(key),
    )
    invoice_center = InvoiceCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header
    )
    finance_center = FinanceCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header
    )
    reports_center = ReportsCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header
    )
    admin_center = AdminCenter(
        page, ctx, content, on_logout=on_logout, native_files=native_files,
        on_theme_changed=on_theme_changed,
    )
    party_center = PartyCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header
    )
    security_center = SecurityCenter(
        page, ctx, content, on_title_change=set_header
    )

    def open_receipt(customer_id=None, amount=None):
        navigate("finance")

    def open_sale():
        navigate("invoices")

    def open_purchase():
        navigate("invoices")

    dashboard_center = DashboardCenter(
        page,
        ctx,
        content,
        native_files=native_files,
        on_title_change=set_header,
        on_navigate=lambda key: navigate(key),
        on_open_sale=open_sale,
        on_open_purchase=open_purchase,
        on_open_notifications=notification_center.open_panel,
        on_open_receipt=open_receipt,
    )

    centers = {
        "dashboard": dashboard_center.show_center,
        "customers": lambda: party_center.show_center(ctx.customers, "العملاء"),
        "suppliers": lambda: party_center.show_center(ctx.suppliers, "الموردون"),
        "invoices": invoice_center.show_center,
        "finance": finance_center.show_center,
        "reports": reports_center.show_center,
        "admin": admin_center.show_center,
        "security": security_center.show_center,
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
                            c.color = (
                                Colors.WHITE if active else Colors.TEXT_SECONDARY
                            )
                        if isinstance(c, ft.Text):
                            c.color = (
                                Colors.WHITE if active else Colors.TEXT_SECONDARY
                            )

    def nav_item(key: str, label: str, icon) -> ft.Container:
        return ft.Container(
            data=key,
            content=ft.Column(
                [
                    ft.Icon(icon, size=20, color=Colors.TEXT_SECONDARY),
                    ft.Text(label, size=10, color=Colors.TEXT_SECONDARY),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=10,
            on_click=lambda e, k=key: navigate(k),
        )

    # Bottom nav — focused on accounting domains
    nav_row = ft.Row(
        [
            nav_item("dashboard", "الرئيسية", ft.Icons.HOME_OUTLINED),
            nav_item("customers", "العملاء", ft.Icons.PEOPLE_OUTLINE),
            nav_item("finance", "المالية", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED),
            nav_item("invoices", "الفواتير", ft.Icons.RECEIPT_LONG_OUTLINED),
            nav_item("reports", "التقارير", ft.Icons.BAR_CHART_OUTLINED),
        ],
        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
    )

    # More sheet for admin / security / suppliers
    def open_more(_=None):
        def close_sheet(_=None):
            page.close(more_sheet)

        more_sheet = ft.BottomSheet(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("المزيد", size=16, weight=ft.FontWeight.BOLD),
                        ft.ListTile(
                            leading=ft.Icon(ft.Icons.LOCAL_SHIPPING_OUTLINED),
                            title=ft.Text("الموردون"),
                            on_click=lambda _: (close_sheet(), navigate("suppliers")),
                        ),
                        ft.ListTile(
                            leading=ft.Icon(ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED),
                            title=ft.Text("الإدارة"),
                            on_click=lambda _: (close_sheet(), navigate("admin")),
                        ),
                        ft.ListTile(
                            leading=ft.Icon(ft.Icons.SECURITY),
                            title=ft.Text("الأمان"),
                            on_click=lambda _: (close_sheet(), navigate("security")),
                        ),
                        ft.ListTile(
                            leading=ft.Icon(ft.Icons.LOGOUT),
                            title=ft.Text("تسجيل الخروج"),
                            on_click=lambda _: (close_sheet(), on_logout()),
                        ),
                    ],
                    tight=True,
                    spacing=0,
                ),
                padding=20,
            ),
            open=True,
        )
        page.open(more_sheet)

    more_btn = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.MORE_HORIZ, size=20, color=Colors.TEXT_SECONDARY),
                ft.Text("المزيد", size=10, color=Colors.TEXT_SECONDARY),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
        border_radius=10,
        on_click=open_more,
    )
    nav_row.controls.append(more_btn)

    bottom_nav = ft.Container(
        content=nav_row,
        bgcolor=Colors.BACKGROUND_ALT,
        border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
        padding=ft.padding.only(top=4, bottom=8),
    )

    header = ft.Container(
        content=ft.Row(
            [
                ft.Column([header_title, header_subtitle], spacing=2, expand=True),
                ft.IconButton(
                    ft.Icons.NOTIFICATIONS_OUTLINED,
                    on_click=lambda _: notification_center.open_panel(),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.only(left=16, right=4, top=10, bottom=6),
    )

    page.add(
        ft.Column(
            [header, content, bottom_nav],
            expand=True,
            spacing=0,
        )
    )
    navigate("dashboard")


def main(page: ft.Page):
    run_app(
        page,
        app_title="نانو | المحاسبة",
        app_id="accounting",
        build_shell=build_accounting_shell,
    )


ft.app(target=main)
