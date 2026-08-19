from __future__ import annotations

from pathlib import Path

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.components import PatternPad, SearchSelect
from nano_offline.core.paths import database_path, migrate_legacy_database
from nano_offline.views.activation_view import ActivationGate
from nano_offline.views.admin_view import AdminCenter
from nano_offline.views.finance_view import FinanceCenter
from nano_offline.views.invoice_view import InvoiceCenter
from nano_offline.views.reports_view import ReportsCenter

APP_DB = database_path()
LEGACY_APP_DB = next((p for p in [Path(__file__).resolve().parent.parent / "data" / "nano.db", Path(__file__).resolve().parent.parent / "data" / "qeid.db"] if p.exists()), Path(__file__).resolve().parent.parent / "data" / "nano.db")


def build_shell(page: ft.Page, ctx: AppContext, *, on_logout, native_files: NativeFiles):
    page.title = "Nano | نانو"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed="#0B63F6")
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
                            ft.Text("Nano", weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "منصة أعمال حديثة للمحاسبة والمخزون والفواتير، بهوية Nano الجديدة وتشغيل محلي كامل.",
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
        kind = SearchSelect(
            label="النوع",
            choices=[("مخزون", "مخزون"), ("خدمة", "خدمة")],
            value="مخزون",
            allow_clear=False,
        )
        category = SearchSelect(
            label="التصنيف",
            choices=[(str(c["id"]), c["name"]) for c in categories],
        )
        base_unit = SearchSelect(
            label="الوحدة الأساسية",
            choices=[(str(u["id"]), u["name"]) for u in units],
        )
        alt_unit = SearchSelect(
            label="وحدة إضافية",
            choices=[(str(u["id"]), u["name"]) for u in units],
        )
        alt_factor = ft.TextField(label="معامل التحويل", value="1", keyboard_type=ft.KeyboardType.NUMBER)
        search = ft.TextField(label="بحث في المواد", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=8)

        definitions_dialog = ft.AlertDialog(modal=True)

        def close_definitions(_=None):
            page.close(definitions_dialog)

        def add_category(_):
            try:
                ctx.definitions.create_category(cat_name.value or "")
                close_definitions()
                notify("تمت إضافة التصنيف")
                items_view()
            except Exception as exc:
                notify(str(exc))

        def add_unit(_):
            try:
                ctx.definitions.create_unit(unit_name.value or "", unit_abbr.value)
                close_definitions()
                notify("تمت إضافة الوحدة")
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

        definitions_dialog.title = ft.Text("التصنيفات والوحدات")
        definitions_dialog.content = ft.Container(
            ft.Column(
                [
                    ft.Text("التصنيفات", weight=ft.FontWeight.BOLD),
                    cat_name,
                    ft.FilledButton("إضافة تصنيف", icon=ft.Icons.ADD, on_click=add_category),
                    ft.Divider(),
                    ft.Text("الوحدات", weight=ft.FontWeight.BOLD),
                    ft.ResponsiveRow(
                        [
                            ft.Container(unit_name, col={"xs": 8}),
                            ft.Container(unit_abbr, col={"xs": 4}),
                        ]
                    ),
                    ft.OutlinedButton("إضافة وحدة", icon=ft.Icons.ADD, on_click=add_unit),
                ],
                tight=True,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=460,
        )
        definitions_dialog.actions = [ft.TextButton("إغلاق", on_click=close_definitions)]

        form_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("مادة / خدمة جديدة", size=18, weight=ft.FontWeight.BOLD, expand=True),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="إغلاق", on_click=lambda _: hide_form()),
                        ]
                    ),
                    ft.Text(
                        "عند اختيار خدمة، يستخدم سعر الشراء كتكلفة معيارية لأغراض الربحية.",
                        size=11,
                        color="#64748B",
                    ),
                    name,
                    ft.ResponsiveRow(
                        [
                            ft.Container(kind, col={"xs": 6, "md": 3}),
                            ft.Container(category, col={"xs": 6, "md": 3}),
                            ft.Container(base_unit, col={"xs": 6, "md": 3}),
                            ft.Container(qty, col={"xs": 6, "md": 3}),
                            ft.Container(purchase, col={"xs": 6, "md": 3}),
                            ft.Container(selling, col={"xs": 6, "md": 3}),
                            ft.Container(alt_unit, col={"xs": 6, "md": 3}),
                            ft.Container(alt_factor, col={"xs": 6, "md": 3}),
                        ],
                        spacing=8,
                        run_spacing=8,
                    ),
                    ft.FilledButton("حفظ المادة", icon=ft.Icons.SAVE_OUTLINED, on_click=add),
                ],
                spacing=10,
            ),
            padding=12,
            border=ft.border.all(1, "#BFDBFE"),
            border_radius=14,
            bgcolor="#F8FBFF",
            visible=False,
        )

        def show_form(_=None):
            form_panel.visible = True
            page.update()

        def hide_form(_=None):
            form_panel.visible = False
            page.update()

        def show_definitions(_=None):
            page.open(definitions_dialog)

        refresh()
        content.content = ft.Column(
            [
                ft.Text("المواد", size=24, weight=ft.FontWeight.BOLD),
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            ft.FilledButton("مادة جديدة", icon=ft.Icons.ADD, on_click=show_form),
                            col={"xs": 6, "md": 3},
                        ),
                        ft.Container(
                            ft.OutlinedButton("التصنيفات والوحدات", icon=ft.Icons.SETTINGS_OUTLINED, on_click=show_definitions),
                            col={"xs": 6, "md": 3},
                        ),
                    ],
                    spacing=8,
                    run_spacing=8,
                ),
                form_panel,
                search,
                rows,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        page.update()

    def show_security():
        session = ctx.auth.current()
        if session is None:
            raise RuntimeError("لا توجد جلسة مستخدم")
        quick_kind = ctx.auth.quick_auth_info(session.username)
        quick_label = {"pin": "PIN", "pattern": "نمط"}.get(quick_kind, "غير مفعّل")
        quick_status = ft.Text(f"الدخول السريع الحالي: {quick_label}", color="#475569")
        saved_status = ft.Text(
            "الدخول التلقائي مفعّل على هذا الجهاز" if ctx.auth.saved_login_enabled(session.username) else "الدخول التلقائي غير مفعّل",
            color="#475569",
        )

        def refresh_security():
            kind = ctx.auth.quick_auth_info(session.username)
            quick_status.value = "الدخول السريع الحالي: " + {"pin": "PIN", "pattern": "نمط"}.get(kind, "غير مفعّل")
            saved_status.value = "الدخول التلقائي مفعّل على هذا الجهاز" if ctx.auth.saved_login_enabled(session.username) else "الدخول التلقائي غير مفعّل"
            page.update()

        def pin_dialog(_=None):
            current_password = ft.TextField(label="كلمة المرور الحالية", password=True, can_reveal_password=True)
            pin = ft.TextField(label="PIN جديد (4–8 أرقام)", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER)
            confirm = ft.TextField(label="تأكيد PIN", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER)
            dialog = ft.AlertDialog(modal=True, title=ft.Text("إعداد الدخول بـ PIN"))

            def close(_=None):
                page.close(dialog)

            def save(_=None):
                try:
                    if (pin.value or "") != (confirm.value or ""):
                        raise ValueError("تأكيد PIN غير مطابق")
                    ctx.auth.set_quick_auth("pin", pin.value or "", current_password.value or "")
                    page.close(dialog)
                    notify("تم تفعيل الدخول بـ PIN")
                    refresh_security()
                except Exception as exc:
                    notify(str(exc))

            dialog.content = ft.Column([current_password, pin, confirm], tight=True, spacing=10)
            dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حفظ PIN", on_click=save)]
            page.open(dialog)

        def pattern_dialog(_=None):
            current_password = ft.TextField(label="كلمة المرور الحالية", password=True, can_reveal_password=True)
            first = PatternPad()
            second = PatternPad()
            dialog = ft.AlertDialog(modal=True, title=ft.Text("إعداد نمط الدخول"))

            def close(_=None):
                page.close(dialog)

            def save(_=None):
                try:
                    if first.value != second.value:
                        raise ValueError("تأكيد النمط غير مطابق")
                    ctx.auth.set_quick_auth("pattern", first.value, current_password.value or "")
                    page.close(dialog)
                    notify("تم تفعيل الدخول بالنمط")
                    refresh_security()
                except Exception as exc:
                    notify(str(exc))

            dialog.content = ft.Container(
                ft.Column(
                    [
                        current_password,
                        ft.Text("النمط الجديد: اختر 4 نقاط مختلفة على الأقل", weight=ft.FontWeight.BOLD),
                        first,
                        ft.Divider(),
                        ft.Text("تأكيد النمط", weight=ft.FontWeight.BOLD),
                        second,
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    spacing=10,
                ),
                width=420,
                height=560,
            )
            dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حفظ النمط", on_click=save)]
            page.open(dialog)

        def clear_dialog(_=None):
            current_password = ft.TextField(label="كلمة المرور الحالية", password=True, can_reveal_password=True)
            dialog = ft.AlertDialog(modal=True, title=ft.Text("إلغاء الدخول السريع"), content=current_password)

            def close(_=None):
                page.close(dialog)

            def clear(_=None):
                try:
                    ctx.auth.clear_quick_auth(current_password.value or "")
                    page.close(dialog)
                    notify("تم إلغاء PIN / النمط")
                    refresh_security()
                except Exception as exc:
                    notify(str(exc))

            dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("إلغاء الدخول السريع", on_click=clear)]
            page.open(dialog)

        content.content = ft.Column(
            [
                ft.Text("الأمان والدخول", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(
                    ft.Column(
                        [
                            ft.Text(f"المستخدم: {session.full_name} ({session.username})", weight=ft.FontWeight.BOLD),
                            quick_status,
                            saved_status,
                            ft.Text(
                                "لا يتم حفظ كلمة المرور كنص. خيار البقاء مسجلاً يستخدم رمز جلسة عشوائيًا محليًا، بينما PIN والنمط يحفظان كبصمة مشفرة مرتبطة بهذا الجهاز.",
                                size=11,
                                color="#64748B",
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=14,
                    border=ft.border.all(1, "#E2E8F0"),
                    border_radius=14,
                    bgcolor="#FFFFFF",
                ),
                ft.ResponsiveRow(
                    [
                        ft.Container(ft.FilledButton("إعداد PIN", icon=ft.Icons.LOCK, on_click=pin_dialog), col={"xs": 6, "md": 3}),
                        ft.Container(ft.OutlinedButton("إعداد نمط", icon=ft.Icons.APPS_ROUNDED, on_click=pattern_dialog), col={"xs": 6, "md": 3}),
                        ft.Container(ft.TextButton("إلغاء PIN / النمط", icon=ft.Icons.REFRESH, on_click=clear_dialog), col={"xs": 12, "md": 3}),
                    ],
                    spacing=8,
                    run_spacing=8,
                ),
            ],
            spacing=12,
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
        ("items", ft.Icons.INVENTORY_2_OUTLINED, ft.Icons.INVENTORY_2, "المواد", items_view),
        ("customers", ft.Icons.PEOPLE_OUTLINE, ft.Icons.PEOPLE, "العملاء", lambda: party_view(ctx.customers, "العملاء")),
        ("suppliers", ft.Icons.LOCAL_SHIPPING_OUTLINED, ft.Icons.LOCAL_SHIPPING, "الموردون", lambda: party_view(ctx.suppliers, "الموردون")),
        ("invoices", ft.Icons.RECEIPT_LONG_OUTLINED, ft.Icons.RECEIPT_LONG, "الفواتير", invoice_center.show_center),
        ("finance", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, ft.Icons.ACCOUNT_BALANCE_WALLET, "المالية", finance_center.show_center),
        ("reports", ft.Icons.QUERY_STATS_OUTLINED, ft.Icons.QUERY_STATS, "التقارير", reports_center.show_center),
        ("security", ft.Icons.LOCK_OUTLINE, ft.Icons.LOCK, "الأمان", show_security),
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

    primary_keys = {"dashboard", "items", "invoices", "finance"}
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
                ft.Text("العملاء والموردون والتقارير والأمان والإدارة حسب صلاحيات المستخدم.", size=12, color="#64748B"),
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
    # Keep page content below Android/iOS status bars while the bottom NavigationBar
    # continues to use the platform-safe inset managed by Flet.
    page.add(ft.SafeArea(root, expand=True))

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
    page.title = "Nano | نانو"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed="#0B63F6")
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
        remembered = ctx.auth.remembered_username() if not first_run else ""
        username = ft.TextField(label="اسم المستخدم", value=remembered, autofocus=not bool(remembered))
        full_name = ft.TextField(label="الاسم الكامل") if first_run else None
        password = ft.TextField(label="كلمة المرور", password=True, can_reveal_password=True, on_submit=lambda _: submit(None))
        confirm = ft.TextField(label="تأكيد كلمة المرور", password=True, can_reveal_password=True) if first_run else None
        remember_name = ft.Checkbox(label="تذكر اسم المستخدم", value=bool(remembered) or first_run)
        stay_signed = ft.Checkbox(
            label="البقاء مسجلاً على هذا الجهاز",
            value=False,
            tooltip="يحفظ رمز جلسة محليًا بدل حفظ كلمة المرور نفسها",
        )
        quick_button = ft.OutlinedButton("الدخول السريع", icon=ft.Icons.LOCK_OPEN, visible=False, width=320)
        security_note = ft.Text(
            "يمكن تفعيل PIN أو نمط من قسم الأمان بعد تسجيل الدخول. كلمة المرور لا تُحفظ كنص صريح.",
            size=11,
            color="#64748B",
            text_align=ft.TextAlign.CENTER,
        )

        def refresh_quick(_=None):
            if first_run:
                quick_button.visible = False
            else:
                kind = ctx.auth.quick_auth_info(username.value or "")
                quick_button.visible = kind in {"pin", "pattern"}
                quick_button.text = "الدخول بـ PIN" if kind == "pin" else "الدخول بالنمط" if kind == "pattern" else "الدخول السريع"
            page.update()

        def submit(_):
            try:
                if first_run:
                    if (password.value or "") != (confirm.value or ""):
                        raise ValueError("تأكيد كلمة المرور غير مطابق")
                    ctx.auth.create_initial_admin(username.value or "", full_name.value or "", password.value or "")
                ctx.auth.login(
                    username.value or "",
                    password.value or "",
                    remember_login=bool(stay_signed.value),
                    remember_username=bool(remember_name.value),
                )
                open_shell()
            except Exception as exc:
                notify(str(exc))

        def quick_login(_=None):
            kind = ctx.auth.quick_auth_info(username.value or "")
            if not kind:
                notify("لا يوجد PIN أو نمط مفعّل لهذا المستخدم")
                return
            dialog = ft.AlertDialog(modal=True, title=ft.Text("الدخول السريع"))

            def close(_=None):
                page.close(dialog)

            if kind == "pin":
                secret = ft.TextField(
                    label="PIN",
                    password=True,
                    can_reveal_password=True,
                    keyboard_type=ft.KeyboardType.NUMBER,
                    autofocus=True,
                )

                def do_login(_=None):
                    try:
                        ctx.auth.login_quick(username.value or "", "pin", secret.value or "")
                        page.close(dialog)
                        open_shell()
                    except Exception as exc:
                        notify(str(exc))

                secret.on_submit = do_login
                dialog.content = secret
                dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("دخول", on_click=do_login)]
            else:
                pad = PatternPad()

                def do_login(_=None):
                    try:
                        ctx.auth.login_quick(username.value or "", "pattern", pad.value)
                        page.close(dialog)
                        open_shell()
                    except Exception as exc:
                        notify(str(exc))

                dialog.content = ft.Container(
                    ft.Column([ft.Text("أدخل النمط المسجل"), pad], tight=True, spacing=8),
                    width=380,
                )
                dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("دخول", on_click=do_login)]
            page.open(dialog)

        username.on_change = refresh_quick
        quick_button.on_click = quick_login

        controls = [
            ft.Image(src="icon.png", width=84, height=84, fit=ft.ImageFit.CONTAIN),
            ft.Text("Nano | نانو", size=26, weight=ft.FontWeight.BOLD, color="#0A2E78"),
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
        if not first_run:
            controls.extend([remember_name, stay_signed])
        controls.extend(
            [
                ft.FilledButton(
                    "إنشاء المدير والدخول" if first_run else "دخول بكلمة المرور",
                    icon=ft.Icons.LOGIN,
                    on_click=submit,
                    width=320,
                ),
                quick_button,
                security_note,
                ft.Text(
                    "كل المستخدمين والبيانات محليون على هذا الجهاز. لا يعتمد التشغيل المحاسبي على خدمات خارجية أو قاعدة بيانات أونلاين.",
                    size=11,
                    color="#64748B",
                    text_align=ft.TextAlign.CENTER,
                ),
            ]
        )
        card = ft.Container(
            ft.Column(controls, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, scroll=ft.ScrollMode.AUTO),
            width=390,
            padding=24,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=16,
            bgcolor="#FFFFFF",
        )
        page.add(
            ft.SafeArea(
                ft.Container(
                    ft.Column([card], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    expand=True,
                    padding=16,
                ),
                expand=True,
            )
        )
        refresh_quick()

    if ctx.license.status().valid:
        if ctx.auth.has_users() and ctx.auth.restore_saved_session() is not None:
            open_shell()
        else:
            show_auth()
    else:
        show_activation()


ft.app(target=main)
