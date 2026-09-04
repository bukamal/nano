from __future__ import annotations

from datetime import date

import flet as ft

from qeid_offline.services.invoice_service import InvoiceLineInput


STATUS_AR = {
    "paid": "مدفوعة",
    "partial": "مدفوعة جزئيًا",
    "unpaid": "غير مدفوعة",
}


class InvoiceCenter:
    """Responsive invoice center/editor for Flet 0.28.x."""

    def __init__(self, page: ft.Page, ctx, content: ft.Container, on_saved=None, native_files=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_saved = on_saved
        self.native_files = native_files
        self.invoice_type = "sale"
        self.editing_id: int | None = None
        self.lines: list[dict] = []

    @staticmethod
    def money(value: float) -> str:
        return f"{float(value or 0):,.2f}"

    def notify(self, text: str) -> None:
        snack = ft.SnackBar(ft.Text(text))
        self.page.open(snack)


    def _print_handler(self, invoice_id: int):
        async def handler(_):
            if self.native_files is None:
                self.notify("الطباعة الأصلية غير مهيأة في هذا البناء")
                return
            try:
                html = self.ctx.documents.invoice_html(invoice_id)
                await self.native_files.print_html(html, name=f"qeid-invoice-{invoice_id}")
            except Exception as exc:
                self.notify(str(exc))
        return handler

    def _pdf_handler(self, invoice_id: int):
        async def handler(_):
            if self.native_files is None:
                self.notify("تصدير PDF غير مهيأ في هذا البناء")
                return
            try:
                html = self.ctx.documents.invoice_html(invoice_id)
                await self.native_files.share_pdf(html, filename=f"qeid_invoice_{invoice_id}.pdf")
            except Exception as exc:
                self.notify(str(exc))
        return handler

    def show_center(self) -> None:
        invoices = self.ctx.invoices.list_invoices(limit=250)
        cards = ft.Column(spacing=8)
        for inv in invoices:
            kind = "بيع" if inv["type"] == "sale" else "شراء"
            party = inv.get("party_name") or "نقدي"
            remaining = max(0.0, float(inv["remaining_amount"] or 0))
            status = STATUS_AR.get(inv.get("payment_status"), inv.get("payment_status") or "")
            invoice_id = int(inv["id"])
            actions = [
                ft.OutlinedButton("طباعة", icon=ft.Icons.PRINT_OUTLINED, on_click=self._print_handler(invoice_id)),
                ft.OutlinedButton("PDF", icon=ft.Icons.PICTURE_AS_PDF_OUTLINED, on_click=self._pdf_handler(invoice_id)),
                ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=lambda e, iid=invoice_id: self.show_editor(iid)),
                ft.TextButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda e, iid=invoice_id: self.confirm_delete(iid)),
            ]
            has_party = bool(inv.get("customer_id") if inv["type"] == "sale" else inv.get("supplier_id"))
            if remaining > 1e-9 and has_party:
                actions.insert(0, ft.FilledButton("تسجيل دفعة", icon=ft.Icons.PAYMENTS_OUTLINED, on_click=lambda e, iid=invoice_id: self.show_payment_dialog(iid)))
            cards.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Column(
                                        [
                                            ft.Text(f"فاتورة {kind} #{invoice_id}", weight=ft.FontWeight.BOLD),
                                            ft.Text(f"{inv['invoice_date']} • {party}", size=12, color="#64748B"),
                                        ],
                                        spacing=2,
                                        expand=True,
                                    ),
                                    ft.Text(self.money(inv["total"]), size=18, weight=ft.FontWeight.BOLD),
                                ]
                            ),
                            ft.Row(
                                [
                                    ft.Text(f"المدفوع: {self.money(inv['paid_amount'])}", size=12),
                                    ft.Text(f"المتبقي: {self.money(remaining)}", size=12),
                                    ft.Text(status, size=12, color="#0A3F70"),
                                ],
                                wrap=True,
                            ),
                            ft.Row(actions, wrap=True),
                        ],
                        spacing=8,
                    ),
                    padding=12,
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=12,
                    bgcolor="#FFFFFF",
                )
            )

        if not cards.controls:
            cards.controls.append(
                ft.Container(
                    ft.Text("لا توجد فواتير بعد", color="#64748B"),
                    padding=24,
                    alignment=ft.alignment.center,
                )
            )

        self.content.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("الفواتير", size=24, weight=ft.FontWeight.BOLD, expand=True),
                        ft.FilledButton("بيع جديد", icon=ft.Icons.ADD_SHOPPING_CART, on_click=lambda _: self.show_editor(None, "sale")),
                        ft.OutlinedButton("شراء جديد", icon=ft.Icons.SHOPPING_BAG_OUTLINED, on_click=lambda _: self.show_editor(None, "purchase")),
                    ],
                    wrap=True,
                ),
                ft.Text("جميع الفواتير والحسابات والمخزون محفوظة محليًا في SQLite.", size=12, color="#64748B"),
                cards,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def show_payment_dialog(self, invoice_id: int) -> None:
        invoice = self.ctx.invoices.get_invoice(invoice_id)
        if not invoice:
            self.notify("الفاتورة غير موجودة")
            return
        remaining = max(0.0, float(invoice["remaining_amount"] or 0))
        if remaining <= 1e-9:
            self.notify("الفاتورة مسددة بالكامل")
            return

        amount = ft.TextField(label="المبلغ", value=str(remaining), keyboard_type=ft.KeyboardType.NUMBER)
        payment_date = ft.TextField(label="التاريخ", value=date.today().isoformat())
        reference = ft.TextField(label="المرجع")
        notes = ft.TextField(label="ملاحظات", multiline=True, min_lines=1, max_lines=3)
        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def save(_):
            try:
                voucher_id = self.ctx.payments.register_invoice_payment(
                    invoice_id,
                    float(amount.value or 0),
                    payment_date=payment_date.value,
                    reference=reference.value,
                    notes=notes.value,
                )
                self.page.close(dialog)
                self.notify(f"تم تسجيل الدفعة بسند #{voucher_id}")
                self.show_center()
                if self.on_saved:
                    self.on_saved()
            except Exception as exc:
                self.notify(str(exc))

        dialog.title = ft.Text(f"تسجيل دفعة — فاتورة #{invoice_id}")
        dialog.content = ft.Container(
            ft.Column(
                [
                    ft.Text(f"{invoice.get('party_name') or '—'} • المتبقي {self.money(remaining)}", color="#64748B"),
                    amount,
                    payment_date,
                    reference,
                    notes,
                ],
                tight=True,
            ),
            width=480,
        )
        dialog.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("تسجيل", icon=ft.Icons.PAYMENTS_OUTLINED, on_click=save)]
        self.page.open(dialog)

    def confirm_delete(self, invoice_id: int) -> None:
        invoice = self.ctx.invoices.get_invoice(invoice_id)
        if not invoice:
            self.notify("الفاتورة غير موجودة")
            return

        dialog = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dialog)

        def do_delete(_):
            try:
                self.ctx.invoices.delete_invoice(invoice_id)
                self.page.close(dialog)
                self.notify(f"تم حذف الفاتورة #{invoice_id} وعكس آثارها المحاسبية والمخزنية")
                self.show_center()
                if self.on_saved:
                    self.on_saved()
            except Exception as exc:
                self.page.close(dialog)
                self.notify(str(exc))

        dialog.title = ft.Text("تأكيد حذف الفاتورة")
        dialog.content = ft.Text(
            f"سيتم حذف الفاتورة #{invoice_id} وإعادة احتساب المخزون والأرصدة والتكلفة. لا يمكن التراجع عن العملية."
        )
        dialog.actions = [
            ft.TextButton("إلغاء", on_click=close),
            ft.FilledButton("حذف نهائي", icon=ft.Icons.DELETE_FOREVER, on_click=do_delete),
        ]
        self.page.open(dialog)

    def show_editor(self, invoice_id: int | None = None, invoice_type: str | None = None) -> None:
        existing = self.ctx.invoices.get_invoice(invoice_id) if invoice_id else None
        if invoice_id and not existing:
            self.notify("الفاتورة غير موجودة")
            return

        self.editing_id = invoice_id
        self.invoice_type = (existing["type"] if existing else invoice_type) or "sale"
        customers = self.ctx.customers.list()
        suppliers = self.ctx.suppliers.list()
        items = self.ctx.items.list()
        item_map = {int(i["id"]): i for i in items}

        type_dd = ft.Dropdown(
            label="نوع الفاتورة",
            value=self.invoice_type,
            options=[ft.dropdown.Option("sale", "بيع"), ft.dropdown.Option("purchase", "شراء")],
        )
        party_dd = ft.Dropdown(label="العميل", enable_search=True, enable_filter=True)
        invoice_date = ft.TextField(label="التاريخ", value=str(existing["invoice_date"] if existing else date.today().isoformat()))
        reference = ft.TextField(label="المرجع", value=(existing.get("reference") or "") if existing else "")
        notes = ft.TextField(label="ملاحظات", value=(existing.get("notes") or "") if existing else "", multiline=True, min_lines=1, max_lines=3)
        paid = ft.TextField(
            label="الدفعة الأولى",
            value=str(existing["initial_paid_amount"] if existing else 0),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        lines_column = ft.Column(spacing=8)
        total_text = ft.Text("0.00", size=20, weight=ft.FontWeight.BOLD)
        remaining_text = ft.Text("0.00", size=18, weight=ft.FontWeight.BOLD)

        def party_options() -> None:
            is_sale = type_dd.value == "sale"
            source = customers if is_sale else suppliers
            party_dd.label = "العميل" if is_sale else "المورد"
            party_dd.options = [ft.dropdown.Option(str(p["id"]), p["name"]) for p in source]
            if existing and existing["type"] == type_dd.value:
                pid = existing.get("customer_id") if is_sale else existing.get("supplier_id")
                party_dd.value = str(pid) if pid else None
            elif party_dd.value and not any(o.key == party_dd.value for o in party_dd.options):
                party_dd.value = None

        def parse_number(control, label: str, allow_zero: bool = True) -> float:
            try:
                value = float(control.value or 0)
            except Exception as exc:
                raise ValueError(f"{label} غير صحيح") from exc
            if value < 0 or (not allow_zero and value <= 0):
                raise ValueError(f"{label} غير صحيح")
            return value

        def recalc(_=None) -> None:
            total = 0.0
            for state in self.lines:
                try:
                    qty_value = float(state["qty"].value or 0)
                    price_value = float(state["price"].value or 0)
                    line_total = qty_value * price_value
                except Exception:
                    line_total = 0.0
                state["total"].value = self.money(line_total)
                total += line_total
            try:
                paid_value = float(paid.value or 0)
            except Exception:
                paid_value = 0.0
            total_text.value = self.money(total)
            remaining_text.value = self.money(max(0, total - paid_value))
            self.page.update()

        def update_line_units(state: dict, selected_unit_id: int | None = None) -> None:
            state["unit"].options = []
            state["unit"].value = None
            state["factor"] = 1.0
            if not state["item"].value:
                return
            item_id_value = int(state["item"].value)
            units = self.ctx.items.units(item_id_value)
            state["units"] = {int(u["id"]): u for u in units}
            state["unit"].options = [
                ft.dropdown.Option(str(u["id"]), f"{u['name']} × {self.money(u['conversion_factor'])}") for u in units
            ]
            chosen = selected_unit_id if selected_unit_id in state["units"] else None
            if chosen is None and units:
                chosen = int(units[0]["id"])
            if chosen is not None:
                state["unit"].value = str(chosen)
                state["factor"] = float(state["units"][chosen]["conversion_factor"])

        def item_changed(state: dict) -> None:
            if state["item"].value:
                item_row = item_map[int(state["item"].value)]
                state["description"].value = item_row["name"]
                state["base_price"] = float(item_row["selling_price"] if type_dd.value == "sale" else item_row["purchase_price"])
                update_line_units(state)
                state["price"].value = str(state["base_price"] * float(state.get("factor") or 1))
            recalc()

        def unit_changed(state: dict) -> None:
            if state["unit"].value:
                uid = int(state["unit"].value)
                unit_row = state.get("units", {}).get(uid)
                state["factor"] = float(unit_row["conversion_factor"]) if unit_row else 1.0
                if state.get("base_price") is not None:
                    state["price"].value = str(float(state["base_price"]) * state["factor"])
            recalc()

        def remove_line(state: dict) -> None:
            if len(self.lines) <= 1:
                self.notify("يجب أن تحتوي الفاتورة على بند واحد على الأقل")
                return
            self.lines.remove(state)
            lines_column.controls.remove(state["card"])
            recalc()

        def add_line(initial: dict | None = None) -> None:
            initial = initial or {}
            initial_item = item_map.get(int(initial["item_id"])) if initial.get("item_id") else None
            state: dict = {
                "factor": float(initial.get("conversion_factor") or 1),
                "units": {},
                "base_price": (
                    float(initial_item["selling_price"] if type_dd.value == "sale" else initial_item["purchase_price"])
                    if initial_item else None
                ),
            }
            item_dd = ft.Dropdown(
                label="المادة / الخدمة",
                options=[ft.dropdown.Option(str(i["id"]), i["name"]) for i in items],
                value=str(initial["item_id"]) if initial.get("item_id") else None,
                enable_search=True,
                enable_filter=True,
            )
            description = ft.TextField(label="البيان", value=initial.get("description") or "")
            unit_dd = ft.Dropdown(label="الوحدة")
            qty = ft.TextField(label="الكمية", value=str(initial.get("quantity") or 1), keyboard_type=ft.KeyboardType.NUMBER)
            price = ft.TextField(label="السعر", value=str(initial.get("unit_price") or 0), keyboard_type=ft.KeyboardType.NUMBER)
            line_total = ft.Text("0.00", weight=ft.FontWeight.BOLD)
            state.update({"item": item_dd, "description": description, "unit": unit_dd, "qty": qty, "price": price, "total": line_total})

            item_dd.on_change = lambda e: item_changed(state)
            unit_dd.on_change = lambda e: unit_changed(state)
            qty.on_change = recalc
            price.on_change = recalc
            card = ft.Container(
                content=ft.Column(
                    [
                        ft.ResponsiveRow(
                            [
                                ft.Container(item_dd, col={"xs": 12, "md": 4}),
                                ft.Container(description, col={"xs": 12, "md": 4}),
                                ft.Container(unit_dd, col={"xs": 12, "md": 4}),
                            ]
                        ),
                        ft.ResponsiveRow(
                            [
                                ft.Container(qty, col={"xs": 5, "md": 3}),
                                ft.Container(price, col={"xs": 5, "md": 3}),
                                ft.Container(
                                    ft.Column([ft.Text("الإجمالي", size=11, color="#64748B"), line_total], spacing=2),
                                    col={"xs": 8, "md": 3},
                                    padding=8,
                                ),
                                ft.Container(
                                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="حذف البند", on_click=lambda e: remove_line(state)),
                                    col={"xs": 4, "md": 3},
                                ),
                            ]
                        ),
                    ],
                    spacing=4,
                ),
                padding=10,
                border=ft.border.all(1, "#E5E7EB"),
                border_radius=12,
                bgcolor="#FFFFFF",
            )
            state["card"] = card
            self.lines.append(state)
            lines_column.controls.append(card)
            if initial.get("item_id"):
                update_line_units(state, int(initial["unit_id"]) if initial.get("unit_id") else None)
            recalc()

        self.lines = []
        party_options()
        if existing:
            for line in existing["lines"]:
                add_line(line)
        else:
            add_line()

        def type_changed(_):
            self.invoice_type = type_dd.value or "sale"
            party_options()
            # Prices are invoice-type dependent; refresh selected rows.
            for state in self.lines:
                if state["item"].value:
                    item_row = item_map[int(state["item"].value)]
                    state["base_price"] = float(item_row["selling_price"] if type_dd.value == "sale" else item_row["purchase_price"])
                    state["price"].value = str(state["base_price"] * float(state.get("factor") or 1))
            recalc()

        type_dd.on_change = type_changed
        paid.on_change = recalc

        def save(_):
            try:
                inputs: list[InvoiceLineInput] = []
                for idx, state in enumerate(self.lines, start=1):
                    item_id_value = int(state["item"].value) if state["item"].value else None
                    unit_id_value = int(state["unit"].value) if state["unit"].value else None
                    inputs.append(
                        InvoiceLineInput(
                            description=(state["description"].value or "").strip(),
                            item_id=item_id_value,
                            unit_id=unit_id_value,
                            conversion_factor=float(state.get("factor") or 1),
                            quantity=parse_number(state["qty"], f"كمية البند {idx}", allow_zero=False),
                            unit_price=parse_number(state["price"], f"سعر البند {idx}"),
                        )
                    )
                paid_value = parse_number(paid, "المبلغ المدفوع")
                common = dict(
                    invoice_type=type_dd.value or "sale",
                    lines=inputs,
                    customer_id=int(party_dd.value) if (type_dd.value == "sale" and party_dd.value) else None,
                    supplier_id=int(party_dd.value) if (type_dd.value == "purchase" and party_dd.value) else None,
                    invoice_date=(invoice_date.value or "").strip(),
                    reference=reference.value,
                    notes=notes.value,
                    paid_amount=paid_value,
                )
                if self.editing_id:
                    self.ctx.invoices.update_invoice(self.editing_id, **common)
                    saved_id = self.editing_id
                    message = f"تم تعديل الفاتورة #{saved_id} وإعادة احتساب المخزون والأرصدة"
                else:
                    saved_id = self.ctx.invoices.create_invoice(**common)
                    message = f"تم حفظ الفاتورة #{saved_id}"
                self.notify(message)
                self.show_center()
                if self.on_saved:
                    self.on_saved()
            except Exception as exc:
                self.notify(str(exc))

        self.content.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.IconButton(icon=ft.Icons.ARROW_FORWARD, tooltip="رجوع", on_click=lambda _: self.show_center()),
                        ft.Text(
                            f"تعديل فاتورة #{self.editing_id}" if self.editing_id else "فاتورة جديدة",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            expand=True,
                        ),
                    ]
                ),
                ft.ResponsiveRow(
                    [
                        ft.Container(type_dd, col={"xs": 12, "md": 3}),
                        ft.Container(party_dd, col={"xs": 12, "md": 4}),
                        ft.Container(invoice_date, col={"xs": 6, "md": 2}),
                        ft.Container(reference, col={"xs": 6, "md": 3}),
                    ]
                ),
                ft.Row(
                    [
                        ft.Text("بنود الفاتورة", size=18, weight=ft.FontWeight.BOLD, expand=True),
                        ft.OutlinedButton("إضافة بند", icon=ft.Icons.ADD, on_click=lambda _: add_line()),
                    ]
                ),
                lines_column,
                ft.ResponsiveRow(
                    [
                        ft.Container(paid, col={"xs": 12, "md": 4}),
                        ft.Container(
                            ft.Column([ft.Text("إجمالي الفاتورة", size=12, color="#64748B"), total_text], spacing=3),
                            col={"xs": 6, "md": 4},
                            padding=10,
                        ),
                        ft.Container(
                            ft.Column([ft.Text("المتبقي", size=12, color="#64748B"), remaining_text], spacing=3),
                            col={"xs": 6, "md": 4},
                            padding=10,
                        ),
                    ]
                ),
                notes,
                ft.FilledButton("حفظ التعديلات" if self.editing_id else "حفظ الفاتورة", icon=ft.Icons.SAVE_OUTLINED, on_click=save),
                ft.Text(
                    "عند تعديل أو حذف فاتورة تاريخية يعاد احتساب التكلفة المتوسطة، تكلفة المبيعات، المخزون والذمم داخل Transaction واحدة.",
                    size=11,
                    color="#64748B",
                ),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        recalc()
