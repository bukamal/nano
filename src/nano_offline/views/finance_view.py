from __future__ import annotations

from datetime import date

import flet as ft

from nano_offline.components import SearchSelect


# Compatibility terminology: «سند دفع» هو نفسه «سند صرف» في الإصدارات السابقة.

class FinanceCenter:
    def __init__(self, page: ft.Page, ctx, content: ft.Container, on_changed=None, native_files=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_changed = on_changed
        self.native_files = native_files

    @staticmethod
    def money(value) -> str:
        return f"{float(value or 0):,.2f}"

    def notify(self, text: str) -> None:
        self.page.open(ft.SnackBar(ft.Text(text)))

    def _changed(self) -> None:
        if self.on_changed:
            self.on_changed()

    def _section_nav(self, active: str) -> ft.Row:
        items = [
            ("vouchers", "السندات", self.show_vouchers),
            ("expenses", "المصروفات", self.show_expenses),
            ("customers", "كشف العملاء", lambda: self.show_statements("customer")),
            ("suppliers", "كشف الموردين", lambda: self.show_statements("supplier")),
        ]
        controls = []
        for key, label, action in items:
            cls = ft.FilledButton if key == active else ft.OutlinedButton
            controls.append(cls(label, on_click=lambda _, fn=action: fn()))
        return ft.Row(controls, wrap=True)

    def show_center(self) -> None:
        self.show_vouchers()

    def show_vouchers(self) -> None:
        search = ft.TextField(label="بحث في السندات", hint_text="رقم السند، الحساب أو المرجع", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=9)
        summary = ft.ResponsiveRow(spacing=8, run_spacing=8)
        filter_state = {"type": "all"}
        filter_boxes: dict[str, ft.Container] = {}

        def metric(label: str, value: str, icon, accent: str):
            return ft.Container(
                ft.Row([
                    ft.Container(ft.Icon(icon, size=19, color=accent), width=38, height=38, alignment=ft.alignment.center, bgcolor="#F8FAFC", border_radius=12),
                    ft.Column([ft.Text(label, size=10, color="#64748B"), ft.Text(value, size=17, weight=ft.FontWeight.BOLD)], spacing=1, expand=True),
                ]),
                padding=11, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=16,
            )

        def filter_box(key: str, label: str, icon):
            box = ft.Container(
                ft.Row([ft.Icon(icon, size=15), ft.Text(label, size=11, weight=ft.FontWeight.W_600)], spacing=5),
                padding=ft.padding.symmetric(horizontal=11, vertical=8), border_radius=20,
                border=ft.border.all(1, "#E2E8F0"), ink=True,
                on_click=lambda _, k=key: set_filter(k),
            )
            filter_boxes[key] = box
            return box

        def update_filter_styles():
            for key, box in filter_boxes.items():
                selected = key == filter_state["type"]
                box.bgcolor = "#0B63F6" if selected else "#FFFFFF"
                box.border = ft.border.all(1, "#0B63F6" if selected else "#E2E8F0")
                row = box.content
                if isinstance(row, ft.Row):
                    for ctrl in row.controls:
                        if isinstance(ctrl, ft.Text): ctrl.color = "#FFFFFF" if selected else "#475569"
                        elif isinstance(ctrl, ft.Icon): ctrl.color = "#FFFFFF" if selected else "#64748B"

        def set_filter(key: str):
            filter_state["type"] = key
            update_filter_styles(); refresh()

        def refresh(_=None):
            vouchers = self.ctx.payments.list_vouchers()
            receipts = sum(float(v.get("amount") or 0) for v in vouchers if v.get("voucher_type") == "receipt")
            payments = sum(float(v.get("amount") or 0) for v in vouchers if v.get("voucher_type") == "payment")
            unallocated_total = sum(float(v.get("unallocated_amount") or 0) for v in vouchers)
            summary.controls = [
                ft.Container(metric("إجمالي القبض", self.money(receipts), ft.Icons.ADD_CARD, "#16A34A"), col={"xs": 6, "md": 4}),
                ft.Container(metric("إجمالي الدفع", self.money(payments), ft.Icons.PAYMENTS_OUTLINED, "#EF4444"), col={"xs": 6, "md": 4}),
                ft.Container(metric("رصيد غير موزع", self.money(unallocated_total), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, "#0B63F6"), col={"xs": 12, "md": 4}),
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
                accent = "#16A34A" if receipt else "#DC2626"
                allocated = float(voucher.get("allocated_amount") or 0)
                unallocated = float(voucher.get("unallocated_amount") or 0)
                rows.controls.append(
                    ft.Container(
                        ft.Row([
                            ft.Container(ft.Icon(ft.Icons.SOUTH_WEST if receipt else ft.Icons.NORTH_EAST, size=18, color=accent), width=44, height=44, alignment=ft.alignment.center, bgcolor="#ECFDF5" if receipt else "#FEF2F2", border_radius=14),
                            ft.Column([
                                ft.Text(f"{title} #{voucher['id']}", size=13, weight=ft.FontWeight.BOLD),
                                ft.Text(f"{voucher.get('party_name') or '—'} • {voucher.get('voucher_date') or '—'}", size=10, color="#64748B"),
                                ft.Text(f"موزع {self.money(allocated)}" + (f" • على الحساب {self.money(unallocated)}" if unallocated else ""), size=9, color="#64748B"),
                            ], spacing=2, expand=True),
                            ft.Column([
                                ft.Text(self.money(voucher.get("amount")), size=15, weight=ft.FontWeight.BOLD, color=accent),
                                ft.Text(voucher.get("reference") or "بدون مرجع", size=9, color="#94A3B8", max_lines=1),
                            ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                            ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color="#94A3B8"),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=12, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=16,
                        on_click=lambda _, vid=int(voucher["id"]): self.show_voucher_detail(vid), ink=True,
                    )
                )
            if not rows.controls:
                rows.controls.append(ft.Container(ft.Column([ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, size=46, color="#CBD5E1"), ft.Text("لا توجد سندات مطابقة", color="#64748B")], horizontal_alignment=ft.CrossAxisAlignment.CENTER), alignment=ft.alignment.center, padding=30))
            update_filter_styles(); self.page.update()

        search.on_change = refresh
        filters = ft.Row([
            filter_box("all", "الكل", ft.Icons.APPS_ROUNDED),
            filter_box("receipt", "قبض", ft.Icons.ADD_CARD),
            filter_box("payment", "دفع", ft.Icons.PAYMENTS_OUTLINED),
        ], wrap=True, spacing=6)
        self.content.content = ft.Column([
            self._section_nav("vouchers"),
            summary,
            ft.ResponsiveRow([
                ft.Container(ft.FilledButton("سند قبض", icon=ft.Icons.ADD_CARD, on_click=lambda _: self.show_voucher_dialog(None, "receipt")), col={"xs": 4, "md": 3}),
                ft.Container(ft.OutlinedButton("سند دفع", icon=ft.Icons.PAYMENTS_OUTLINED, on_click=lambda _: self.show_voucher_dialog(None, "payment")), col={"xs": 4, "md": 3}),
                ft.Container(ft.OutlinedButton("سند مصروف", icon=ft.Icons.RECEIPT_OUTLINED, on_click=lambda _: self.show_expense_dialog()), col={"xs": 4, "md": 3}),
            ], spacing=7, run_spacing=7),
            search, filters, rows,
        ], spacing=12, scroll=ft.ScrollMode.AUTO)
        refresh()

    def _voucher_html(self, voucher: dict) -> str:
        receipt = voucher.get("voucher_type") == "receipt"
        title = "سند قبض" if receipt else "سند دفع"
        accent = "#059669" if receipt else "#dc2626"
        party_label = "العميل" if receipt else "المورد"
        return f"""<!doctype html><html dir='rtl' lang='ar'><head><meta charset='utf-8'><style>
        @page {{ size:80mm auto; margin:0; }} * {{ box-sizing:border-box; }} body {{ width:80mm; margin:0; padding:5mm; font-family:Arial,sans-serif; color:#111; }}
        .brand {{ text-align:center; color:#0B63F6; font-size:20px; font-weight:800; }} .sub {{ text-align:center; font-size:10px; color:#64748B; }}
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
        accent = "#16A34A" if receipt else "#DC2626"
        allocations = voucher.get("allocations") or []
        alloc_controls = []
        for a in allocations:
            alloc_controls.append(ft.Container(ft.Row([ft.Text(f"فاتورة #{a['invoice_id']}", size=11, expand=True), ft.Text(self.money(a.get("amount")), size=11, weight=ft.FontWeight.BOLD)]), padding=7, bgcolor="#F8FAFC", border_radius=10))
        if not alloc_controls:
            alloc_controls.append(ft.Text("لا توجد توزيعات على فواتير", size=10, color="#64748B"))
        dialog = ft.AlertDialog(modal=True)

        def close(_=None): self.page.close(dialog)
        def edit(_=None): close(); self.show_voucher_dialog(voucher_id)
        def duplicate(_=None):
            close(); self.show_voucher_dialog(None, voucher.get("voucher_type") or "receipt", initial_data=voucher)
        async def print_voucher(_=None):
            if self.native_files is None:
                self.notify("الطباعة الأصلية غير مهيأة في هذا البناء"); return
            try:
                await self.native_files.print_html(self._voucher_html(voucher), name=f"nano-voucher-{voucher_id}")
            except Exception as exc:
                self.notify(str(exc))

        dialog.title = ft.Text(f"{title} #{voucher_id}")
        dialog.content = ft.Container(ft.Column([
            ft.Container(ft.Column([ft.Text(self.money(voucher.get("amount")), size=28, weight=ft.FontWeight.BOLD, color=accent), ft.Text(title, size=11, color="#64748B")], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2), padding=14, bgcolor="#F8FAFC", border_radius=16),
            ft.ResponsiveRow([
                ft.Container(ft.Text(f"التاريخ: {voucher.get('voucher_date') or '—'}", size=11), col={"xs": 6}),
                ft.Container(ft.Text(f"الحساب: {voucher.get('party_name') or '—'}", size=11), col={"xs": 6}),
                ft.Container(ft.Text(f"المرجع: {voucher.get('reference') or '—'}", size=11), col={"xs": 6}),
                ft.Container(ft.Text(f"على الحساب: {self.money(voucher.get('unallocated_amount'))}", size=11), col={"xs": 6}),
            ]),
            ft.Text(voucher.get("notes") or "بدون ملاحظات", size=10, color="#64748B"),
            ft.Divider(height=8), ft.Text("التوزيعات", size=13, weight=ft.FontWeight.BOLD), ft.Column(alloc_controls, spacing=5),
        ], spacing=8, scroll=ft.ScrollMode.AUTO), width=620, height=430)
        dialog.actions = [
            ft.TextButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _: (close(), self.confirm_delete_voucher(voucher_id))),
            ft.TextButton("تكرار", icon=ft.Icons.CONTENT_COPY, on_click=duplicate),
            ft.OutlinedButton("طباعة 80mm", icon=ft.Icons.PRINT_OUTLINED, on_click=print_voucher),
            ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=edit),
            ft.FilledButton("إغلاق", on_click=close),
        ]
        self.page.open(dialog)

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
        amount = ft.TextField(label="المبلغ", value=str(seed.get("amount", 0)), keyboard_type=ft.KeyboardType.NUMBER)
        vdate = ft.TextField(label="التاريخ", value=str(seed.get("voucher_date") or date.today().isoformat()))
        reference = ft.TextField(label="المرجع", value=seed.get("reference") or "")
        notes = ft.TextField(label="ملاحظات", value=seed.get("notes") or "", multiline=True, min_lines=1, max_lines=3)
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
                manual_column.controls.append(ft.Text("اختر الحساب أولًا لعرض الفواتير المفتوحة.", size=12, color="#64748B"))
                self.page.update()
                return
            exclude_payment_id = int(existing["payment_id"]) if existing and existing.get("payment_id") else None
            invoices = self.ctx.payments.allocatable_invoices(
                party_type(), int(party_dd.value), exclude_payment_id=exclude_payment_id
            )
            if not invoices:
                manual_column.controls.append(ft.Text("لا توجد فواتير قابلة للتوزيع.", size=12, color="#64748B"))
            for inv in invoices:
                iid = int(inv["id"])
                field = ft.TextField(
                    label=f"توزيع على فاتورة #{iid}",
                    value=str(existing_allocations.get(iid, 0)),
                    keyboard_type=ft.KeyboardType.NUMBER,
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
                                        ft.Text(f"{inv['invoice_date']} • المتاح للتوزيع {self.money(inv['allocatable_amount'])}", size=11, color="#64748B"),
                                    ],
                                    expand=True,
                                    spacing=2,
                                ),
                                field,
                            ],
                            wrap=True,
                        ),
                        padding=8,
                        border=ft.border.all(1, "#E5E7EB"),
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

        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def save(_):
            try:
                amount_value = float(amount.value or 0)
                pid = int(party_dd.value) if party_dd.value else None
                kwargs = {
                    "voucher_type": type_dd.value,
                    "amount": amount_value,
                    "voucher_date": vdate.value,
                    "reference": reference.value,
                    "notes": notes.value,
                    "allocation_mode": allocation_mode.value,
                    "allocations": {iid: float(field.value or 0) for iid, field in manual_fields.items()} if allocation_mode.value == "manual" else None,
                    "customer_id": pid if type_dd.value == "receipt" else None,
                    "supplier_id": pid if type_dd.value == "payment" else None,
                }
                if voucher_id:
                    self.ctx.payments.update_voucher(voucher_id, **kwargs)
                    message = f"تم تعديل السند #{voucher_id}"
                else:
                    new_id = self.ctx.payments.create_voucher(**kwargs)
                    message = f"تم حفظ السند #{new_id}"
                self.page.close(dialog)
                self.notify(message)
                self.show_vouchers()
                self._changed()
            except Exception as exc:
                self.notify(str(exc))

        dialog.title = ft.Text("تعديل سند" if voucher_id else "سند جديد")
        dialog.content = ft.Container(
            ft.Column(
                [
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
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=700,
        )
        dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حفظ", icon=ft.Icons.SAVE_OUTLINED, on_click=save)]
        self.page.open(dialog)
        refresh_manual()

    def confirm_delete_voucher(self, voucher_id: int) -> None:
        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def delete(_):
            try:
                self.ctx.payments.delete_voucher(voucher_id)
                self.page.close(dialog)
                self.notify("تم حذف السند وعكس أثره المالي")
                self.show_vouchers()
                self._changed()
            except Exception as exc:
                self.page.close(dialog)
                self.notify(str(exc))

        dialog.title = ft.Text("حذف السند")
        dialog.content = ft.Text("سيتم حذف السند وتوزيعاته وإعادة احتساب الذمم والفواتير. هل تريد المتابعة؟")
        dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حذف", icon=ft.Icons.DELETE_FOREVER, on_click=delete)]
        self.page.open(dialog)

    def show_expenses(self) -> None:
        search = ft.TextField(label="بحث في المصروفات", hint_text="البيان، التصنيف أو المرجع", prefix_icon=ft.Icons.SEARCH)
        rows = ft.Column(spacing=9)
        summary = ft.ResponsiveRow(spacing=8, run_spacing=8)

        def metric(label: str, value: str, icon, accent: str):
            return ft.Container(
                ft.Row([
                    ft.Container(ft.Icon(icon, size=19, color=accent), width=38, height=38, alignment=ft.alignment.center, bgcolor="#F8FAFC", border_radius=12),
                    ft.Column([ft.Text(label, size=10, color="#64748B"), ft.Text(value, size=17, weight=ft.FontWeight.BOLD)], spacing=1, expand=True),
                ]), padding=11, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=16,
            )

        def refresh(_=None):
            expenses = self.ctx.expenses.list_expenses()
            q = (search.value or "").strip().casefold()
            filtered = [e for e in expenses if not q or q in f"{e.get('description','')} {e.get('category_name','')} {e.get('reference','')}".casefold()]
            total = sum(float(e.get("amount") or 0) for e in expenses)
            categories = {str(e.get("category_name") or "بلا تصنيف") for e in expenses}
            current_month = date.today().isoformat()[:7]
            month_total = sum(float(e.get("amount") or 0) for e in expenses if str(e.get("expense_date") or "").startswith(current_month))
            summary.controls = [
                ft.Container(metric("إجمالي المصروفات", self.money(total), ft.Icons.PAYMENTS_OUTLINED, "#DC2626"), col={"xs": 6, "md": 4}),
                ft.Container(metric("هذا الشهر", self.money(month_total), ft.Icons.CALENDAR_MONTH_OUTLINED, "#EA580C"), col={"xs": 6, "md": 4}),
                ft.Container(metric("التصنيفات", str(len(categories)), ft.Icons.CATEGORY_OUTLINED, "#7C3AED"), col={"xs": 12, "md": 4}),
            ]
            rows.controls = []
            for exp in filtered:
                rows.controls.append(ft.Container(
                    ft.Row([
                        ft.Container(ft.Icon(ft.Icons.RECEIPT_OUTLINED, size=18, color="#EA580C"), width=44, height=44, alignment=ft.alignment.center, bgcolor="#FFF7ED", border_radius=14),
                        ft.Column([ft.Text(exp["description"], size=13, weight=ft.FontWeight.BOLD), ft.Text(f"{exp.get('category_name') or 'بلا تصنيف'} • {exp.get('expense_date') or '—'}", size=10, color="#64748B")], spacing=2, expand=True),
                        ft.Column([ft.Text(self.money(exp.get("amount")), size=15, weight=ft.FontWeight.BOLD, color="#DC2626"), ft.Text(exp.get("reference") or "بدون مرجع", size=9, color="#94A3B8")], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                        ft.PopupMenuButton(items=[
                            ft.PopupMenuItem(text="تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _, eid=int(exp["id"]): self.show_expense_dialog(eid)),
                            ft.PopupMenuItem(text="حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _, eid=int(exp["id"]): self.confirm_delete_expense(eid)),
                        ]),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=12, bgcolor="#FFFFFF", border=ft.border.all(1, "#E2E8F0"), border_radius=16,
                ))
            if not rows.controls:
                rows.controls.append(ft.Container(ft.Column([ft.Icon(ft.Icons.RECEIPT_OUTLINED, size=46, color="#CBD5E1"), ft.Text("لا توجد مصروفات مطابقة", color="#64748B")], horizontal_alignment=ft.CrossAxisAlignment.CENTER), alignment=ft.alignment.center, padding=30))
            self.page.update()

        search.on_change = refresh
        self.content.content = ft.Column([
            self._section_nav("expenses"), summary,
            ft.Row([ft.FilledButton("سند مصروف", icon=ft.Icons.ADD, on_click=lambda _: self.show_expense_dialog())]),
            search, rows,
        ], spacing=12, scroll=ft.ScrollMode.AUTO)
        refresh()

    def show_expense_dialog(self, expense_id: int | None = None) -> None:
        existing = self.ctx.expenses.get_expense(expense_id) if expense_id else None
        categories = self.ctx.expenses.list_categories()
        category = SearchSelect(
            label="التصنيف",
            value=str(existing["category_id"]) if existing and existing.get("category_id") else None,
            choices=[(str(c["id"]), c["name"]) for c in categories],
        )
        new_category = ft.TextField(label="تصنيف جديد")
        description = ft.TextField(label="البيان", value=(existing["description"] if existing else ""))
        amount = ft.TextField(label="المبلغ", value=str(seed.get("amount", 0)), keyboard_type=ft.KeyboardType.NUMBER)
        edate = ft.TextField(label="التاريخ", value=str(existing["expense_date"] if existing else date.today().isoformat()))
        reference = ft.TextField(label="المرجع", value=seed.get("reference") or "")
        notes = ft.TextField(label="ملاحظات", value=(existing.get("notes") or "") if existing else "", multiline=True)
        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def save(_):
            try:
                category_id = int(category.value) if category.value else None
                if (new_category.value or "").strip():
                    category_id = self.ctx.expenses.create_category(new_category.value)
                kwargs = {
                    "amount": float(amount.value or 0),
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
                self.page.close(dialog)
                self.notify("تم حفظ المصروف")
                self.show_expenses()
                self._changed()
            except Exception as exc:
                self.notify(str(exc))

        dialog.title = ft.Text("تعديل مصروف" if expense_id else "مصروف جديد")
        dialog.content = ft.Container(
            ft.Column([category, new_category, description, ft.Row([amount, edate], wrap=True), reference, notes], scroll=ft.ScrollMode.AUTO),
            width=560,
        )
        dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حفظ", on_click=save)]
        self.page.open(dialog)

    def confirm_delete_expense(self, expense_id: int) -> None:
        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def delete(_):
            try:
                self.ctx.expenses.delete_expense(expense_id)
                self.page.close(dialog)
                self.notify("تم حذف المصروف")
                self.show_expenses()
                self._changed()
            except Exception as exc:
                self.page.close(dialog)
                self.notify(str(exc))

        dialog.title = ft.Text("حذف المصروف")
        dialog.content = ft.Text("سيتم حذف المصروف وعكس أثره على الصندوق والأرباح.")
        dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حذف", on_click=delete)]
        self.page.open(dialog)

    def show_statements(self, party_type: str) -> None:
        source = self.ctx.customers.list() if party_type == "customer" else self.ctx.suppliers.list()
        title = "كشف حساب العملاء" if party_type == "customer" else "كشف حساب الموردين"
        active = "customers" if party_type == "customer" else "suppliers"
        party_dd = SearchSelect(
            label="العميل" if party_type == "customer" else "المورد",
            choices=[(str(p["id"]), p["name"]) for p in source],
        )
        date_from = ft.TextField(label="من تاريخ", hint_text="YYYY-MM-DD")
        date_to = ft.TextField(label="إلى تاريخ", hint_text="YYYY-MM-DD")
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
                self.notify(str(exc))

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
                self.notify(str(exc))

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
                            ft.Container(self._metric("الرصيد الحالي", f"{self.money(abs(balance))} — {balance_label}"), col={"xs": 12, "md": 4}),
                            ft.Container(self._metric("الرصيد الافتتاحي للفترة", self.money(data["opening_balance"])), col={"xs": 6, "md": 4}),
                            ft.Container(self._metric("فواتير مفتوحة", str(len(data["open_invoices"]))), col={"xs": 6, "md": 4}),
                        ]
                    )
                )
                for row in data["rows"]:
                    movement = float(row["movement"])
                    movement_text = f"+{self.money(movement)}" if movement >= 0 else f"-{self.money(abs(movement))}"
                    result.controls.append(
                        ft.Container(
                            ft.Row(
                                [
                                    ft.Column(
                                        [
                                            ft.Text(row["description"] or row["source_label"], weight=ft.FontWeight.BOLD),
                                            ft.Text(f"{row['entry_date']} • {row['source_label']} #{row['source_id'] or '—'}", size=11, color="#64748B"),
                                        ],
                                        expand=True,
                                        spacing=2,
                                    ),
                                    ft.Column(
                                        [
                                            ft.Text(movement_text, weight=ft.FontWeight.BOLD),
                                            ft.Text(f"الرصيد {self.money(row['balance'])}", size=11, color="#64748B"),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.END,
                                    ),
                                ]
                            ),
                            padding=10,
                            border=ft.border.all(1, "#E5E7EB"),
                            border_radius=10,
                            bgcolor="#FFFFFF",
                        )
                    )
                if not data["rows"]:
                    result.controls.append(ft.Text("لا توجد حركات في الفترة المحددة.", color="#64748B"))
            except Exception as exc:
                export_actions.visible = False
                self.notify(str(exc))
            self.page.update()

        party_dd.on_change = render
        self.content.content = ft.Column(
            [
                ft.Text(title, size=24, weight=ft.FontWeight.BOLD),
                self._section_nav(active),
                ft.ResponsiveRow(
                    [
                        ft.Container(party_dd, col={"xs": 12, "md": 6}),
                        ft.Container(date_from, col={"xs": 6, "md": 3}),
                        ft.Container(date_to, col={"xs": 6, "md": 3}),
                    ]
                ),
                ft.Row([ft.FilledButton("عرض الكشف", icon=ft.Icons.SEARCH, on_click=render), export_actions], wrap=True),
                result,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def _metric(self, title: str, value: str) -> ft.Container:
        return ft.Container(
            ft.Column([ft.Text(title, size=11, color="#64748B"), ft.Text(value, size=17, weight=ft.FontWeight.BOLD)], spacing=3),
            padding=10,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=10,
            bgcolor="#FFFFFF",
        )
