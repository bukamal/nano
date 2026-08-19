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

    content = ft.Container(expand=True, padding=ft.padding.only(left=18, right=18, top=14, bottom=18))

    header_title = ft.Text("لوحة التحكم", size=22, weight=ft.FontWeight.BOLD, color="#0F172A")
    header_subtitle = ft.Text("نظرة عامة على أداء عملك", size=12, color="#64748B")

    def set_header(title: str, subtitle: str = "") -> None:
        header_title.value = title
        header_subtitle.value = subtitle

    top_bar = ft.Container(
        ft.Row(
            [
                ft.Column([header_title, header_subtitle], spacing=1, expand=True),
                ft.Container(
                    ft.Icon(ft.Icons.NOTIFICATIONS_NONE_ROUNDED, color="#64748B", size=22),
                    width=42,
                    height=42,
                    alignment=ft.alignment.center,
                    border=ft.border.all(1, "#E2E8F0"),
                    border_radius=14,
                    bgcolor="#FFFFFF",
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=18, vertical=12),
        bgcolor="#FFFFFF",
        border=ft.border.only(bottom=ft.BorderSide(1, "#E2E8F0")),
    )

    def money(value):
        return f"{float(value or 0):,.2f}"

    def notify(text: str):
        page.open(ft.SnackBar(ft.Text(text)))

    def metric(title: str, value: str, *, icon, accent: str, note: str = ""):
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                ft.Icon(icon, size=20, color=accent),
                                width=40, height=40, alignment=ft.alignment.center,
                                bgcolor={"#16A34A": "#ECFDF5", "#0B63F6": "#EFF6FF", "#F59E0B": "#FFFBEB", "#EF4444": "#FEF2F2"}.get(accent, "#EFF6FF"), border_radius=13,
                            ),
                            ft.Text(title, size=12, color="#64748B", weight=ft.FontWeight.W_600, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color="#0F172A"),
                    ft.Text(note, size=10, color="#94A3B8") if note else ft.Container(height=2),
                ],
                spacing=7,
            ),
            padding=16,
            border=ft.border.all(1, "#E2E8F0"),
            border_radius=20,
            bgcolor="#FFFFFF",
            shadow=ft.BoxShadow(blur_radius=18, spread_radius=0, color="#E2E8F0", offset=ft.Offset(0, 5)),
        )

    def dashboard_action(label: str, icon, on_click, *, primary: bool = False):
        return ft.Container(
            ft.Column(
                [
                    ft.Container(
                        ft.Icon(icon, color="#FFFFFF" if primary else "#0B63F6", size=24),
                        width=48, height=48, alignment=ft.alignment.center,
                        bgcolor="#0B63F6" if primary else "#EFF6FF",
                        border_radius=16,
                    ),
                    ft.Text(label, size=12, weight=ft.FontWeight.W_600, color="#0F172A", text_align=ft.TextAlign.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=7,
            ),
            padding=10,
            border_radius=18,
            on_click=on_click,
            ink=True,
        )

    def show_dashboard():
        set_header("لوحة التحكم", "نظرة عامة على أداء عملك")
        summary = ctx.dashboard.summary()
        invoices = ctx.invoices.list_invoices(limit=100)
        recent = invoices[:5]
        open_invoices = [i for i in invoices if i.get("payment_status") != "paid"]
        low_stock = [
            i for i in ctx.items.list()
            if i.get("item_type") == "مخزون" and float(i.get("quantity") or 0) <= 5
        ]

        sales = max(0.0, float(summary["sales"]))
        purchases = max(0.0, float(summary["purchases"]))
        max_flow = max(sales, purchases, 1.0)

        def flow_row(label: str, value: float, color: str):
            ratio = max(0.04, min(1.0, value / max_flow)) if value else 0.02
            return ft.Column(
                [
                    ft.Row([ft.Text(label, size=12, color="#475569", expand=True), ft.Text(money(value), size=12, weight=ft.FontWeight.BOLD)]),
                    ft.Stack(
                        [
                            ft.Container(height=8, bgcolor="#F1F5F9", border_radius=10),
                            ft.Container(height=8, width=max(8, 260 * ratio), bgcolor=color, border_radius=10),
                        ]
                    ),
                ],
                spacing=5,
            )

        recent_cards: list[ft.Control] = []
        for inv in recent:
            sale = inv.get("type") == "sale"
            remaining = max(0.0, float(inv.get("remaining_amount") or 0))
            recent_cards.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Container(
                                ft.Icon(ft.Icons.TRENDING_UP if sale else ft.Icons.TRENDING_DOWN, size=18, color="#16A34A" if sale else "#7C3AED"),
                                width=38, height=38, alignment=ft.alignment.center,
                                bgcolor="#ECFDF5" if sale else "#F5F3FF", border_radius=12,
                            ),
                            ft.Column(
                                [
                                    ft.Text(f"فاتورة {'بيع' if sale else 'شراء'} #{inv['id']}", size=13, weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{inv.get('party_name') or 'نقدي'} • {inv.get('invoice_date') or '—'}", size=10, color="#64748B"),
                                ], spacing=2, expand=True,
                            ),
                            ft.Column(
                                [
                                    ft.Text(money(inv.get("total")), size=13, weight=ft.FontWeight.BOLD),
                                    ft.Text("مسددة" if remaining <= 1e-9 else f"متبقي {money(remaining)}", size=9, color="#16A34A" if remaining <= 1e-9 else "#EA580C"),
                                ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=10,
                    border_radius=14,
                    bgcolor="#F8FAFC",
                )
            )
        if not recent_cards:
            recent_cards.append(ft.Container(ft.Text("لا توجد فواتير بعد", color="#64748B", size=12), padding=12))

        alerts = ft.Column(spacing=8)
        if open_invoices:
            alerts.controls.append(
                ft.Container(
                    ft.Row([ft.Icon(ft.Icons.RECEIPT_LONG, color="#EA580C"), ft.Text(f"{len(open_invoices)} فاتورة غير مسددة أو جزئية", expand=True, size=12), ft.Icon(ft.Icons.CHEVRON_LEFT, color="#94A3B8")]),
                    padding=12, bgcolor="#FFF7ED", border_radius=14, on_click=lambda _: navigate("invoices"), ink=True,
                )
            )
        if low_stock:
            alerts.controls.append(
                ft.Container(
                    ft.Row([ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color="#B91C1C"), ft.Text(f"{len(low_stock)} مادة منخفضة المخزون (≤ 5)", expand=True, size=12), ft.Icon(ft.Icons.CHEVRON_LEFT, color="#94A3B8")]),
                    padding=12, bgcolor="#FEF2F2", border_radius=14, on_click=lambda _: navigate("items"), ink=True,
                )
            )
        if not alerts.controls:
            alerts.controls.append(ft.Container(ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color="#16A34A"), ft.Text("لا توجد تنبيهات مهمة حاليًا", size=12)]), padding=12, bgcolor="#ECFDF5", border_radius=14))

        content.content = ft.Column(
            [
                ft.ResponsiveRow(
                    [
                        ft.Container(metric("صافي الربح", money(summary["net_profit"]), icon=ft.Icons.QUERY_STATS, accent="#16A34A", note="بعد تكلفة المبيعات والمصروفات"), col={"xs": 6, "md": 3}),
                        ft.Container(metric("رصيد الصندوق", money(summary["cash"]), icon=ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, accent="#0B63F6", note="الرصيد النقدي الحالي"), col={"xs": 6, "md": 3}),
                        ft.Container(metric("ذمم العملاء", money(summary["receivables"]), icon=ft.Icons.PEOPLE_OUTLINE, accent="#F59E0B", note="مبالغ مستحقة التحصيل"), col={"xs": 6, "md": 3}),
                        ft.Container(metric("ذمم الموردين", money(summary["payables"]), icon=ft.Icons.LOCAL_SHIPPING_OUTLINED, accent="#EF4444", note="مبالغ مستحقة الدفع"), col={"xs": 6, "md": 3}),
                    ], spacing=10, run_spacing=10,
                ),
                ft.Container(
                    ft.Column(
                        [
                            ft.Row([ft.Text("إجراءات سريعة", size=16, weight=ft.FontWeight.BOLD, expand=True), ft.Text("الأكثر استخدامًا", size=10, color="#94A3B8")]),
                            ft.Row(
                                [
                                    dashboard_action("بيع", ft.Icons.SHOPPING_CART_CHECKOUT, lambda _: open_sale(), primary=True),
                                    dashboard_action("شراء", ft.Icons.ADD_SHOPPING_CART, lambda _: open_purchase()),
                                    dashboard_action("الفواتير", ft.Icons.RECEIPT_LONG_OUTLINED, lambda _: navigate("invoices")),
                                    dashboard_action("المواد", ft.Icons.INVENTORY_2_OUTLINED, lambda _: navigate("items")),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_AROUND,
                            ),
                        ], spacing=12,
                    ),
                    padding=15, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=20,
                ),
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            ft.Container(
                                ft.Column(
                                    [
                                        ft.Text("المبيعات والمشتريات", size=16, weight=ft.FontWeight.BOLD),
                                        flow_row("المبيعات", sales, "#0B63F6"),
                                        flow_row("المشتريات", purchases, "#8B5CF6"),
                                        ft.Row([ft.Text("قيمة المخزون", size=11, color="#64748B", expand=True), ft.Text(money(summary["inventory_value"]), weight=ft.FontWeight.BOLD, size=12)]),
                                    ], spacing=13,
                                ),
                                padding=16, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=20,
                            ),
                            col={"xs": 12, "md": 6},
                        ),
                        ft.Container(
                            ft.Container(
                                ft.Column([ft.Text("تنبيهات", size=16, weight=ft.FontWeight.BOLD), alerts], spacing=10),
                                padding=16, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=20,
                            ),
                            col={"xs": 12, "md": 6},
                        ),
                    ], spacing=10, run_spacing=10,
                ),
                ft.Container(
                    ft.Column([ft.Row([ft.Text("آخر الفواتير", size=16, weight=ft.FontWeight.BOLD, expand=True), ft.TextButton("عرض الكل", on_click=lambda _: navigate("invoices"))]), *recent_cards], spacing=8),
                    padding=14, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=20,
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
        )
        page.update()

    def party_view(repo, title):
        is_customer = repo.table == "customers"
        singular = "العميل" if is_customer else "المورد"
        set_header(title, f"إدارة بيانات {title} والحسابات المرتبطة")
        search = ft.TextField(
            label=f"بحث في {title}",
            hint_text=f"الاسم أو الهاتف",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
        )
        rows = ft.Column(spacing=9)
        summary_row = ft.ResponsiveRow(spacing=8, run_spacing=8)

        def small_metric(label: str, value: str, icon, accent: str):
            return ft.Container(
                ft.Row(
                    [
                        ft.Container(ft.Icon(icon, size=19, color=accent), width=38, height=38, alignment=ft.alignment.center, bgcolor="#F8FAFC", border_radius=12),
                        ft.Column([ft.Text(label, size=10, color="#64748B"), ft.Text(value, size=17, weight=ft.FontWeight.BOLD)], spacing=1, expand=True),
                    ]
                ),
                padding=11,
                bgcolor="#FFFFFF",
                border=ft.border.all(1, "#E2E8F0"),
                border_radius=16,
            )

        def open_editor(party: dict | None = None):
            name = ft.TextField(label="الاسم", value=(party or {}).get("name", ""), autofocus=True)
            phone = ft.TextField(label="الهاتف", value=(party or {}).get("phone") or "", keyboard_type=ft.KeyboardType.PHONE)
            address = ft.TextField(label="العنوان", value=(party or {}).get("address") or "", multiline=True, min_lines=1, max_lines=3)
            dialog = ft.AlertDialog(modal=True)

            def close(_=None):
                page.close(dialog)

            def save(_=None):
                try:
                    if party:
                        repo.update(int(party["id"]), name.value or "", phone.value, address.value)
                        message = f"تم تحديث {singular}"
                    else:
                        repo.create(name.value or "", phone.value, address.value)
                        message = f"تمت إضافة {singular}"
                    close()
                    notify(message)
                    refresh()
                except Exception as exc:
                    notify(str(exc))

            dialog.title = ft.Text(f"{'تعديل' if party else 'إضافة'} {singular}")
            dialog.content = ft.Container(ft.Column([name, phone, address], spacing=10, tight=True), width=480)
            dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حفظ", icon=ft.Icons.SAVE_OUTLINED, on_click=save)]
            page.open(dialog)

        def confirm_delete(party: dict, parent_dialog=None):
            confirm = ft.AlertDialog(modal=True)

            def close(_=None):
                page.close(confirm)

            def remove(_=None):
                try:
                    repo.delete(int(party["id"]))
                    close()
                    if parent_dialog:
                        try:
                            page.close(parent_dialog)
                        except Exception:
                            pass
                    notify(f"تم حذف {singular}")
                    refresh()
                except Exception as exc:
                    close()
                    notify(str(exc))

            confirm.title = ft.Text(f"حذف {singular}")
            confirm.content = ft.Text(f"هل تريد حذف «{party['name']}»؟ لن يسمح بالحذف إذا كانت هناك حركات مالية مرتبطة.")
            confirm.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حذف", icon=ft.Icons.DELETE_FOREVER, on_click=remove)]
            page.open(confirm)

        def show_detail(party: dict):
            try:
                data = repo.activity_summary(int(party["id"]))
            except Exception as exc:
                notify(str(exc))
                return
            dialog = ft.AlertDialog(modal=True)
            balance = float(data.get("balance") or 0)
            recent = []
            for inv in data.get("recent_invoices") or []:
                remaining = float(inv.get("remaining_amount") or 0)
                recent.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(f"فاتورة #{inv['id']}", size=12, weight=ft.FontWeight.BOLD),
                                        ft.Text(str(inv.get("invoice_date") or "—"), size=10, color="#64748B"),
                                    ], spacing=1, expand=True,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(money(inv.get("total")), size=12, weight=ft.FontWeight.BOLD),
                                        ft.Text("مسددة" if remaining <= 1e-9 else f"متبقي {money(remaining)}", size=9, color="#16A34A" if remaining <= 1e-9 else "#EA580C"),
                                    ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ]
                        ),
                        padding=9, bgcolor="#F8FAFC", border_radius=12,
                    )
                )
            if not recent:
                recent = [ft.Text("لا توجد فواتير مرتبطة بعد", size=11, color="#64748B")]

            def close(_=None):
                page.close(dialog)

            def edit(_=None):
                close()
                open_editor(data)

            dialog.title = ft.Row(
                [
                    ft.Container(ft.Icon(ft.Icons.PERSON if is_customer else ft.Icons.LOCAL_SHIPPING_OUTLINED, color="#0B63F6"), width=42, height=42, alignment=ft.alignment.center, bgcolor="#EFF6FF", border_radius=14),
                    ft.Column([ft.Text(data["name"], size=18, weight=ft.FontWeight.BOLD), ft.Text(data.get("phone") or "بدون هاتف", size=11, color="#64748B")], spacing=1, expand=True),
                ]
            )
            dialog.content = ft.Container(
                ft.Column(
                    [
                        ft.ResponsiveRow(
                            [
                                ft.Container(small_metric("الرصيد الحالي", money(balance), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, "#0B63F6"), col={"xs": 6, "md": 3}),
                                ft.Container(small_metric("عدد الفواتير", str(int(data.get("invoice_count") or 0)), ft.Icons.RECEIPT_LONG_OUTLINED, "#7C3AED"), col={"xs": 6, "md": 3}),
                                ft.Container(small_metric("إجمالي الفواتير", money(data.get("invoice_total")), ft.Icons.PAID_OUTLINED, "#16A34A"), col={"xs": 6, "md": 3}),
                                ft.Container(small_metric("المتبقي", money(data.get("outstanding_total")), ft.Icons.PENDING_ACTIONS_OUTLINED, "#EA580C"), col={"xs": 6, "md": 3}),
                            ], spacing=7, run_spacing=7,
                        ),
                        ft.Text(f"العنوان: {data.get('address') or '—'}", size=11, color="#475569"),
                        ft.Divider(height=10),
                        ft.Text("آخر الفواتير", size=14, weight=ft.FontWeight.BOLD),
                        ft.Column(recent, spacing=6),
                    ], spacing=9, scroll=ft.ScrollMode.AUTO,
                ), width=680, height=500,
            )
            dialog.actions = [
                ft.TextButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _: confirm_delete(data, dialog)),
                ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=edit),
                ft.FilledButton("إغلاق", on_click=close),
            ]
            page.open(dialog)

        def refresh(_=None):
            parties = repo.list(search.value or "")
            all_parties = repo.list()
            total_balance = sum(float(x.get("balance") or 0) for x in all_parties)
            positive = sum(1 for x in all_parties if abs(float(x.get("balance") or 0)) > 1e-9)
            summary_row.controls = [
                ft.Container(small_metric(f"عدد {title}", str(len(all_parties)), ft.Icons.GROUP_OUTLINED, "#0B63F6"), col={"xs": 6, "md": 4}),
                ft.Container(small_metric("إجمالي الأرصدة", money(total_balance), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, "#16A34A" if total_balance >= 0 else "#EF4444"), col={"xs": 6, "md": 4}),
                ft.Container(small_metric("حسابات بحركة", str(positive), ft.Icons.SYNC_ALT, "#7C3AED"), col={"xs": 12, "md": 4}),
            ]
            rows.controls = []
            for party in parties:
                balance = float(party.get("balance") or 0)
                initials = (party.get("name") or "؟").strip()[:1]
                rows.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Container(ft.Text(initials, size=18, weight=ft.FontWeight.BOLD, color="#0B63F6"), width=46, height=46, alignment=ft.alignment.center, bgcolor="#EFF6FF", border_radius=15),
                                ft.Column(
                                    [
                                        ft.Text(party["name"], weight=ft.FontWeight.BOLD, size=14),
                                        ft.Text(party.get("phone") or party.get("address") or "بدون بيانات اتصال", size=10, color="#64748B", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ], expand=True, spacing=2,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(money(balance), weight=ft.FontWeight.BOLD, size=13, color="#0F172A"),
                                        ft.Text("رصيد", size=9, color="#64748B"),
                                    ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                                ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color="#94A3B8"),
                            ], vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=12, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=16,
                        on_click=lambda _, p=dict(party): show_detail(p), ink=True,
                    )
                )
            if not rows.controls:
                rows.controls.append(ft.Container(ft.Column([ft.Icon(ft.Icons.PERSON_SEARCH, size=44, color="#CBD5E1"), ft.Text("لا توجد نتائج", color="#64748B")], horizontal_alignment=ft.CrossAxisAlignment.CENTER), alignment=ft.alignment.center, padding=30))
            page.update()

        search.on_change = refresh
        content.content = ft.Column(
            [
                summary_row,
                ft.Row([search, ft.FilledButton(f"إضافة {singular}", icon=ft.Icons.ADD, on_click=lambda _: open_editor())], vertical_alignment=ft.CrossAxisAlignment.START),
                rows,
            ], spacing=12, scroll=ft.ScrollMode.AUTO,
        )
        refresh()

    def items_view():
        set_header("المواد", "إدارة المخزون والخدمات والتصنيفات والوحدات")
        categories = ctx.definitions.list_categories()
        units = ctx.definitions.list_units()
        search = ft.TextField(label="بحث في المواد", hint_text="اسم المادة أو الخدمة", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=9)
        summary_row = ft.ResponsiveRow(spacing=8, run_spacing=8)
        filter_state = {"mode": "all"}
        filter_boxes: dict[str, ft.Container] = {}
        LOW_STOCK = 5.0

        def stat_card(label: str, value: str, icon, accent: str):
            return ft.Container(
                ft.Row([
                    ft.Container(ft.Icon(icon, color=accent, size=20), width=40, height=40, alignment=ft.alignment.center, bgcolor="#F8FAFC", border_radius=13),
                    ft.Column([ft.Text(label, size=10, color="#64748B"), ft.Text(value, size=17, weight=ft.FontWeight.BOLD)], spacing=1, expand=True),
                ]),
                padding=11, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=16,
            )

        def filter_box(key: str, label: str, icon):
            box = ft.Container(
                ft.Row([ft.Icon(icon, size=15), ft.Text(label, size=11, weight=ft.FontWeight.W_600)], spacing=5),
                padding=ft.padding.symmetric(horizontal=11, vertical=8),
                border_radius=20, border=ft.border.all(1, "#E2E8F0"), ink=True,
                on_click=lambda _, k=key: set_filter(k),
            )
            filter_boxes[key] = box
            return box

        def update_filter_styles():
            for key, box in filter_boxes.items():
                selected = key == filter_state["mode"]
                box.bgcolor = "#0B63F6" if selected else "#FFFFFF"
                box.border = ft.border.all(1, "#0B63F6" if selected else "#E2E8F0")
                row = box.content
                if isinstance(row, ft.Row):
                    for control in row.controls:
                        if isinstance(control, ft.Text):
                            control.color = "#FFFFFF" if selected else "#475569"
                        elif isinstance(control, ft.Icon):
                            control.color = "#FFFFFF" if selected else "#64748B"

        def set_filter(key: str):
            filter_state["mode"] = key
            update_filter_styles()
            refresh()

        definitions_dialog = ft.AlertDialog(modal=True)
        cat_name = ft.TextField(label="تصنيف جديد")
        unit_name = ft.TextField(label="وحدة جديدة")
        unit_abbr = ft.TextField(label="اختصار")

        def close_definitions(_=None):
            page.close(definitions_dialog)

        def add_category(_=None):
            try:
                ctx.definitions.create_category(cat_name.value or "")
                close_definitions(); notify("تمت إضافة التصنيف"); items_view()
            except Exception as exc:
                notify(str(exc))

        def add_unit(_=None):
            try:
                ctx.definitions.create_unit(unit_name.value or "", unit_abbr.value)
                close_definitions(); notify("تمت إضافة الوحدة"); items_view()
            except Exception as exc:
                notify(str(exc))

        definitions_dialog.title = ft.Text("التصنيفات والوحدات")
        definitions_dialog.content = ft.Container(
            ft.Column([
                ft.Text("التصنيفات", weight=ft.FontWeight.BOLD), cat_name, ft.FilledButton("إضافة تصنيف", icon=ft.Icons.ADD, on_click=add_category),
                ft.Divider(), ft.Text("الوحدات", weight=ft.FontWeight.BOLD),
                ft.ResponsiveRow([ft.Container(unit_name, col={"xs": 8}), ft.Container(unit_abbr, col={"xs": 4})]),
                ft.OutlinedButton("إضافة وحدة", icon=ft.Icons.ADD, on_click=add_unit),
            ], spacing=9, tight=True, scroll=ft.ScrollMode.AUTO), width=460,
        )
        definitions_dialog.actions = [ft.TextButton("إغلاق", on_click=close_definitions)]

        def open_item_editor(item: dict | None = None):
            name = ft.TextField(label="اسم المادة / الخدمة", value=(item or {}).get("name", ""), autofocus=True)
            purchase = ft.TextField(label="سعر الشراء / تكلفة الخدمة", value=str((item or {}).get("purchase_price", 0)), keyboard_type=ft.KeyboardType.NUMBER)
            selling = ft.TextField(label="سعر البيع", value=str((item or {}).get("selling_price", 0)), keyboard_type=ft.KeyboardType.NUMBER)
            qty = ft.TextField(label="الرصيد الافتتاحي", value="0", keyboard_type=ft.KeyboardType.NUMBER, visible=item is None)
            kind = SearchSelect(label="النوع", choices=[("مخزون", "مخزون"), ("خدمة", "خدمة")], value=(item or {}).get("item_type") or "مخزون", allow_clear=False)
            category = SearchSelect(label="التصنيف", choices=[(str(c["id"]), c["name"]) for c in categories], value=str(item.get("category_id")) if item and item.get("category_id") else None)
            base_unit = SearchSelect(label="الوحدة الأساسية", choices=[(str(u["id"]), u["name"]) for u in units], value=str(item.get("base_unit_id")) if item and item.get("base_unit_id") else None)
            current_units = ctx.items.units(int(item["id"])) if item else []
            alt_current = next((u for u in current_units if not u.get("is_base")), None)
            alt_unit = SearchSelect(label="وحدة إضافية", choices=[(str(u["id"]), u["name"]) for u in units], value=str(alt_current.get("id")) if alt_current else None)
            alt_factor = ft.TextField(label="معامل التحويل", value=str(alt_current.get("conversion_factor", 1) if alt_current else 1), keyboard_type=ft.KeyboardType.NUMBER)
            dialog = ft.AlertDialog(modal=True)

            def close(_=None): page.close(dialog)

            def save(_=None):
                try:
                    alternate_units = []
                    if alt_unit.value:
                        alternate_units.append({"unit_id": int(alt_unit.value), "conversion_factor": float(alt_factor.value or 1)})
                    kwargs = dict(
                        name=name.value or "", item_type=kind.value or "مخزون",
                        category_id=int(category.value) if category.value else None,
                        purchase_price=float(purchase.value or 0), selling_price=float(selling.value or 0),
                        base_unit_id=int(base_unit.value) if base_unit.value else None, item_units=alternate_units,
                    )
                    if item:
                        ctx.items.update(int(item["id"]), **kwargs)
                        msg = "تم تحديث المادة"
                    else:
                        ctx.items.create(quantity=float(qty.value or 0), **kwargs)
                        msg = "تمت إضافة المادة"
                    close(); notify(msg); refresh()
                except Exception as exc:
                    notify(str(exc))

            dialog.title = ft.Text("تعديل المادة" if item else "مادة / خدمة جديدة")
            dialog.content = ft.Container(
                ft.Column([
                    name,
                    ft.ResponsiveRow([
                        ft.Container(kind, col={"xs": 6, "md": 4}), ft.Container(category, col={"xs": 6, "md": 4}), ft.Container(base_unit, col={"xs": 12, "md": 4}),
                        ft.Container(qty, col={"xs": 6, "md": 4}), ft.Container(purchase, col={"xs": 6, "md": 4}), ft.Container(selling, col={"xs": 6, "md": 4}),
                        ft.Container(alt_unit, col={"xs": 6, "md": 4}), ft.Container(alt_factor, col={"xs": 6, "md": 4}),
                    ], spacing=7, run_spacing=7),
                    ft.Text("الخدمات لا تؤثر في المخزون، وتستخدم تكلفة الخدمة لحساب الربحية.", size=10, color="#64748B"),
                ], spacing=9, scroll=ft.ScrollMode.AUTO), width=720, height=500,
            )
            dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حفظ", icon=ft.Icons.SAVE_OUTLINED, on_click=save)]
            page.open(dialog)

        def show_item_detail(item: dict):
            try:
                data = ctx.items.get(int(item["id"])) or item
                stats = ctx.items.activity_summary(int(item["id"]))
                movements = ctx.items.movements(int(item["id"]), limit=20)
                item_units = ctx.items.units(int(item["id"]))
            except Exception as exc:
                notify(str(exc)); return
            dialog = ft.AlertDialog(modal=True)
            move_cards = []
            type_labels = {"sale": "بيع", "purchase": "شراء", "adjustment": "تسوية"}
            for mv in movements:
                delta = float(mv.get("quantity_delta") or 0)
                move_cards.append(
                    ft.Container(
                        ft.Row([
                            ft.Container(ft.Icon(ft.Icons.ARROW_DOWNWARD if delta > 0 else ft.Icons.ARROW_UPWARD, size=15, color="#16A34A" if delta > 0 else "#EF4444"), width=32, height=32, alignment=ft.alignment.center, bgcolor="#F8FAFC", border_radius=10),
                            ft.Column([ft.Text(type_labels.get(mv.get("movement_type"), str(mv.get("movement_type"))), size=11, weight=ft.FontWeight.BOLD), ft.Text(f"{mv.get('movement_date') or '—'} • فاتورة #{mv.get('invoice_id') or '—'}", size=9, color="#64748B")], spacing=1, expand=True),
                            ft.Text(f"{delta:+,.2f}", size=12, weight=ft.FontWeight.BOLD, color="#16A34A" if delta > 0 else "#EF4444"),
                        ]), padding=8, bgcolor="#F8FAFC", border_radius=11,
                    )
                )
            if not move_cards:
                move_cards = [ft.Text("لا توجد حركات مخزون بعد", size=11, color="#64748B")]
            units_text = "، ".join(f"{u['name']} × {float(u.get('conversion_factor') or 1):g}" for u in item_units) or "بلا وحدة"

            def close(_=None): page.close(dialog)
            def edit(_=None): close(); open_item_editor(data)

            dialog.title = ft.Row([
                ft.Container(ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color="#0B63F6"), width=42, height=42, alignment=ft.alignment.center, bgcolor="#EFF6FF", border_radius=14),
                ft.Column([ft.Text(data["name"], size=18, weight=ft.FontWeight.BOLD), ft.Text(f"{data.get('item_type')} • {data.get('category_name') or 'بلا تصنيف'}", size=10, color="#64748B")], spacing=1, expand=True),
            ])
            dialog.content = ft.Container(
                ft.Column([
                    ft.ResponsiveRow([
                        ft.Container(stat_card("المخزون", money(stats.get("quantity")), ft.Icons.INVENTORY, "#0B63F6"), col={"xs": 6, "md": 3}),
                        ft.Container(stat_card("متوسط التكلفة", money(stats.get("average_cost")), ft.Icons.PRICE_CHECK_OUTLINED, "#7C3AED"), col={"xs": 6, "md": 3}),
                        ft.Container(stat_card("قيمة المخزون", money(stats.get("inventory_cost_value")), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, "#16A34A"), col={"xs": 6, "md": 3}),
                        ft.Container(stat_card("بسعر البيع", money(stats.get("inventory_sale_value")), ft.Icons.SELL_OUTLINED, "#F59E0B"), col={"xs": 6, "md": 3}),
                    ], spacing=7, run_spacing=7),
                    ft.ResponsiveRow([
                        ft.Container(stat_card("كمية مباعة", money(stats.get("sold_qty")), ft.Icons.TRENDING_UP, "#EF4444"), col={"xs": 6, "md": 3}),
                        ft.Container(stat_card("كمية مشتراة", money(stats.get("purchased_qty")), ft.Icons.TRENDING_DOWN, "#16A34A"), col={"xs": 6, "md": 3}),
                        ft.Container(stat_card("فواتير بيع", str(int(stats.get("sale_count") or 0)), ft.Icons.RECEIPT_LONG, "#0B63F6"), col={"xs": 6, "md": 3}),
                        ft.Container(stat_card("فواتير شراء", str(int(stats.get("purchase_count") or 0)), ft.Icons.SHOPPING_BAG_OUTLINED, "#7C3AED"), col={"xs": 6, "md": 3}),
                    ], spacing=7, run_spacing=7),
                    ft.Text(f"الوحدات: {units_text}", size=10, color="#475569"),
                    ft.Text(f"آخر بيع: {stats.get('last_sale_date') or '—'}   •   آخر شراء: {stats.get('last_purchase_date') or '—'}", size=10, color="#64748B"),
                    ft.Divider(height=8), ft.Text("آخر حركات المخزون", size=14, weight=ft.FontWeight.BOLD), ft.Column(move_cards, spacing=5),
                ], spacing=9, scroll=ft.ScrollMode.AUTO), width=760, height=570,
            )
            dialog.actions = [ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=edit), ft.FilledButton("إغلاق", on_click=close)]
            page.open(dialog)

        def refresh(_=None):
            all_items = ctx.items.list()
            query = (search.value or "").strip().casefold()
            filtered = [i for i in all_items if not query or query in str(i.get("name") or "").casefold()]
            mode = filter_state["mode"]
            if mode == "stock": filtered = [i for i in filtered if i.get("item_type") == "مخزون"]
            elif mode == "service": filtered = [i for i in filtered if i.get("item_type") == "خدمة"]
            elif mode == "low": filtered = [i for i in filtered if i.get("item_type") == "مخزون" and float(i.get("quantity") or 0) < LOW_STOCK]
            inventory_value = sum(float(i.get("quantity") or 0) * float(i.get("average_cost") or 0) for i in all_items if i.get("item_type") == "مخزون")
            low_count = sum(1 for i in all_items if i.get("item_type") == "مخزون" and float(i.get("quantity") or 0) < LOW_STOCK)
            service_count = sum(1 for i in all_items if i.get("item_type") == "خدمة")
            summary_row.controls = [
                ft.Container(stat_card("عدد المواد", str(len(all_items)), ft.Icons.INVENTORY_2_OUTLINED, "#0B63F6"), col={"xs": 6, "md": 3}),
                ft.Container(stat_card("قيمة المخزون", money(inventory_value), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, "#16A34A"), col={"xs": 6, "md": 3}),
                ft.Container(stat_card("مخزون منخفض", str(low_count), ft.Icons.WARNING_AMBER_ROUNDED, "#EF4444"), col={"xs": 6, "md": 3}),
                ft.Container(stat_card("الخدمات", str(service_count), ft.Icons.HANDYMAN_OUTLINED, "#7C3AED"), col={"xs": 6, "md": 3}),
            ]
            rows.controls = []
            if low_count and mode != "low":
                rows.controls.append(ft.Container(ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color="#B91C1C"), ft.Text(f"يوجد {low_count} مواد منخفضة المخزون", expand=True, size=11, weight=ft.FontWeight.W_600), ft.Text("عرضها", size=10, color="#B91C1C")]), padding=11, bgcolor="#FEF2F2", border=ft.border.all(1, "#FECACA"), border_radius=14, on_click=lambda _: set_filter("low"), ink=True))
            for item in filtered:
                qty = float(item.get("quantity") or 0)
                stock = item.get("item_type") == "مخزون"
                status = "خدمة" if not stock else "نفد" if qty <= 0 else "منخفض" if qty < LOW_STOCK else "متوفر"
                status_color = "#7C3AED" if not stock else "#DC2626" if qty <= 0 else "#D97706" if qty < LOW_STOCK else "#16A34A"
                rows.controls.append(ft.Container(
                    ft.Row([
                        ft.Container(ft.Icon(ft.Icons.HANDYMAN_OUTLINED if not stock else ft.Icons.INVENTORY_2_OUTLINED, color="#0B63F6", size=20), width=44, height=44, alignment=ft.alignment.center, bgcolor="#EFF6FF", border_radius=14),
                        ft.Column([ft.Text(item["name"], weight=ft.FontWeight.BOLD, size=13), ft.Text(f"{item.get('category_name') or 'بلا تصنيف'} • {item.get('unit_name') or 'بلا وحدة'}", size=9, color="#64748B")], expand=True, spacing=2),
                        ft.Column([ft.Text("—" if not stock else f"{qty:,.2f}", size=13, weight=ft.FontWeight.BOLD), ft.Text(status, size=9, color=status_color, weight=ft.FontWeight.W_600)], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Column([ft.Text(money(item.get("selling_price")), size=12, weight=ft.FontWeight.BOLD), ft.Text("سعر البيع", size=8, color="#64748B")], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                        ft.Icon(ft.Icons.CHEVRON_LEFT, color="#94A3B8", size=18),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=11, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=16, on_click=lambda _, i=dict(item): show_item_detail(i), ink=True,
                ))
            if not filtered:
                rows.controls.append(ft.Container(ft.Column([ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=46, color="#CBD5E1"), ft.Text("لا توجد مواد مطابقة", color="#64748B")], horizontal_alignment=ft.CrossAxisAlignment.CENTER), alignment=ft.alignment.center, padding=30))
            update_filter_styles(); page.update()

        search.on_change = refresh
        filters = ft.Row([
            filter_box("all", "الكل", ft.Icons.APPS_ROUNDED), filter_box("stock", "مخزون", ft.Icons.INVENTORY_2_OUTLINED),
            filter_box("service", "خدمات", ft.Icons.HANDYMAN_OUTLINED), filter_box("low", "منخفض", ft.Icons.WARNING_AMBER_ROUNDED),
        ], wrap=True, spacing=6)
        content.content = ft.Column([
            summary_row,
            ft.ResponsiveRow([
                ft.Container(ft.FilledButton("مادة جديدة", icon=ft.Icons.ADD, on_click=lambda _: open_item_editor()), col={"xs": 6, "md": 3}),
                ft.Container(ft.OutlinedButton("التصنيفات والوحدات", icon=ft.Icons.TUNE, on_click=lambda _: page.open(definitions_dialog)), col={"xs": 6, "md": 3}),
            ], spacing=7, run_spacing=7),
            search, filters, rows,
        ], spacing=12, scroll=ft.ScrollMode.AUTO)
        refresh()

    def show_security():
        set_header("الأمان والدخول", "إدارة PIN والنمط والجلسة المحفوظة على هذا الجهاز")
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

    invoice_center = InvoiceCenter(page, ctx, content, native_files=native_files, on_title_change=set_header)
    finance_center = FinanceCenter(page, ctx, content, native_files=native_files)
    reports_center = ReportsCenter(page, ctx, content)
    admin_center = AdminCenter(page, ctx, content, on_logout=on_logout, native_files=native_files)
    session = ctx.auth.current()
    if session is None:
        raise RuntimeError("لا توجد جلسة مستخدم")

    page_meta = {
        "dashboard": ("لوحة التحكم", "نظرة عامة على أداء عملك"),
        "items": ("المواد", "إدارة المخزون والخدمات والتصنيفات والوحدات"),
        "customers": ("العملاء", "إدارة العملاء والذمم المدينة"),
        "suppliers": ("الموردون", "إدارة الموردين والذمم الدائنة"),
        "invoices": ("الفواتير", "المبيعات والمشتريات وحالات السداد"),
        "finance": ("المالية", "السندات والمصروفات والحركات المالية"),
        "reports": ("التقارير", "التقارير المالية والمخزون والربحية"),
        "security": ("الأمان والدخول", "PIN والنمط والجلسات المحفوظة"),
        "admin": ("الإدارة", "المستخدمون والنسخ الاحتياطية والترخيص"),
    }

    actions = {
        "dashboard": show_dashboard,
        "items": items_view,
        "customers": lambda: party_view(ctx.customers, "العملاء"),
        "suppliers": lambda: party_view(ctx.suppliers, "الموردون"),
        "invoices": invoice_center.show_center,
        "finance": finance_center.show_center,
        "reports": reports_center.show_center,
        "security": show_security,
        "admin": admin_center.show_center,
    }

    icon_map = {
        "dashboard": ft.Icons.HOME_OUTLINED,
        "items": ft.Icons.INVENTORY_2_OUTLINED,
        "customers": ft.Icons.PEOPLE_OUTLINE,
        "suppliers": ft.Icons.LOCAL_SHIPPING_OUTLINED,
        "invoices": ft.Icons.RECEIPT_LONG_OUTLINED,
        "finance": ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
        "reports": ft.Icons.QUERY_STATS_OUTLINED,
        "security": ft.Icons.LOCK_OUTLINE,
        "admin": ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED,
    }
    label_map = {k: v[0] for k, v in page_meta.items()}
    allowed_keys = [k for k in actions if session.can(k)]
    selected_key = {"value": "dashboard"}
    sidebar_buttons: dict[str, ft.Container] = {}
    mobile_buttons: dict[str, tuple[ft.Container, ft.Icon, ft.Text]] = {}

    def refresh_navigation_state() -> None:
        current = selected_key["value"]
        for key, button in sidebar_buttons.items():
            active = key == current
            button.bgcolor = "#EFF6FF" if active else None
            button.border = ft.border.all(1, "#BFDBFE") if active else None
            row = button.content
            if isinstance(row, ft.Row):
                for ctrl in row.controls:
                    if isinstance(ctrl, ft.Icon):
                        ctrl.color = "#0B63F6" if active else "#64748B"
                    elif isinstance(ctrl, ft.Text):
                        ctrl.color = "#0B63F6" if active else "#334155"
        for key, (box, icon, label) in mobile_buttons.items():
            active = key == current
            icon.color = "#0B63F6" if active else "#94A3B8"
            label.color = "#0B63F6" if active else "#64748B"
            label.weight = ft.FontWeight.BOLD if active else ft.FontWeight.W_500
            box.bgcolor = "#EFF6FF" if active else None

    def navigate(key: str) -> None:
        action = actions.get(key)
        if action is None or key not in allowed_keys:
            return
        selected_key["value"] = key
        title, subtitle = page_meta[key]
        set_header(title, subtitle)
        refresh_navigation_state()
        action()

    def open_sale(_=None) -> None:
        if not session.can("invoices"):
            notify("لا تملك صلاحية الفواتير")
            return
        selected_key["value"] = "sale"
        set_header("فاتورة بيع", "إنشاء فاتورة بيع جديدة — النقدي افتراضيًا")
        refresh_navigation_state()
        invoice_center.show_editor(None, "sale")

    def open_purchase(_=None) -> None:
        if not session.can("invoices"):
            notify("لا تملك صلاحية الفواتير")
            return
        selected_key["value"] = "purchase"
        set_header("فاتورة شراء", "إنشاء فاتورة شراء جديدة — النقدي افتراضيًا")
        refresh_navigation_state()
        invoice_center.show_editor(None, "purchase")

    def nav_button(key: str, label: str, icon, on_click):
        icon_ctrl = ft.Icon(icon, size=21, color="#64748B")
        text_ctrl = ft.Text(label, size=13, weight=ft.FontWeight.W_600, color="#334155", expand=True)
        box = ft.Container(
            ft.Row([icon_ctrl, text_ctrl, ft.Icon(ft.Icons.CHEVRON_LEFT, size=15, color="#CBD5E1")], spacing=12),
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            border_radius=14,
            on_click=on_click,
            ink=True,
        )
        if key in actions:
            sidebar_buttons[key] = box
        return box

    sidebar_controls: list[ft.Control] = []
    for key in allowed_keys:
        sidebar_controls.append(nav_button(key, label_map[key], icon_map[key], lambda _, k=key: navigate(k)))
        if key == "items" and session.can("invoices"):
            sidebar_controls.append(nav_button("sale", "فاتورة بيع", ft.Icons.SHOPPING_CART_CHECKOUT, open_sale))
            sidebar_controls.append(nav_button("purchase", "فاتورة شراء", ft.Icons.ADD_SHOPPING_CART, open_purchase))

    avatar_text = "".join(part[:1] for part in (session.full_name or session.username).split()[:2]).upper() or "N"
    sidebar = ft.Container(
        ft.Column(
            [
                ft.Container(
                    ft.Row(
                        [
                            ft.Image(src="icon.png", width=48, height=48, fit=ft.ImageFit.CONTAIN),
                            ft.Column([ft.Text("Nano | نانو", size=19, weight=ft.FontWeight.BOLD, color="#0F172A"), ft.Text("نظام المحاسبة الذكي", size=10, color="#64748B")], spacing=1, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.only(left=18, right=18, top=18, bottom=14),
                    border=ft.border.only(bottom=ft.BorderSide(1, "#E2E8F0")),
                ),
                ft.Container(ft.Column(sidebar_controls, spacing=5, scroll=ft.ScrollMode.AUTO), padding=12, expand=True),
                ft.Container(
                    ft.Row(
                        [
                            ft.Container(ft.Text(avatar_text, color="#FFFFFF", weight=ft.FontWeight.BOLD), width=40, height=40, alignment=ft.alignment.center, bgcolor="#0B63F6", border_radius=14),
                            ft.Column([ft.Text(session.full_name, size=12, weight=ft.FontWeight.BOLD), ft.Text(session.username, size=10, color="#64748B")], spacing=1, expand=True),
                            ft.IconButton(icon=ft.Icons.LOGOUT, tooltip="تسجيل الخروج", icon_color="#64748B", on_click=lambda _: on_logout()),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=12,
                    border=ft.border.only(top=ft.BorderSide(1, "#E2E8F0")),
                ),
            ],
            spacing=0,
            expand=True,
        ),
        width=280,
        bgcolor="#FFFFFF",
        border=ft.border.only(left=ft.BorderSide(1, "#E2E8F0")),
        visible=False,
    )

    body = ft.Column([top_bar, content], spacing=0, expand=True)

    def mobile_item(key: str, label: str, icon_data, on_click):
        icon = ft.Icon(icon_data, size=23, color="#94A3B8")
        label_ctrl = ft.Text(label, size=10, color="#64748B", text_align=ft.TextAlign.CENTER)
        box = ft.Container(
            ft.Column([icon, label_ctrl], spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER),
            width=62, height=58, alignment=ft.alignment.center, border_radius=15, on_click=on_click, ink=True,
        )
        mobile_buttons[key] = (box, icon, label_ctrl)
        return box

    sale_fab = ft.Container(
        ft.Column(
            [
                ft.Container(
                    ft.Icon(ft.Icons.SHOPPING_CART_CHECKOUT, color="#FFFFFF", size=25),
                    width=58, height=58, alignment=ft.alignment.center,
                    gradient=ft.LinearGradient(colors=["#0B63F6", "#8B5CF6"], begin=ft.alignment.top_left, end=ft.alignment.bottom_right),
                    border_radius=30,
                    border=ft.border.all(4, "#F8FAFC"),
                    shadow=ft.BoxShadow(blur_radius=20, spread_radius=1, color="#BFDBFE", offset=ft.Offset(0, 7)),
                ),
                ft.Text("بيع", size=10, color="#0B63F6", weight=ft.FontWeight.BOLD),
            ],
            spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=72, height=78, margin=ft.margin.only(top=-25), on_click=open_sale, ink=True, border_radius=30,
    )

    more_sheet = ft.BottomSheet(content=ft.Container())

    def show_more(_=None):
        entries: list[tuple[str, str, object, object]] = []
        if session.can("invoices"):
            entries.append(("purchase", "شراء", ft.Icons.ADD_SHOPPING_CART, lambda _: (page.close(more_sheet), open_purchase())))
        for key in ["customers", "suppliers", "finance", "reports", "security", "admin"]:
            if key in allowed_keys:
                entries.append((key, label_map[key], icon_map[key], lambda _, k=key: (page.close(more_sheet), navigate(k))))

        cards = []
        for key, label, icon_data, action in entries:
            cards.append(
                ft.Container(
                    ft.Column(
                        [
                            ft.Container(ft.Icon(icon_data, color="#0B63F6", size=24), width=48, height=48, alignment=ft.alignment.center, bgcolor="#EFF6FF", border_radius=16),
                            ft.Text(label, size=12, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.CENTER),
                        ],
                        spacing=7, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    col={"xs": 4}, padding=9, border_radius=18, on_click=action, ink=True,
                )
            )
        more_sheet.content = ft.Container(
            ft.Column(
                [
                    ft.Container(width=44, height=5, bgcolor="#CBD5E1", border_radius=10, alignment=ft.alignment.center),
                    ft.Text("المزيد", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("الوصول السريع إلى بقية أقسام Nano", size=11, color="#64748B"),
                    ft.ResponsiveRow(cards, spacing=8, run_spacing=8),
                    ft.OutlinedButton("تسجيل الخروج", icon=ft.Icons.LOGOUT, on_click=lambda _: (page.close(more_sheet), on_logout()), width=260),
                ],
                spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=18, right=18, top=12, bottom=24),
            bgcolor="#FFFFFF",
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
        )
        page.open(more_sheet)

    mobile_bar = ft.Container(
        ft.Row(
            [
                mobile_item("dashboard", "الرئيسية", ft.Icons.HOME_OUTLINED, lambda _: navigate("dashboard")),
                mobile_item("items", "المواد", ft.Icons.INVENTORY_2_OUTLINED, lambda _: navigate("items")),
                sale_fab,
                mobile_item("invoices", "الفواتير", ft.Icons.RECEIPT_LONG_OUTLINED, lambda _: navigate("invoices")),
                mobile_item("more", "المزيد", ft.Icons.MORE_HORIZ, show_more),
            ],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            vertical_alignment=ft.CrossAxisAlignment.END,
        ),
        height=78,
        padding=ft.padding.only(left=5, right=5, top=7, bottom=5),
        bgcolor="#FFFFFF",
        border=ft.border.only(top=ft.BorderSide(1, "#E2E8F0")),
        shadow=ft.BoxShadow(blur_radius=20, color="#E2E8F0", offset=ft.Offset(0, -5)),
    )

    # The v0.8 shell intentionally replaces the old NavigationRail / NavigationBar
    # with a branded desktop sidebar and a five-action mobile bottom bar.
    main_row = ft.Row([sidebar, body], expand=True, spacing=0)
    root = ft.Column([main_row, mobile_bar], expand=True, spacing=0)
    page.add(ft.SafeArea(root, expand=True))

    def adapt_navigation(_=None):
        desktop = bool(page.width and page.width >= 900)
        sidebar.visible = desktop
        mobile_bar.visible = not desktop
        content.padding = ft.padding.only(left=24 if desktop else 16, right=24 if desktop else 16, top=18 if desktop else 12, bottom=24 if desktop else 16)
        page.update()

    page.on_resize = adapt_navigation
    navigate("dashboard")
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
