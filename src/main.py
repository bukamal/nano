from __future__ import annotations

from pathlib import Path

import flet as ft
from flet_native_files import NativeFiles

from qeid_offline.app_context import AppContext
from qeid_offline.core.paths import database_path, migrate_legacy_database
from qeid_offline.views.activation_view import ActivationGate
from qeid_offline.views.admin_view import AdminCenter
from qeid_offline.views.finance_view import FinanceCenter
from qeid_offline.views.invoice_view import InvoiceCenter
from qeid_offline.views.reports_view import ReportsCenter

APP_DB = database_path()
LEGACY_APP_DB = Path(__file__).resolve().parent.parent / "data" / "qeid.db"


def build_shell(page: ft.Page, ctx: AppContext, *, on_logout, native_files: NativeFiles):
    page.title = "قيد - أوفلاين"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = "#F8FAFC"

    content = ft.Container(expand=True, padding=16)

    def money(value):
        return f"{float(value or 0):,.2f}"

    def notify(text: str):
        page.open(ft.SnackBar(ft.Text(text)))

    def metric(title, value):
        return ft.Container(
            content=ft.Column(
                [ft.Text(title, size=12, color="#64748B"), ft.Text(value, size=20, weight=ft.FontWeight.BOLD)],
                spacing=4,
            ),
            padding=14,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=12,
            bgcolor="#FFFFFF",
        )

    def show_dashboard():
        summary = ctx.dashboard.summary()
        content.content = ft.Column(
            [
                ft.Text("لوحة التحكم", size=24, weight=ft.FontWeight.BOLD),
                ft.ResponsiveRow(
                    [
                        ft.Container(metric("المبيعات", money(summary["sales"])), col={"xs": 6, "md": 3}),
                        ft.Container(metric("الربح الصافي", money(summary["net_profit"])), col={"xs": 6, "md": 3}),
                        ft.Container(metric("ذمم العملاء", money(summary["receivables"])), col={"xs": 6, "md": 3}),
                        ft.Container(metric("ذمم الموردين", money(summary["payables"])), col={"xs": 6, "md": 3}),
                        ft.Container(metric("أرصدة دائنة للعملاء", money(summary["customer_credits"])), col={"xs": 6, "md": 3}),
                        ft.Container(metric("دفعات مقدمة للموردين", money(summary["supplier_advances"])), col={"xs": 6, "md": 3}),
                        ft.Container(metric("قيمة المخزون", money(summary["inventory_value"])), col={"xs": 6, "md": 3}),
                        ft.Container(metric("الصندوق", money(summary["cash"])), col={"xs": 6, "md": 3}),
                    ]
                ),
                ft.Container(
                    ft.Column(
                        [
                            ft.Text("Flet Offline", weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "المرحلة 7: مشاركة النسخ الاحتياطية، استيرادها، طباعة/PDF، وتكلفة الخدمات — مع بقاء المحاسبة أوفلاين.",
                                color="#64748B",
                            ),
                        ]
                    ),
                    padding=14,
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=12,
                    bgcolor="#FFFFFF",
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        page.update()

    def party_view(repo, title):
        name = ft.TextField(label="الاسم", expand=True)
        phone = ft.TextField(label="الهاتف")
        address = ft.TextField(label="العنوان")
        search = ft.TextField(label="بحث", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=8)

        def refresh(_=None):
            rows.controls = []
            for party in repo.list(search.value or ""):
                rows.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(party["name"], weight=ft.FontWeight.BOLD),
                                        ft.Text(party.get("phone") or "", size=12, color="#64748B"),
                                    ],
                                    expand=True,
                                    spacing=2,
                                ),
                                ft.Column(
                                    [ft.Text("الرصيد", size=11, color="#64748B"), ft.Text(money(party["balance"]), weight=ft.FontWeight.BOLD)],
                                    spacing=2,
                                ),
                            ]
                        ),
                        padding=10,
                        border=ft.border.all(1, "#E5E7EB"),
                        border_radius=10,
                        bgcolor="#FFFFFF",
                    )
                )
            page.update()

        search.on_change = refresh

        def add(_):
            try:
                repo.create(name.value or "", phone.value, address.value)
                name.value = phone.value = address.value = ""
                refresh()
            except Exception as exc:
                notify(str(exc))

        refresh()
        content.content = ft.Column(
            [
                ft.Text(title, size=24, weight=ft.FontWeight.BOLD),
                ft.ResponsiveRow(
                    [
                        ft.Container(name, col={"xs": 12, "md": 5}),
                        ft.Container(phone, col={"xs": 12, "md": 3}),
                        ft.Container(address, col={"xs": 12, "md": 4}),
                    ]
                ),
                ft.FilledButton("إضافة", icon=ft.Icons.ADD, on_click=add),
                ft.Divider(),
                search,
                rows,
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        page.update()

    def items_view():
        categories = ctx.definitions.list_categories()
        units = ctx.definitions.list_units()
        category_map = {int(c["id"]): c for c in categories}
        unit_map = {int(u["id"]): u for u in units}

        cat_name = ft.TextField(label="تصنيف جديد")
        unit_name = ft.TextField(label="وحدة جديدة")
        unit_abbr = ft.TextField(label="اختصار")

        name = ft.TextField(label="اسم المادة / الخدمة")
        purchase = ft.TextField(label="سعر الشراء / تكلفة الخدمة", value="0", keyboard_type=ft.KeyboardType.NUMBER)
        selling = ft.TextField(label="سعر البيع", value="0", keyboard_type=ft.KeyboardType.NUMBER)
        qty = ft.TextField(label="الرصيد الافتتاحي", value="0", keyboard_type=ft.KeyboardType.NUMBER)
        kind = ft.Dropdown(label="النوع", value="مخزون", options=[ft.dropdown.Option("مخزون"), ft.dropdown.Option("خدمة")])
        category = ft.Dropdown(
            label="التصنيف",
            options=[ft.dropdown.Option(str(c["id"]), c["name"]) for c in categories],
            enable_search=True,
        )
        base_unit = ft.Dropdown(
            label="الوحدة الأساسية",
            options=[ft.dropdown.Option(str(u["id"]), u["name"]) for u in units],
            enable_search=True,
        )
        alt_unit = ft.Dropdown(
            label="وحدة إضافية",
            options=[ft.dropdown.Option(str(u["id"]), u["name"]) for u in units],
            enable_search=True,
        )
        alt_factor = ft.TextField(label="معامل التحويل", value="1", keyboard_type=ft.KeyboardType.NUMBER)
        search = ft.TextField(label="بحث في المواد", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=8)

        def add_category(_):
            try:
                ctx.definitions.create_category(cat_name.value or "")
                items_view()
            except Exception as exc:
                notify(str(exc))

        def add_unit(_):
            try:
                ctx.definitions.create_unit(unit_name.value or "", unit_abbr.value)
                items_view()
            except Exception as exc:
                notify(str(exc))

        def refresh(_=None):
            rows.controls = []
            for item in ctx.items.list(search.value or ""):
                item_units = ctx.items.units(int(item["id"]))
                units_text = "، ".join(
                    f"{u['name']} × {money(u['conversion_factor'])}" for u in item_units
                ) or "بلا وحدة"
                rows.controls.append(
                    ft.Container(
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Column(
                                            [
                                                ft.Text(item["name"], weight=ft.FontWeight.BOLD),
                                                ft.Text(
                                                    f"{item['item_type']} • {item.get('category_name') or 'بلا تصنيف'}",
                                                    size=12,
                                                    color="#64748B",
                                                ),
                                            ],
                                            expand=True,
                                            spacing=2,
                                        ),
                                        ft.Column(
                                            [
                                                ft.Text(f"المخزون: {money(item['quantity'])}"),
                                                ft.Text(f"بيع: {money(item['selling_price'])}", size=12),
                                                ft.Text(("تكلفة الخدمة: " if item["item_type"] == "خدمة" else "متوسط التكلفة: ") + money(item["purchase_price"] if item["item_type"] == "خدمة" else item["average_cost"]), size=11, color="#64748B"),
                                            ],
                                            spacing=2,
                                        ),
                                    ]
                                ),
                                ft.Text(f"الوحدات: {units_text}", size=11, color="#64748B"),
                            ],
                            spacing=5,
                        ),
                        padding=10,
                        border=ft.border.all(1, "#E5E7EB"),
                        border_radius=10,
                        bgcolor="#FFFFFF",
                    )
                )
            page.update()

        search.on_change = refresh

        def add(_):
            try:
                alternate_units = []
                if alt_unit.value:
                    alternate_units.append(
                        {"unit_id": int(alt_unit.value), "conversion_factor": float(alt_factor.value or 1)}
                    )
                ctx.items.create(
                    name=name.value or "",
                    item_type=kind.value or "مخزون",
                    category_id=int(category.value) if category.value else None,
                    purchase_price=float(purchase.value or 0),
                    selling_price=float(selling.value or 0),
                    quantity=float(qty.value or 0),
                    base_unit_id=int(base_unit.value) if base_unit.value else None,
                    item_units=alternate_units,
                )
                notify("تمت إضافة المادة")
                items_view()
            except Exception as exc:
                notify(str(exc))

        refresh()
        content.content = ft.Column(
            [
                ft.Text("المواد والتعريفات", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(
                    ft.Column(
                        [
                            ft.Text("التعريفات", weight=ft.FontWeight.BOLD),
                            ft.ResponsiveRow(
                                [
                                    ft.Container(cat_name, col={"xs": 8, "md": 4}),
                                    ft.Container(ft.FilledButton("إضافة تصنيف", on_click=add_category), col={"xs": 4, "md": 2}),
                                    ft.Container(unit_name, col={"xs": 5, "md": 3}),
                                    ft.Container(unit_abbr, col={"xs": 3, "md": 1}),
                                    ft.Container(ft.OutlinedButton("إضافة وحدة", on_click=add_unit), col={"xs": 4, "md": 2}),
                                ]
                            ),
                        ]
                    ),
                    padding=10,
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=12,
                    bgcolor="#FFFFFF",
                ),
                ft.Text("إضافة مادة / خدمة", size=18, weight=ft.FontWeight.BOLD),
                ft.Text("عند اختيار خدمة، يُستخدم سعر الشراء كتكلفة معيارية وتُحفظ لقطة التكلفة داخل فاتورة البيع لأغراض الربحية.", size=11, color="#64748B"),
                ft.ResponsiveRow(
                    [
                        ft.Container(name, col={"xs": 12, "md": 4}),
                        ft.Container(kind, col={"xs": 6, "md": 2}),
                        ft.Container(category, col={"xs": 6, "md": 2}),
                        ft.Container(base_unit, col={"xs": 6, "md": 2}),
                        ft.Container(qty, col={"xs": 6, "md": 2}),
                        ft.Container(purchase, col={"xs": 6, "md": 2}),
                        ft.Container(selling, col={"xs": 6, "md": 2}),
                        ft.Container(alt_unit, col={"xs": 6, "md": 2}),
                        ft.Container(alt_factor, col={"xs": 6, "md": 2}),
                    ]
                ),
                ft.FilledButton("حفظ المادة", icon=ft.Icons.SAVE_OUTLINED, on_click=add),
                ft.Divider(),
                search,
                rows,
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        page.update()

    invoice_center = InvoiceCenter(page, ctx, content, native_files=native_files)
    finance_center = FinanceCenter(page, ctx, content, native_files=native_files)
    reports_center = ReportsCenter(page, ctx, content)
    admin_center = AdminCenter(page, ctx, content, on_logout=on_logout, native_files=native_files)
    session = ctx.auth.current()
    if session is None:
        raise RuntimeError("لا توجد جلسة مستخدم")
    available_pages = [
        ("dashboard", ft.Icons.HOME_OUTLINED, ft.Icons.HOME, "الرئيسية", show_dashboard),
        ("customers", ft.Icons.PEOPLE_OUTLINE, ft.Icons.PEOPLE, "العملاء", lambda: party_view(ctx.customers, "العملاء")),
        ("suppliers", ft.Icons.LOCAL_SHIPPING_OUTLINED, ft.Icons.LOCAL_SHIPPING, "الموردون", lambda: party_view(ctx.suppliers, "الموردون")),
        ("items", ft.Icons.INVENTORY_2_OUTLINED, ft.Icons.INVENTORY_2, "المواد", items_view),
        ("invoices", ft.Icons.RECEIPT_LONG_OUTLINED, ft.Icons.RECEIPT_LONG, "الفواتير", invoice_center.show_center),
        ("finance", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, ft.Icons.ACCOUNT_BALANCE_WALLET, "المالية", finance_center.show_center),
        ("reports", ft.Icons.QUERY_STATS_OUTLINED, ft.Icons.QUERY_STATS, "التقارير", reports_center.show_center),
        ("admin", ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED, ft.Icons.ADMIN_PANEL_SETTINGS, "الإدارة", admin_center.show_center),
    ]
    allowed_pages = [entry for entry in available_pages if session.can(entry[0])]

    # Desktop keeps the complete navigation rail. On phones, limit the bottom
    # navigation to the most frequent actions and group master-data/admin
    # screens under "المزيد" so labels and touch targets remain usable.
    desktop_destinations = [(entry[1], entry[2], entry[3]) for entry in allowed_pages]

    def rail_changed(e):
        index = max(0, min(int(e.control.selected_index), len(allowed_pages) - 1))
        allowed_pages[index][4]()

    primary_keys = {"dashboard", "invoices", "finance", "reports"}
    mobile_primary = [entry for entry in allowed_pages if entry[0] in primary_keys]
    mobile_secondary = [entry for entry in allowed_pages if entry[0] not in primary_keys]

    def show_more():
        cards = []
        for entry in mobile_secondary:
            action = entry[4]
            cards.append(
                ft.Container(
                    ft.OutlinedButton(
                        entry[3],
                        icon=entry[1],
                        on_click=lambda _, fn=action: fn(),
                        width=220,
                    ),
                    col={"xs": 6, "sm": 4},
                )
            )
        content.content = ft.Column(
            [
                ft.Text("المزيد", size=24, weight=ft.FontWeight.BOLD),
                ft.Text("العملاء والموردون والمواد والإدارة حسب صلاحيات المستخدم.", size=12, color="#64748B"),
                ft.ResponsiveRow(cards) if cards else ft.Text("لا توجد أقسام إضافية لهذا المستخدم.", color="#64748B"),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        page.update()

    mobile_actions = [entry[4] for entry in mobile_primary]
    mobile_destinations = [(entry[1], entry[2], entry[3]) for entry in mobile_primary]
    if mobile_secondary:
        mobile_actions.append(show_more)
        mobile_destinations.append((ft.Icons.MORE_HORIZ, ft.Icons.MORE_HORIZ, "المزيد"))

    def nav_changed(e):
        index = max(0, min(int(e.control.selected_index), len(mobile_actions) - 1))
        mobile_actions[index]()

    nav = ft.NavigationBar(
        selected_index=0,
        on_change=nav_changed,
        destinations=[
            ft.NavigationBarDestination(icon=icon, selected_icon=selected, label=label)
            for icon, selected, label in mobile_destinations
        ],
    )
    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        on_change=rail_changed,
        destinations=[
            ft.NavigationRailDestination(icon=icon, selected_icon=selected, label=label)
            for icon, selected, label in desktop_destinations
        ],
    )

    page.navigation_bar = nav
    root = ft.Row([rail, ft.VerticalDivider(width=1), content], expand=True, spacing=0)
    page.add(root)

    def adapt_navigation(_=None):
        desktop = bool(page.width and page.width >= 900)
        rail.visible = desktop
        nav.visible = not desktop
        page.update()

    page.on_resize = adapt_navigation
    show_dashboard()
    adapt_navigation()



def main(page: ft.Page):
    migrate_legacy_database(LEGACY_APP_DB, APP_DB)
    ctx = AppContext.create(APP_DB)
    native_files = NativeFiles()
    page.overlay.append(native_files)
    page.title = "قيد - أوفلاين"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = "#F8FAFC"

    def reset_page():
        page.controls.clear()
        page.navigation_bar = None
        page.update()

    def open_shell():
        reset_page()
        build_shell(page, ctx, on_logout=logout, native_files=native_files)

    def logout():
        ctx.auth.logout()
        show_auth()

    def notify(text: str):
        page.open(ft.SnackBar(ft.Text(text)))

    def show_activation():
        reset_page()
        ActivationGate(page, ctx, on_success=show_auth).show()

    def show_auth():
        reset_page()
        first_run = not ctx.auth.has_users()
        username = ft.TextField(label="اسم المستخدم", autofocus=True)
        full_name = ft.TextField(label="الاسم الكامل") if first_run else None
        password = ft.TextField(label="كلمة المرور", password=True, can_reveal_password=True, on_submit=lambda _: submit(None))
        confirm = ft.TextField(label="تأكيد كلمة المرور", password=True, can_reveal_password=True) if first_run else None

        def submit(_):
            try:
                if first_run:
                    if (password.value or "") != (confirm.value or ""):
                        raise ValueError("تأكيد كلمة المرور غير مطابق")
                    ctx.auth.create_initial_admin(username.value or "", full_name.value or "", password.value or "")
                ctx.auth.login(username.value or "", password.value or "")
                open_shell()
            except Exception as exc:
                notify(str(exc))

        controls = [
            ft.Icon(ft.Icons.ACCOUNT_BALANCE, size=48, color="#0F4C81"),
            ft.Text("قيد - أوفلاين", size=26, weight=ft.FontWeight.BOLD),
            ft.Text(
                "إنشاء المدير الأول" if first_run else "تسجيل الدخول المحلي",
                color="#64748B",
            ),
            username,
        ]
        if full_name is not None:
            controls.append(full_name)
        controls.append(password)
        if confirm is not None:
            controls.append(confirm)
        controls.extend(
            [
                ft.FilledButton(
                    "إنشاء المدير والدخول" if first_run else "دخول",
                    icon=ft.Icons.LOGIN,
                    on_click=submit,
                    width=320,
                ),
                ft.Text(
                    "كل المستخدمين والبيانات محليون على هذا الجهاز. لا يعتمد التشغيل المحاسبي على خدمات خارجية أو قاعدة بيانات أونلاين.",
                    size=11,
                    color="#64748B",
                    text_align=ft.TextAlign.CENTER,
                ),
            ]
        )
        card = ft.Container(
            ft.Column(controls, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            width=390,
            padding=24,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=16,
            bgcolor="#FFFFFF",
        )
        page.add(
            ft.Container(
                ft.Column([card], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True,
                padding=16,
            )
        )
        page.update()

    if ctx.license.status().valid:
        show_auth()
    else:
        show_activation()


ft.app(target=main)
