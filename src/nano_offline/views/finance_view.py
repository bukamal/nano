from __future__ import annotations

from datetime import date

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import SearchSelect, SelectAllTextField, SmartAmountField, SmartDateField, empty_state, kpi_card, new_form_sheet, render_form_sheet, status_pill
from nano_offline.core.theme import Colors, Radius, Shadow
from nano_offline.core import currency
from nano_offline.core.home_widget import refresh_home_widget


# Compatibility terminology: «سند دفع» هو نفسه «سند صرف» في الإصدارات السابقة.

class FinanceCenter:
    def __init__(self, page: ft.Page, ctx, content: ft.Container, on_changed=None, native_files=None, on_title_change=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_changed = on_changed
        self.native_files = native_files
        self.on_title_change = on_title_change

    def money(self, value) -> str:
        return currency.format_amount(value, self.ctx.settings)

    def notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    def _changed(self) -> None:
        if self.on_changed:
            self.on_changed()

    def _set_header(self, title: str, subtitle: str = "") -> None:
        if self.on_title_change:
            self.on_title_change(title, subtitle)

    def _nav_chip(self, label: str, icon, *, active: bool, on_click) -> ft.Container:
        # Same pill language as the filter chips used on this screen (and
        # on items_view's list) -- a page-level tab bar built out of
        # ft.FilledButton/OutlinedButton mixed with those chips read as two
        # different button systems stacked on top of each other. One chip
        # style throughout keeps the section switcher visually part of the
        # same screen instead of a separate toolbar bolted on top of it.
        return ft.Container(
            ft.Row(
                [
                    ft.Icon(icon, size=14, color=Colors.WHITE if active else Colors.TEXT_MUTED),
                    ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=Colors.WHITE if active else Colors.TEXT_MUTED),
                ],
                spacing=5, tight=True,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=9),
            bgcolor=Colors.PRIMARY if active else Colors.WHITE,
            border=ft.border.all(1, Colors.PRIMARY if active else Colors.BORDER),
            border_radius=20, ink=True,
            on_click=lambda _: on_click(),
        )

    def _section_nav(self, active: str) -> ft.Row:
        items = [
            ("vouchers", "السندات", ft.Icons.RECEIPT_LONG_OUTLINED, self.show_vouchers),
            ("expenses", "المصروفات", ft.Icons.PAYMENTS_OUTLINED, self.show_expenses),
            ("customers", "كشف العملاء", ft.Icons.PEOPLE_ALT_OUTLINED, lambda: self.show_statements("customer")),
            ("suppliers", "كشف الموردين", ft.Icons.LOCAL_SHIPPING_OUTLINED, lambda: self.show_statements("supplier")),
        ]
        return ft.Row(
            [self._nav_chip(label, icon, active=key == active, on_click=action) for key, label, icon, action in items],
            wrap=True, spacing=8, run_spacing=8,
        )

    def show_center(self) -> None:
        self.show_vouchers()

    def show_vouchers(self) -> None:
        self._set_header("السندات", "سندات القبض والدفع والمصروفات وربطها بالفواتير")
        search = SelectAllTextField(label="بحث في السندات", hint_text="رقم السند، الحساب أو المرجع", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=9)
        summary = ft.ResponsiveRow(spacing=8, run_spacing=8)
        filter_state = {"type": "all"}
        # Real dropdown (ft.Dropdown) instead of a search-style field or a
        # row of chips -- same control used for "ترتيب حسب" on the items
        # screen: tap once, pick from the list, no typing involved.
        type_filter = ft.Dropdown(
            label="نوع السند",
            value="all",
            options=[
                ft.dropdown.Option(key="all", text="الكل"),
                ft.dropdown.Option(key="receipt", text="قبض"),
                ft.dropdown.Option(key="payment", text="دفع"),
            ],
            filled=True,
            bgcolor=Colors.BACKGROUND_ALT,
            border_radius=Radius.MD,
            border_color=Colors.BORDER,
        )

        def set_filter(key: str):
            filter_state["type"] = key
            if type_filter.value != key:
                type_filter.value = key
            refresh()

        def on_type_filter_change(_=None):
            filter_state["type"] = type_filter.value or "all"
            refresh()

        type_filter.on_change = on_type_filter_change

        def refresh(_=None):
            vouchers = self.ctx.payments.list_vouchers()
            receipts = sum(float(v.get("amount") or 0) for v in vouchers if v.get("voucher_type") == "receipt")
            payments = sum(float(v.get("amount") or 0) for v in vouchers if v.get("voucher_type") == "payment")
            unallocated_total = sum(float(v.get("unallocated_amount") or 0) for v in vouchers)
            summary.controls = [
                ft.Container(kpi_card("إجمالي القبض", self.money(receipts), ft.Icons.ADD_CARD, Colors.SUCCESS, on_tap=lambda _: set_filter("receipt")), col={"xs": 6, "md": 4}),
                ft.Container(kpi_card("إجمالي الدفع", self.money(payments), ft.Icons.PAYMENTS_OUTLINED, Colors.DANGER, on_tap=lambda _: set_filter("payment")), col={"xs": 6, "md": 4}),
                ft.Container(kpi_card("رصيد غير موزع", self.money(unallocated_total), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, Colors.PRIMARY), col={"xs": 12, "md": 4}),
            ]
            q = (search.value or "").strip().casefold()
            filtered = []
            for v in vouchers:
                if filter_state["type"] != "all" and v.get("voucher_type") != filter_state["type"]:
                    continue
                hay = f"{v.get('id','')} {v.get('party_name','')} {v.get('reference','')}".casefold()
                if q and q not in hay:
                    continue
                filtered.append(v)
            rows.controls = []
            for voucher in filtered:
                receipt = voucher["voucher_type"] == "receipt"
                title = "سند قبض" if receipt else "سند دفع"
                accent = Colors.SUCCESS if receipt else Colors.DANGER_DARK
                allocated = float(voucher.get("allocated_amount") or 0)
                unallocated = float(voucher.get("unallocated_amount") or 0)
                # Same "badge next to the title" language as the invoices
                # list's status/overdue pills -- an unallocated balance is
                # this row's equivalent of "needs attention".
                badges = [status_pill("على الحساب", Colors.ORANGE_DARK, Colors.WARNING_BG_ALT)] if unallocated > 1e-9 else []
                rows.controls.append(
                    ft.Container(
                        ft.Row([
                            ft.Container(ft.Icon(ft.Icons.SOUTH_WEST if receipt else ft.Icons.NORTH_EAST, size=18, color=accent), width=44, height=44, alignment=ft.alignment.center, bgcolor=Colors.SUCCESS_BG if receipt else Colors.DANGER_BG, border_radius=14),
                            ft.Column([
                                ft.Row([ft.Text(f"{title} #{voucher['id']}", size=13, weight=ft.FontWeight.BOLD, expand=True), *badges]),
                                ft.Text(f"{voucher.get('party_name') or '—'} • {voucher.get('voucher_date') or '—'}", size=10, color=Colors.TEXT_SECONDARY),
                                ft.Text(f"موزع {self.money(allocated)}" + (f" • على الحساب {self.money(unallocated)}" if unallocated else ""), size=9, color=Colors.TEXT_SECONDARY),
                            ], spacing=2, expand=True),
                            ft.Column([
                                ft.Text(self.money(voucher.get("amount")), size=15, weight=ft.FontWeight.BOLD, color=accent),
                                ft.Text(voucher.get("reference") or "بدون مرجع", size=9, color=Colors.TEXT_FAINT, max_lines=1),
                            ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                            ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color=Colors.TEXT_FAINT),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=12, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=16, shadow=Shadow.SM,
                        on_click=lambda _, vid=int(voucher["id"]): self.show_voucher_detail(vid), ink=True,
                    )
                )
            if not rows.controls:
                if vouchers:
                    rows.controls.append(empty_state(
                        "لا توجد سندات مطابقة",
                        icon=ft.Icons.RECEIPT_LONG_OUTLINED,
                        hint="جرّب تغيير البحث أو عوامل التصفية",
                    ))
                else:
                    rows.controls.append(empty_state(
                        "لا توجد سندات بعد",
                        icon=ft.Icons.RECEIPT_LONG_OUTLINED,
                        hint="أنشئ أول سند قبض أو دفع لتتبع حركة الصندوق",
                        action_label="سند قبض جديد",
                        on_action=lambda _: self.show_voucher_dialog(None, "receipt"),
                    ))
            self.page.update()

        search.on_change = refresh

        # Floating "new voucher" action: one FAB that expands into the three
        # voucher types (قبض / دفع / مصروف) instead of a three-button row
        # competing with the summary cards and filters for space at the top
        # -- same speed-dial pattern already used for "فاتورة جديدة" in
        # invoice_view.py. Each mini-action is colored to match that type's
        # accent in the list below (السطر أدناه بنفس لون السند في القائمة)
        # so the three voucher types stay visually distinct end-to-end.
        fab_state = {"open": False}

        def close_fab(_=None):
            if fab_state["open"]:
                fab_state["open"] = False
                render_fab()
                self.page.update()

        def open_voucher(kind: str):
            def handler(_=None):
                close_fab()
                self.show_voucher_dialog(None, kind)
            return handler

        def open_expense_from_fab(_=None):
            close_fab()
            self.show_expense_dialog()

        def toggle_fab(_):
            fab_state["open"] = not fab_state["open"]
            render_fab()
            self.page.update()

        def mini_action(label: str, icon, bg: str, on_click) -> ft.Row:
            return ft.Row(
                [
                    ft.Container(
                        ft.Text(label, size=12, color=Colors.WHITE, weight=ft.FontWeight.W_600),
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        bgcolor=Colors.TEXT_PRIMARY,
                        border_radius=10,
                    ),
                    ft.Container(
                        ft.Icon(icon, color=Colors.WHITE, size=20),
                        width=46, height=46, border_radius=23,
                        bgcolor=bg, alignment=ft.alignment.center,
                        shadow=Shadow.MD, ink=True, on_click=on_click,
                    ),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.END,
                animate_opacity=160,
            )

        scrim = ft.Container(
            expand=True,
            bgcolor=ft.Colors.with_opacity(0.001, Colors.TEXT_PRIMARY),
            visible=False,
            on_click=close_fab,
            left=0, right=0, top=0, bottom=0,
        )

        mini_expense = mini_action("سند مصروف", ft.Icons.RECEIPT_OUTLINED, Colors.ORANGE, open_expense_from_fab)
        mini_payment = mini_action("سند دفع", ft.Icons.PAYMENTS_OUTLINED, Colors.DANGER_DARK, open_voucher("payment"))
        mini_receipt = mini_action("سند قبض", ft.Icons.ADD_CARD, Colors.SUCCESS, open_voucher("receipt"))
        main_fab = ft.Container(
            ft.Icon(ft.Icons.ADD_ROUNDED, color=Colors.WHITE, size=26),
            width=56, height=56, border_radius=28,
            bgcolor=Colors.PRIMARY, alignment=ft.alignment.center,
            shadow=Shadow.LG, ink=True, on_click=toggle_fab,
            rotate=ft.Rotate(0), animate_rotation=160,
        )
        fab_column = ft.Column(
            [mini_expense, mini_payment, mini_receipt, main_fab],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.END,
        )
        fab_container = ft.Container(fab_column, right=16, bottom=16, animate_opacity=160)

        def render_fab() -> None:
            is_open = fab_state["open"]
            for mini in (mini_expense, mini_payment, mini_receipt):
                mini.visible = is_open
                mini.opacity = 1 if is_open else 0
            main_fab.rotate = ft.Rotate(0.125 * 6.283) if is_open else ft.Rotate(0)  # 45°
            scrim.visible = is_open

        render_fab()

        # Same sticky-header / scrolling-body split as invoice_view and
        # items_view: the section tabs, search, and type filters live in a
        # bordered white bar that stays put, while the KPI cards and the
        # voucher list scroll together underneath it.
        sticky_header = ft.Container(
            ft.Column(
                [
                    self._section_nav("vouchers"),
                    search,
                    type_filter,
                ],
                spacing=10,
            ),
            padding=ft.padding.only(left=16, right=16, top=14, bottom=12),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
            shadow=Shadow.SM,
        )
        scroll_body = ft.Container(
            ft.Column(
                [
                    summary,
                    rows,
                    # Breathing room so the last card never sits directly under
                    # the floating action button.
                    ft.Container(height=84),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            expand=True,
            padding=ft.padding.only(top=12, left=16, right=16),
        )
        body = ft.Column([sticky_header, scroll_body], spacing=0, expand=True)
        self.content.content = ft.Stack([body, scrim, fab_container], expand=True)
        refresh()

    def _voucher_html(self, voucher: dict) -> str:
        receipt = voucher.get("voucher_type") == "receipt"
        title = "سند قبض" if receipt else "سند دفع"
        accent = Colors.SUCCESS_ALT if receipt else Colors.DANGER_DARK
        party_label = "العميل" if receipt else "المورد"
        return f"""<!doctype html><html dir='rtl' lang='ar'><head><meta charset='utf-8'><style>
        @page {{ size:80mm auto; margin:0; }} * {{ box-sizing:border-box; }} body {{ width:80mm; margin:0; padding:5mm; font-family:Arial,sans-serif; color:#111; }}
        .brand {{ text-align:center; color:#0F766E; font-size:20px; font-weight:800; }} .sub {{ text-align:center; font-size:10px; color:#64748B; }}
        .type {{ text-align:center; font-size:15px; font-weight:700; margin:8px 0; }} .amount {{ text-align:center; color:{accent}; font-size:24px; font-weight:900; margin:10px 0; }}
        .line {{ border-top:1px dashed #777; margin:8px 0; }} .row {{ display:flex; justify-content:space-between; gap:8px; margin:5px 0; font-size:11px; }}
        .label {{ color:#64748B; }} .footer {{ text-align:center; color:#94A3B8; font-size:9px; margin-top:12px; }}
        </style></head><body><div class='brand'>Nano | نانو</div><div class='sub'>نظام المحاسبة الذكي</div><div class='type'>{title} #{voucher.get('id')}</div>
        <div class='amount'>{self.money(voucher.get('amount'))}</div><div class='line'></div>
        <div class='row'><span class='label'>التاريخ</span><strong>{voucher.get('voucher_date') or '—'}</strong></div>
        <div class='row'><span class='label'>{party_label}</span><strong>{voucher.get('party_name') or '—'}</strong></div>
        <div class='row'><span class='label'>المرجع</span><strong>{voucher.get('reference') or '—'}</strong></div>
        <div class='row'><span class='label'>موزع</span><strong>{self.money(voucher.get('allocated_amount'))}</strong></div>
        <div class='row'><span class='label'>على الحساب</span><strong>{self.money(voucher.get('unallocated_amount'))}</strong></div>
        <div class='line'></div><div style='font-size:10px'>{voucher.get('notes') or ''}</div><div class='footer'>تم إنشاء السند بواسطة Nano</div></body></html>"""

    def show_voucher_detail(self, voucher_id: int) -> None:
        voucher = self.ctx.payments.get_voucher(voucher_id)
        if not voucher:
            self.notify("السند غير موجود"); return
        receipt = voucher.get("voucher_type") == "receipt"
        title = "سند قبض" if receipt else "سند دفع"
        accent = Colors.SUCCESS if receipt else Colors.DANGER_DARK
        allocations = voucher.get("allocations") or []
        alloc_controls = []
        for a in allocations:
            alloc_controls.append(ft.Container(ft.Row([ft.Text(f"فاتورة #{a['invoice_id']}", size=11, expand=True), ft.Text(self.money(a.get("amount")), size=11, weight=ft.FontWeight.BOLD)]), padding=7, bgcolor=Colors.BACKGROUND, border_radius=10))
        if not alloc_controls:
            alloc_controls.append(ft.Text("لا توجد توزيعات على فواتير", size=10, color=Colors.TEXT_SECONDARY))
        # Bottom sheet instead of a centered AlertDialog -- same read-mostly
        # detail treatment used for item detail (items_view.py) and
        # customer/supplier detail (parties_view.py): opened by tapping a
        # row in a list, no destructive action of its own.
        detail_sheet = ft.BottomSheet(content=ft.Container(), enable_drag=True, maintain_bottom_view_insets_padding=True)

        def close(_=None): self.page.close(detail_sheet)
        def edit(_=None): close(); self.show_voucher_dialog(voucher_id)
        def duplicate(_=None):
            close(); self.show_voucher_dialog(None, voucher.get("voucher_type") or "receipt", initial_data=voucher)
        async def print_voucher(_=None):
            if self.native_files is None:
                self.notify("الطباعة الأصلية غير مهيأة في هذا البناء"); return
            try:
                await self.native_files.print_html(self._voucher_html(voucher), name=f"nano-voucher-{voucher_id}")
            except Exception as exc:
                self.notify(str(exc), kind="error")

        # Same explicit-height approach as the other converted detail
        # sheets: outer Container height computed from the real screen
        # height, scrollable body, fixed action footer (wraps onto a
        # second line on narrow screens since this one has five actions).
        page_h = self.page.height or 780
        total_sheet_h = min(int(page_h * 0.55), 600)
        header_reserved, footer_reserved, gaps = 70, 70, 24
        body_area_height = max(160, total_sheet_h - header_reserved - footer_reserved - gaps)

        detail_sheet.content = ft.Container(
            ft.Column(
                [
                    ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10, alignment=ft.alignment.center),
                    ft.Text(f"{title} #{voucher_id}", size=18, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        ft.Column([
                            ft.Container(ft.Column([ft.Text(self.money(voucher.get("amount")), size=28, weight=ft.FontWeight.BOLD, color=accent), ft.Text(title, size=11, color=Colors.TEXT_SECONDARY)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2), padding=14, bgcolor=Colors.BACKGROUND, border_radius=16),
                            ft.ResponsiveRow([
                                ft.Container(ft.Text(f"التاريخ: {voucher.get('voucher_date') or '—'}", size=11), col={"xs": 6}),
                                ft.Container(ft.Text(f"الحساب: {voucher.get('party_name') or '—'}", size=11), col={"xs": 6}),
                                ft.Container(ft.Text(f"المرجع: {voucher.get('reference') or '—'}", size=11), col={"xs": 6}),
                                ft.Container(ft.Text(f"على الحساب: {self.money(voucher.get('unallocated_amount'))}", size=11), col={"xs": 6}),
                            ]),
                            ft.Text(voucher.get("notes") or "بدون ملاحظات", size=10, color=Colors.TEXT_SECONDARY),
                            ft.Divider(height=8), ft.Text("التوزيعات", size=13, weight=ft.FontWeight.BOLD), ft.Column(alloc_controls, spacing=5),
                        ], spacing=8, scroll=ft.ScrollMode.AUTO),
                        height=body_area_height, padding=ft.padding.only(top=4),
                    ),
                    ft.Container(
                        ft.Row(
                            [
                                ft.TextButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _: (close(), self.confirm_delete_voucher(voucher_id))),
                                ft.TextButton("تكرار", icon=ft.Icons.CONTENT_COPY, on_click=duplicate),
                                ft.OutlinedButton("طباعة 80mm", icon=ft.Icons.PRINT_OUTLINED, on_click=print_voucher),
                                ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=edit),
                                ft.FilledButton("إغلاق", on_click=close),
                            ],
                            spacing=8, run_spacing=8, wrap=True,
                        ),
                        padding=ft.padding.only(top=4),
                    ),
                ],
                spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            height=total_sheet_h,
            padding=ft.padding.only(left=18, right=18, top=12, bottom=20),
            bgcolor=Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
            shadow=Shadow.LG,
        )
        self.page.open(detail_sheet)

    def show_voucher_dialog(self, voucher_id: int | None = None, voucher_type: str = "receipt", initial_data: dict | None = None) -> None:
        existing = self.ctx.payments.get_voucher(voucher_id) if voucher_id else None
        seed = existing or initial_data or {}
        if voucher_id and not existing:
            self.notify("السند غير موجود")
            return

        current_type = existing["voucher_type"] if existing else seed.get("voucher_type", voucher_type)
        type_dd = SearchSelect(
            label="نوع السند",
            value=current_type,
            choices=[("receipt", "قبض من عميل"), ("payment", "صرف لمورد")],
            allow_clear=False,
        )
        party_dd = SearchSelect(label="الحساب")
        amount = SmartAmountField(
            label=currency.amount_field_label("المبلغ", self.ctx.settings),
            value=currency.to_input_text(seed.get("amount", 0), self.ctx.settings),
        )
        vdate = SmartDateField(label="التاريخ", value=str(seed.get("voucher_date") or date.today().isoformat()))
        reference = SelectAllTextField(label="المرجع", value=seed.get("reference") or "")
        notes = SelectAllTextField(label="ملاحظات", value=seed.get("notes") or "", multiline=True, min_lines=1, max_lines=3)
        existing_allocations = {int(a["invoice_id"]): float(a["amount"]) for a in (existing.get("allocations") or [])} if existing else {}
        default_mode = "manual" if existing_allocations else "none" if existing else "oldest"
        allocation_mode = SearchSelect(
            label="توزيع الدفعة",
            value=default_mode,
            choices=[
                ("oldest", "الأقدم أولًا تلقائيًا"),
                ("manual", "توزيع يدوي"),
                ("none", "رصيد على الحساب دون توزيع"),
            ],
            allow_clear=False,
        )
        manual_column = ft.Column(spacing=6)
        manual_fields: dict[int, ft.TextField] = {}

        def party_type() -> str:
            return "customer" if type_dd.value == "receipt" else "supplier"

        def load_parties(reset: bool = False) -> None:
            source = self.ctx.customers.list() if type_dd.value == "receipt" else self.ctx.suppliers.list()
            party_dd.label = "العميل" if type_dd.value == "receipt" else "المورد"
            party_dd.set_choices([(str(p["id"]), p["name"]) for p in source])
            if reset:
                party_dd.value = None
            elif seed and seed.get("voucher_type") == type_dd.value:
                pid = seed.get("customer_id") if type_dd.value == "receipt" else seed.get("supplier_id")
                party_dd.value = str(pid) if pid else None

        def refresh_manual(_=None) -> None:
            manual_column.controls = []
            manual_fields.clear()
            if allocation_mode.value != "manual":
                self.page.update()
                return
            if not party_dd.value:
                manual_column.controls.append(ft.Text("اختر الحساب أولًا لعرض الفواتير المفتوحة.", size=12, color=Colors.TEXT_SECONDARY))
                self.page.update()
                return
            exclude_payment_id = int(existing["payment_id"]) if existing and existing.get("payment_id") else None
            invoices = self.ctx.payments.allocatable_invoices(
                party_type(), int(party_dd.value), exclude_payment_id=exclude_payment_id
            )
            if not invoices:
                manual_column.controls.append(ft.Text("لا توجد فواتير قابلة للتوزيع.", size=12, color=Colors.TEXT_SECONDARY))
            for inv in invoices:
                iid = int(inv["id"])
                field = SmartAmountField(
                    label=f"توزيع على فاتورة #{iid}",
                    value=currency.to_input_text(existing_allocations.get(iid, 0), self.ctx.settings),
                    width=170,
                )
                manual_fields[iid] = field
                manual_column.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(f"فاتورة #{iid}", weight=ft.FontWeight.BOLD),
                                        ft.Text(f"{inv['invoice_date']} • المتاح للتوزيع {self.money(inv['allocatable_amount'])}", size=11, color=Colors.TEXT_SECONDARY),
                                    ],
                                    expand=True,
                                    spacing=2,
                                ),
                                field,
                            ],
                            wrap=True,
                        ),
                        padding=8,
                        border=ft.border.all(1, Colors.BORDER_ALT),
                        border_radius=8,
                    )
                )
            self.page.update()

        def type_changed(_):
            load_parties(reset=True)
            refresh_manual()

        type_dd.on_change = type_changed
        party_dd.on_change = refresh_manual
        allocation_mode.on_change = refresh_manual
        load_parties()

        sheet = new_form_sheet()

        def close(_=None):
            self.page.close(sheet)

        def save(_):
            try:
                amount_value = currency.parse_display_input(amount.value, self.ctx.settings)
                pid = int(party_dd.value) if party_dd.value else None
                kwargs = {
                    "voucher_type": type_dd.value,
                    "amount": amount_value,
                    "voucher_date": vdate.value,
                    "reference": reference.value,
                    "notes": notes.value,
                    "allocation_mode": allocation_mode.value,
                    "allocations": {
                        iid: currency.parse_display_input(field.value, self.ctx.settings)
                        for iid, field in manual_fields.items()
                    } if allocation_mode.value == "manual" else None,
                    "customer_id": pid if type_dd.value == "receipt" else None,
                    "supplier_id": pid if type_dd.value == "payment" else None,
                }
                if voucher_id:
                    self.ctx.payments.update_voucher(voucher_id, **kwargs)
                    message = f"تم تعديل السند #{voucher_id}"
                else:
                    new_id = self.ctx.payments.create_voucher(**kwargs)
                    message = f"تم حفظ السند #{new_id}"
                close()
                self.notify(message)
                self.show_vouchers()
                self._changed()
                # PHASE10: receipt/payment vouchers move the cash balance
                # shown on the home screen widget -- refresh it right away.
                refresh_home_widget(self.page, self.native_files, self.ctx.dashboard)
            except Exception as exc:
                self.notify(str(exc), kind="error")

        render_form_sheet(
            self.page, sheet,
            title="تعديل سند" if voucher_id else "سند جديد",
            fields=[
                ft.ResponsiveRow(
                    [
                        ft.Container(type_dd, col={"xs": 12, "md": 6}),
                        ft.Container(party_dd, col={"xs": 12, "md": 6}),
                        ft.Container(amount, col={"xs": 6, "md": 4}),
                        ft.Container(vdate, col={"xs": 6, "md": 4}),
                        ft.Container(reference, col={"xs": 12, "md": 4}),
                    ]
                ),
                allocation_mode,
                manual_column,
                notes,
            ],
            on_close=close, on_save=save,
        )
        self.page.open(sheet)
        refresh_manual()

    def confirm_delete_voucher(self, voucher_id: int) -> None:
        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def delete(_):
            try:
                self.ctx.payments.delete_voucher(voucher_id)
                self.page.close(dialog)
                self.notify("تم حذف السند وعكس أثره المالي", kind="success", sound_kind="delete")
                self.show_vouchers()
                self._changed()
            except Exception as exc:
                self.page.close(dialog)
                self.notify(str(exc), kind="error")

        dialog.title = ft.Text("حذف السند")
        dialog.content = ft.Text("سيتم حذف السند وتوزيعاته وإعادة احتساب الذمم والفواتير. هل تريد المتابعة؟")
        dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حذف", icon=ft.Icons.DELETE_FOREVER, on_click=delete)]
        self.page.open(dialog)

    def show_expenses(self) -> None:
        self._set_header("المصروفات", "تسجيل ومتابعة مصروفات النشاط")
        search = SelectAllTextField(label="بحث في المصروفات", hint_text="البيان، التصنيف أو المرجع", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=9)
        summary = ft.ResponsiveRow(spacing=8, run_spacing=8)
        filter_state = {"month_only": False}

        def toggle_month(_=None):
            filter_state["month_only"] = not filter_state["month_only"]
            refresh()

        def refresh(_=None):
            expenses = self.ctx.expenses.list_expenses()
            q = (search.value or "").strip().casefold()
            current_month = date.today().isoformat()[:7]
            filtered = [
                e for e in expenses
                if (not q or q in f"{e.get('description','')} {e.get('category_name','')} {e.get('reference','')}".casefold())
                and (not filter_state["month_only"] or str(e.get("expense_date") or "").startswith(current_month))
            ]
            total = sum(float(e.get("amount") or 0) for e in expenses)
            categories = {str(e.get("category_name") or "بلا تصنيف") for e in expenses}
            month_total = sum(float(e.get("amount") or 0) for e in expenses if str(e.get("expense_date") or "").startswith(current_month))
            summary.controls = [
                ft.Container(kpi_card("إجمالي المصروفات", self.money(total), ft.Icons.PAYMENTS_OUTLINED, Colors.DANGER_DARK), col={"xs": 6, "md": 4}),
                ft.Container(kpi_card("هذا الشهر", self.money(month_total), ft.Icons.CALENDAR_MONTH_OUTLINED, Colors.ORANGE, on_tap=lambda _: toggle_month()), col={"xs": 6, "md": 4}),
                ft.Container(kpi_card("التصنيفات", str(len(categories)), ft.Icons.CATEGORY_OUTLINED, Colors.PURPLE), col={"xs": 12, "md": 4}),
            ]
            rows.controls = []
            for exp in filtered:
                rows.controls.append(ft.Container(
                    ft.Row([
                        ft.Container(ft.Icon(ft.Icons.RECEIPT_OUTLINED, size=18, color=Colors.ORANGE), width=44, height=44, alignment=ft.alignment.center, bgcolor=Colors.WARNING_BG_ALT, border_radius=14),
                        ft.Column([
                            ft.Row([
                                ft.Text(exp["description"], size=13, weight=ft.FontWeight.BOLD, expand=True),
                                status_pill(exp.get("category_name") or "بلا تصنيف", Colors.PURPLE, Colors.PURPLE_BG),
                            ]),
                            ft.Text(exp.get("expense_date") or "—", size=10, color=Colors.TEXT_SECONDARY),
                        ], spacing=2, expand=True),
                        ft.Column([ft.Text(self.money(exp.get("amount")), size=15, weight=ft.FontWeight.BOLD, color=Colors.DANGER_DARK), ft.Text(exp.get("reference") or "بدون مرجع", size=9, color=Colors.TEXT_FAINT)], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                        ft.PopupMenuButton(items=[
                            ft.PopupMenuItem(text="تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _, eid=int(exp["id"]): self.show_expense_dialog(eid)),
                            ft.PopupMenuItem(text="حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _, eid=int(exp["id"]): self.confirm_delete_expense(eid)),
                        ]),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=12, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=16, shadow=Shadow.SM,
                ))
            if not rows.controls:
                if expenses:
                    rows.controls.append(empty_state(
                        "لا توجد مصروفات مطابقة",
                        icon=ft.Icons.RECEIPT_OUTLINED,
                        hint="جرّب تغيير البحث أو عوامل التصفية",
                    ))
                else:
                    rows.controls.append(empty_state(
                        "لا توجد مصروفات بعد",
                        icon=ft.Icons.RECEIPT_OUTLINED,
                        hint="سجّل أول مصروف لمتابعة تكاليف النشاط",
                        action_label="مصروف جديد",
                        on_action=lambda _: self.show_expense_dialog(),
                    ))
            self.page.update()

        search.on_change = refresh
        # Same sticky-header / scrolling-body split as show_vouchers and
        # invoice_view: section tabs + search stay pinned, KPI cards and the
        # expense list scroll together beneath them.
        sticky_header = ft.Container(
            ft.Column([self._section_nav("expenses"), search], spacing=10),
            padding=ft.padding.only(left=16, right=16, top=14, bottom=12),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
            shadow=Shadow.SM,
        )
        scroll_body = ft.Container(
            ft.Column(
                [
                    summary,
                    ft.Row([ft.FilledButton("مصروف جديد", icon=ft.Icons.ADD, on_click=lambda _: self.show_expense_dialog())]),
                    rows,
                    ft.Container(height=24),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            expand=True,
            padding=ft.padding.only(top=12, left=16, right=16),
        )
        self.content.content = ft.Column([sticky_header, scroll_body], spacing=0, expand=True)
        refresh()

    def show_expense_dialog(self, expense_id: int | None = None) -> None:
        existing = self.ctx.expenses.get_expense(expense_id) if expense_id else None
        categories = self.ctx.expenses.list_categories()
        category = SearchSelect(
            label="التصنيف",
            value=str(existing["category_id"]) if existing and existing.get("category_id") else None,
            choices=[(str(c["id"]), c["name"]) for c in categories],
        )
        new_category = SelectAllTextField(label="تصنيف جديد")
        description = SelectAllTextField(label="البيان", value=(existing["description"] if existing else ""))
        amount = SmartAmountField(
            label=currency.amount_field_label("المبلغ", self.ctx.settings),
            value=currency.to_input_text(existing.get("amount", 0) if existing else 0, self.ctx.settings),
        )
        edate = SmartDateField(label="التاريخ", value=str(existing["expense_date"] if existing else date.today().isoformat()))
        reference = SelectAllTextField(label="المرجع", value=(existing.get("reference") or "") if existing else "")
        notes = SelectAllTextField(label="ملاحظات", value=(existing.get("notes") or "") if existing else "", multiline=True)
        sheet = new_form_sheet()

        def close(_=None):
            self.page.close(sheet)

        def save(_):
            try:
                category_id = int(category.value) if category.value else None
                if (new_category.value or "").strip():
                    category_id = self.ctx.expenses.create_category(new_category.value)
                kwargs = {
                    "amount": currency.parse_display_input(amount.value, self.ctx.settings),
                    "description": description.value or "",
                    "expense_date": edate.value,
                    "category_id": category_id,
                    "reference": reference.value,
                    "notes": notes.value,
                }
                if expense_id:
                    self.ctx.expenses.update_expense(expense_id, **kwargs)
                else:
                    self.ctx.expenses.create_expense(**kwargs)
                close()
                self.notify("تم حفظ المصروف")
                self.show_expenses()
                self._changed()
            except Exception as exc:
                self.notify(str(exc), kind="error")

        render_form_sheet(
            self.page, sheet,
            title="تعديل مصروف" if expense_id else "مصروف جديد",
            fields=[category, new_category, description, ft.Row([amount, edate], wrap=True), reference, notes],
            on_close=close, on_save=save,
        )
        self.page.open(sheet)

    def confirm_delete_expense(self, expense_id: int) -> None:
        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def delete(_):
            try:
                self.ctx.expenses.delete_expense(expense_id)
                self.page.close(dialog)
                self.notify("تم حذف المصروف", kind="success", sound_kind="delete")
                self.show_expenses()
                self._changed()
            except Exception as exc:
                self.page.close(dialog)
                self.notify(str(exc), kind="error")

        dialog.title = ft.Text("حذف المصروف")
        dialog.content = ft.Text("سيتم حذف المصروف وعكس أثره على الصندوق والأرباح.")
        dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حذف", on_click=delete)]
        self.page.open(dialog)

    def show_statements(self, party_type: str) -> None:
        source = self.ctx.customers.list() if party_type == "customer" else self.ctx.suppliers.list()
        title = "كشف حساب العملاء" if party_type == "customer" else "كشف حساب الموردين"
        active = "customers" if party_type == "customer" else "suppliers"
        self._set_header(title, "الرصيد والحركات على الحساب خلال فترة محددة")
        party_dd = SearchSelect(
            label="العميل" if party_type == "customer" else "المورد",
            choices=[(str(p["id"]), p["name"]) for p in source],
        )
        date_from = SmartDateField(label="من تاريخ", hint_text="YYYY-MM-DD")
        date_to = SmartDateField(label="إلى تاريخ", hint_text="YYYY-MM-DD")
        result = ft.Column(spacing=8)
        export_actions = ft.Row(visible=False, wrap=True)

        async def print_statement(_):
            if not party_dd.value:
                self.notify("اختر الحساب أولًا")
                return
            if self.native_files is None:
                self.notify("الطباعة الأصلية غير مهيأة في هذا البناء")
                return
            try:
                html = self.ctx.documents.statement_html(
                    party_type,
                    int(party_dd.value),
                    date_from=(date_from.value or "").strip() or None,
                    date_to=(date_to.value or "").strip() or None,
                )
                await self.native_files.print_html(html, name=f"nano-statement-{party_type}-{party_dd.value}")
            except Exception as exc:
                self.notify(str(exc), kind="error")

        async def share_statement_pdf(_):
            if not party_dd.value:
                self.notify("اختر الحساب أولًا")
                return
            if self.native_files is None:
                self.notify("تصدير PDF غير مهيأ في هذا البناء")
                return
            try:
                html = self.ctx.documents.statement_html(
                    party_type,
                    int(party_dd.value),
                    date_from=(date_from.value or "").strip() or None,
                    date_to=(date_to.value or "").strip() or None,
                )
                await self.native_files.share_pdf(
                    html, filename=f"nano_statement_{party_type}_{party_dd.value}.pdf"
                )
            except Exception as exc:
                self.notify(str(exc), kind="error")

        export_actions.controls = [
            ft.OutlinedButton("طباعة الكشف", icon=ft.Icons.PRINT_OUTLINED, on_click=print_statement),
            ft.OutlinedButton("مشاركة PDF", icon=ft.Icons.PICTURE_AS_PDF_OUTLINED, on_click=share_statement_pdf),
        ]

        def render(_=None):
            result.controls = []
            if not party_dd.value:
                export_actions.visible = False
                self.page.update()
                return
            try:
                data = self.ctx.statements.party_statement(
                    party_type,
                    int(party_dd.value),
                    date_from=(date_from.value or "").strip() or None,
                    date_to=(date_to.value or "").strip() or None,
                )
                export_actions.visible = True
                balance = float(data["current_balance"])
                balance_label = "رصيد مستحق" if balance >= 0 else "رصيد دائن للطرف"
                result.controls.append(
                    ft.ResponsiveRow(
                        [
                            ft.Container(kpi_card("الرصيد الحالي", f"{self.money(abs(balance))} — {balance_label}", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, Colors.PRIMARY if balance >= 0 else Colors.SUCCESS), col={"xs": 12, "md": 4}),
                            ft.Container(kpi_card("الرصيد الافتتاحي للفترة", self.money(data["opening_balance"]), ft.Icons.HISTORY_OUTLINED, Colors.PURPLE), col={"xs": 6, "md": 4}),
                            ft.Container(kpi_card("فواتير مفتوحة", str(len(data["open_invoices"])), ft.Icons.RECEIPT_LONG_OUTLINED, Colors.ORANGE), col={"xs": 6, "md": 4}),
                        ],
                        spacing=8, run_spacing=8,
                    )
                )
                # Same icon-badge card language as the vouchers/invoices
                # list rows -- an inflow is styled like a "قبض" row, an
                # outflow like a "دفع" row, instead of a plain bordered line.
                for row in data["rows"]:
                    movement = float(row["movement"])
                    inflow = movement >= 0
                    movement_text = f"+{self.money(movement)}" if inflow else f"-{self.money(abs(movement))}"
                    accent = Colors.SUCCESS if inflow else Colors.DANGER_DARK
                    result.controls.append(
                        ft.Container(
                            ft.Row(
                                [
                                    ft.Container(ft.Icon(ft.Icons.SOUTH_WEST if inflow else ft.Icons.NORTH_EAST, size=18, color=accent), width=44, height=44, alignment=ft.alignment.center, bgcolor=Colors.SUCCESS_BG if inflow else Colors.DANGER_BG, border_radius=14),
                                    ft.Column(
                                        [
                                            ft.Text(row["description"] or row["source_label"], size=13, weight=ft.FontWeight.BOLD),
                                            ft.Text(f"{row['entry_date']} • {row['source_label']} #{row['source_id'] or '—'}", size=10, color=Colors.TEXT_SECONDARY),
                                        ],
                                        expand=True,
                                        spacing=2,
                                    ),
                                    ft.Column(
                                        [
                                            ft.Text(movement_text, size=15, weight=ft.FontWeight.BOLD, color=accent),
                                            ft.Text(f"الرصيد {self.money(row['balance'])}", size=9, color=Colors.TEXT_FAINT),
                                        ],
                                        spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END,
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            padding=12, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=16, shadow=Shadow.SM,
                        )
                    )
                if not data["rows"]:
                    result.controls.append(empty_state(
                        "لا توجد حركات في الفترة المحددة",
                        icon=ft.Icons.SWAP_VERT_ROUNDED,
                        hint="جرّب توسيع نطاق التاريخ",
                    ))
            except Exception as exc:
                export_actions.visible = False
                self.notify(str(exc), kind="error")
            self.page.update()

        party_dd.on_change = render
        # Same sticky-header / scrolling-body split as the other finance
        # sections: section tabs and the account/date filters stay pinned,
        # the KPI cards and statement rows scroll beneath them.
        sticky_header = ft.Container(
            ft.Column(
                [
                    self._section_nav(active),
                    ft.ResponsiveRow(
                        [
                            ft.Container(party_dd, col={"xs": 12, "md": 6}),
                            ft.Container(date_from, col={"xs": 6, "md": 3}),
                            ft.Container(date_to, col={"xs": 6, "md": 3}),
                        ]
                    ),
                    ft.Row([ft.FilledButton("عرض الكشف", icon=ft.Icons.SEARCH, on_click=render), export_actions], wrap=True),
                ],
                spacing=10,
            ),
            padding=ft.padding.only(left=16, right=16, top=14, bottom=12),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
            shadow=Shadow.SM,
        )
        scroll_body = ft.Container(
            ft.Column([result, ft.Container(height=24)], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True),
            expand=True,
            padding=ft.padding.only(top=12, left=16, right=16),
        )
        self.content.content = ft.Column([sticky_header, scroll_body], spacing=0, expand=True)
        self.page.update()
