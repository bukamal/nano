from __future__ import annotations

from datetime import date

import flet as ft

from nano_offline.components import SearchSelect


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
        rows = ft.Column(spacing=8)
        for voucher in self.ctx.payments.list_vouchers():
            is_receipt = voucher["voucher_type"] == "receipt"
            title = "سند قبض" if is_receipt else "سند صرف"
            allocated = float(voucher["allocated_amount"] or 0)
            unallocated = float(voucher["unallocated_amount"] or 0)
            rows.controls.append(
                ft.Container(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Column(
                                        [
                                            ft.Text(f"{title} #{voucher['id']}", weight=ft.FontWeight.BOLD),
                                            ft.Text(f"{voucher['voucher_date']} • {voucher['party_name']}", size=12, color="#64748B"),
                                        ],
                                        spacing=2,
                                        expand=True,
                                    ),
                                    ft.Text(self.money(voucher["amount"]), size=18, weight=ft.FontWeight.BOLD),
                                ]
                            ),
                            ft.Row(
                                [
                                    ft.Text(f"موزع: {self.money(allocated)}", size=12),
                                    ft.Text(f"رصيد على الحساب: {self.money(unallocated)}", size=12, color="#0A3F70" if unallocated else "#64748B"),
                                ],
                                wrap=True,
                            ),
                            ft.Row(
                                [
                                    ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _, vid=int(voucher["id"]): self.show_voucher_dialog(vid)),
                                    ft.TextButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _, vid=int(voucher["id"]): self.confirm_delete_voucher(vid)),
                                ]
                            ),
                        ],
                        spacing=7,
                    ),
                    padding=12,
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=12,
                    bgcolor="#FFFFFF",
                )
            )
        if not rows.controls:
            rows.controls.append(ft.Container(ft.Text("لا توجد سندات بعد", color="#64748B"), padding=24))

        self.content.content = ft.Column(
            [
                ft.Text("الحركة المالية", size=24, weight=ft.FontWeight.BOLD),
                self._section_nav("vouchers"),
                ft.Row(
                    [
                        ft.FilledButton("سند قبض", icon=ft.Icons.ADD_CARD, on_click=lambda _: self.show_voucher_dialog(None, "receipt")),
                        ft.OutlinedButton("سند صرف", icon=ft.Icons.PAYMENTS_OUTLINED, on_click=lambda _: self.show_voucher_dialog(None, "payment")),
                    ],
                    wrap=True,
                ),
                ft.Text("يمكن توزيع السند آليًا على أقدم الفواتير، يدويًا على عدة فواتير، أو تركه رصيدًا على الحساب.", size=12, color="#64748B"),
                rows,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def show_voucher_dialog(self, voucher_id: int | None = None, voucher_type: str = "receipt") -> None:
        existing = self.ctx.payments.get_voucher(voucher_id) if voucher_id else None
        if voucher_id and not existing:
            self.notify("السند غير موجود")
            return

        current_type = existing["voucher_type"] if existing else voucher_type
        type_dd = SearchSelect(
            label="نوع السند",
            value=current_type,
            choices=[("receipt", "قبض من عميل"), ("payment", "صرف لمورد")],
            allow_clear=False,
        )
        party_dd = SearchSelect(label="الحساب")
        amount = ft.TextField(label="المبلغ", value=str(existing["amount"] if existing else 0), keyboard_type=ft.KeyboardType.NUMBER)
        vdate = ft.TextField(label="التاريخ", value=str(existing["voucher_date"] if existing else date.today().isoformat()))
        reference = ft.TextField(label="المرجع", value=(existing.get("reference") or "") if existing else "")
        notes = ft.TextField(label="ملاحظات", value=(existing.get("notes") or "") if existing else "", multiline=True, min_lines=1, max_lines=3)
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
            elif existing and existing["voucher_type"] == type_dd.value:
                pid = existing.get("customer_id") if type_dd.value == "receipt" else existing.get("supplier_id")
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
        rows = ft.Column(spacing=8)
        for exp in self.ctx.expenses.list_expenses():
            rows.controls.append(
                ft.Container(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Column(
                                        [
                                            ft.Text(exp["description"], weight=ft.FontWeight.BOLD),
                                            ft.Text(f"{exp['expense_date']} • {exp['category_name']}", size=12, color="#64748B"),
                                        ],
                                        expand=True,
                                        spacing=2,
                                    ),
                                    ft.Text(self.money(exp["amount"]), size=18, weight=ft.FontWeight.BOLD),
                                ]
                            ),
                            ft.Row(
                                [
                                    ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _, eid=int(exp["id"]): self.show_expense_dialog(eid)),
                                    ft.TextButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _, eid=int(exp["id"]): self.confirm_delete_expense(eid)),
                                ]
                            ),
                        ],
                        spacing=7,
                    ),
                    padding=12,
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=12,
                    bgcolor="#FFFFFF",
                )
            )
        if not rows.controls:
            rows.controls.append(ft.Container(ft.Text("لا توجد مصروفات بعد", color="#64748B"), padding=24))
        self.content.content = ft.Column(
            [
                ft.Text("المصروفات", size=24, weight=ft.FontWeight.BOLD),
                self._section_nav("expenses"),
                ft.FilledButton("إضافة مصروف", icon=ft.Icons.ADD, on_click=lambda _: self.show_expense_dialog()),
                rows,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

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
        amount = ft.TextField(label="المبلغ", value=str(existing["amount"] if existing else 0), keyboard_type=ft.KeyboardType.NUMBER)
        edate = ft.TextField(label="التاريخ", value=str(existing["expense_date"] if existing else date.today().isoformat()))
        reference = ft.TextField(label="المرجع", value=(existing.get("reference") or "") if existing else "")
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
