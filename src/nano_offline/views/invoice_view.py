from __future__ import annotations

import asyncio
from datetime import date, timedelta

import flet as ft

from nano_offline.core.toast import toast
from nano_offline.core.home_widget import refresh_home_widget

from nano_offline.components import (
    SearchSelect,
    SegmentedToggle,
    SegmentOption,
    SelectAllTextField,
    SmartAmountField,
    SmartDateField,
    empty_state,
    kpi_card,
    new_form_sheet,
    render_form_sheet,
    status_pill,
    money_text_from_str,
    labeled_money_from_str,
)

from nano_offline.services.invoice_service import InvoiceLineInput
from nano_offline.components.buttons import stepper_icon_button
from nano_offline.core.theme import Colors, Shadow
from nano_offline.core import currency
from nano_offline.core.price_fingerprint import check_purchase_price
from nano_offline.core import invoice_settings
from nano_offline.core import barcode_settings

# Below this remaining quantity a stock item is flagged on the invoice line
# as running low -- there is no per-item reorder-point column in the schema
# yet, so this is a fixed, conservative default rather than a per-item
# setting.
LOW_STOCK_THRESHOLD = 5.0


STATUS_AR = {
    "paid": "مدفوعة",
    "partial": "مدفوعة جزئيًا",
    "unpaid": "غير مدفوعة",
}


class InvoiceCenter:
    """Responsive invoice center/editor for Flet 0.28.x."""

    def __init__(self, page: ft.Page, ctx, content: ft.Container, on_saved=None, native_files=None, on_title_change=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_saved = on_saved
        self.native_files = native_files
        self.on_title_change = on_title_change
        self.invoice_type = "sale"
        self.editing_id: int | None = None
        self.lines: list[dict] = []

    def money(self, value: float) -> str:
        return currency.format_amount(value, self.ctx.settings)

    @staticmethod
    def _qty(value) -> str:
        """Plain (non-currency) number formatting -- quantities, unit ratios."""
        return f"{float(value or 0):,.2f}"

    def notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)


    def _print_handler(self, invoice_id: int):
        async def handler(_):
            if self.native_files is None:
                self.notify("الطباعة الأصلية غير مهيأة في هذا البناء")
                return
            self.notify("جارٍ تحضير الطباعة...")
            try:
                html = self.ctx.documents.invoice_html(invoice_id)
                await self.native_files.print_html(html, name=f"nano-invoice-{invoice_id}")
            except Exception as exc:
                self.notify(str(exc), kind="error")
        return handler

    def _pdf_handler(self, invoice_id: int):
        async def handler(_):
            if self.native_files is None:
                self.notify("تصدير PDF غير مهيأ في هذا البناء")
                return
            self.notify("جارٍ تجهيز ملف PDF...")
            try:
                html = self.ctx.documents.invoice_html(invoice_id)
                shared = await self.native_files.share_pdf(html, filename=f"nano_invoice_{invoice_id}.pdf")
                # share_pdf() returns False when the user simply dismissed the
                # native share sheet without picking an app -- without this,
                # that looked identical to "nothing happened" / "broken",
                # since neither an error nor any other feedback followed it.
                if not shared:
                    self.notify("تم إلغاء المشاركة")
            except Exception as exc:
                self.notify(str(exc), kind="error")
        return handler

    def _show_center_error(self, exc: Exception) -> None:
        """Render a recoverable error state instead of leaving a gray Flutter ErrorWidget."""
        if self.on_title_change:
            self.on_title_change("الفواتير", "تعذر تحميل شاشة الفواتير")
        message = str(exc).strip() or exc.__class__.__name__
        self.content.content = ft.Column(
            [
                ft.Text("الفواتير", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(
                    ft.Column(
                        [
                            ft.Icon(ft.Icons.ERROR_OUTLINE, size=42, color=Colors.DANGER_DARKER),
                            ft.Text("تعذر تحميل شاشة الفواتير", size=18, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "تم منع انهيار الواجهة. أعد المحاولة، وإذا تكرر الخطأ فاحتفظ بالتفاصيل التالية.",
                                size=12,
                                color=Colors.TEXT_SECONDARY,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.Text(message, size=11, color=Colors.DANGER_DARKER, selectable=True),
                            ft.FilledButton("إعادة المحاولة", icon=ft.Icons.REFRESH, on_click=lambda _: self.show_center()),
                        ],
                        spacing=10,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=20,
                    border=ft.border.all(1, Colors.DANGER_BORDER),
                    border_radius=14,
                    bgcolor=Colors.DANGER_BG,
                ),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def _bottom_sheet(self, *, icon: str, icon_color: str, icon_bg: str, title: str, subtitle: str, body: ft.Control) -> ft.BottomSheet:
        # Same modal shell used by SecurityCenter/LoginGate (drag handle,
        # rounded top corners, icon bubble + title/subtitle, LG shadow) --
        # kept identical so every "more options" surface in the app looks
        # like one system instead of a mix of AlertDialogs and sheets.
        sheet = ft.BottomSheet(content=ft.Container(), is_scroll_controlled=True, enable_drag=True, maintain_bottom_view_insets_padding=True)
        icon_bubble = ft.Container(ft.Icon(icon, color=icon_color, size=24), width=48, height=48, alignment=ft.alignment.center, bgcolor=icon_bg, border_radius=14)
        sheet.content = ft.Container(
            ft.Column(
                [
                    ft.Row([ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10)], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row(
                        [icon_bubble, ft.Column([ft.Text(title, size=18, weight=ft.FontWeight.BOLD), ft.Text(subtitle, size=11, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True)],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    body,
                ],
                spacing=16,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.padding.only(left=20, right=20, top=12, bottom=26),
            bgcolor=Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
            shadow=Shadow.LG,
        )
        self.page.open(sheet)
        return sheet

    def _sheet_action(self, *, icon: str, icon_color: str, icon_bg: str, label: str, sublabel: str, on_click) -> ft.Container:
        return ft.Container(
            ft.Row(
                [
                    ft.Container(ft.Icon(icon, color=icon_color, size=20), width=40, height=40, alignment=ft.alignment.center, bgcolor=icon_bg, border_radius=12),
                    ft.Column([ft.Text(label, size=14, weight=ft.FontWeight.W_600), ft.Text(sublabel, size=11, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=18, color=Colors.TEXT_FAINT),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=10),
            border_radius=12,
            ink=True,
            on_click=on_click,
        )

    def _invoice_more_dialog(self, invoice: dict) -> None:
        invoice_id = int(invoice["id"])
        sale = invoice.get("type") == "sale"
        party = invoice.get("party_name") or "نقدي"

        def close(_=None):
            self.page.close(sheet)

        async def do_print(_):
            close()
            # Same fix as the detail-sheet -> editor-sheet transition in
            # items_view.py: closing this BottomSheet and immediately
            # triggering more overlay activity (notify()'s SnackBar, here)
            # in the same synchronous tick races Flutter's dismiss
            # animation, so the SnackBar can silently never render. A short
            # yield lets the close animation finish first.
            await asyncio.sleep(0.1)
            await self._print_handler(invoice_id)(None)

        async def do_pdf(_):
            close()
            await asyncio.sleep(0.1)
            await self._pdf_handler(invoice_id)(None)

        def do_delete(_):
            close()
            self.confirm_delete(invoice_id)

        body = ft.Column(
            [
                self._sheet_action(icon=ft.Icons.PRINT_OUTLINED, icon_color=Colors.PRIMARY, icon_bg=Colors.PRIMARY_BG, label="طباعة", sublabel="طباعة الفاتورة مباشرة", on_click=do_print),
                self._sheet_action(icon=ft.Icons.DESCRIPTION_OUTLINED, icon_color=Colors.PRIMARY, icon_bg=Colors.PRIMARY_BG, label="مشاركة PDF", sublabel="تصدير الفاتورة كملف PDF", on_click=do_pdf),
                self._sheet_action(icon=ft.Icons.DELETE_OUTLINE, icon_color=Colors.DANGER, icon_bg=Colors.DANGER_BG, label="حذف الفاتورة", sublabel="حذف نهائي مع إعادة احتساب المخزون والأرصدة", on_click=do_delete),
            ],
            spacing=4,
        )
        sheet = self._bottom_sheet(
            icon=ft.Icons.RECEIPT_LONG_ROUNDED,
            icon_color=Colors.PRIMARY,
            icon_bg=Colors.PRIMARY_BG,
            title=f"فاتورة {'بيع' if sale else 'شراء'} #{invoice_id}",
            subtitle=party,
            body=body,
        )

    def show_invoice_detail(self, invoice_id: int) -> None:
        """Tap-to-open quick view for an invoice card -- same role as
        items_view.show_item_detail: a read-mostly bottom sheet (totals +
        line items) with print/PDF/edit reachable from a footer, so opening
        an invoice from the list no longer requires jumping straight into
        the full editor just to look at it.
        """
        invoice = self.ctx.invoices.get_invoice(invoice_id)
        if not invoice:
            self.notify("الفاتورة غير موجودة")
            return

        sale = invoice.get("type") == "sale"
        kind = "بيع" if sale else "شراء"
        party = invoice.get("party_name") or "نقدي"
        total = float(invoice.get("total") or 0)
        paid_amount = float(invoice.get("paid_amount") or 0)
        remaining = max(0.0, float(invoice.get("remaining_amount") or 0))
        status_key = invoice.get("payment_status") or ""
        status = STATUS_AR.get(status_key, status_key)
        status_bg = Colors.SUCCESS_BG if status_key == "paid" else Colors.WARNING_BG_ALT if status_key == "partial" else Colors.DANGER_BG
        status_fg = Colors.SUCCESS_DARKER if status_key == "paid" else Colors.ORANGE_DARK if status_key == "partial" else Colors.DANGER_DARKER
        accent = Colors.SUCCESS if sale else Colors.PURPLE
        accent_bg = Colors.SUCCESS_BG if sale else Colors.PURPLE_BG

        line_rows: list[ft.Control] = []
        for line in invoice.get("lines") or []:
            qty = float(line.get("quantity") or 0)
            unit_price = float(line.get("unit_price") or 0)
            line_total = float(line.get("total") or 0)
            unit = line.get("unit_abbreviation") or line.get("unit_name") or ""
            name = line.get("item_name") or line.get("description") or "—"
            line_rows.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(name, size=12, weight=ft.FontWeight.W_600),
                                    # Split qty/unit from unit_price so the currency
                                    # symbol keeps the same order as on list cards
                                    # (amount then symbol) instead of being reordered
                                    # by RTL/bidi inside an Arabic phrase.
                                    ft.Row(
                                        [
                                            ft.Text(f"{self._qty(qty)} {unit} × ", size=10, color=Colors.TEXT_SECONDARY),
                                            money_text_from_str(self.money(unit_price), size=10, color=Colors.TEXT_SECONDARY),
                                        ],
                                        spacing=0,
                                        tight=True,
                                    ),
                                ],
                                spacing=1, expand=True,
                            ),
                            money_text_from_str(self.money(line_total), size=12, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                    padding=8, bgcolor=Colors.BACKGROUND, border_radius=11,
                )
            )
        if not line_rows:
            line_rows = [ft.Text("لا توجد أسطر", size=11, color=Colors.TEXT_SECONDARY)]

        def close(_=None):
            self.page.close(sheet)

        async def edit(_=None):
            # Same close-then-yield-then-open fix used everywhere else in
            # this file/items_view -- closing this sheet and opening the
            # editor's sheet in the same tick can race Flutter's dismiss
            # animation and leave the editor invisible.
            close()
            await asyncio.sleep(0.1)
            self.show_editor(invoice_id)

        async def do_print(_):
            close()
            await asyncio.sleep(0.1)
            await self._print_handler(invoice_id)(None)

        async def do_pdf(_):
            close()
            await asyncio.sleep(0.1)
            await self._pdf_handler(invoice_id)(None)

        export_row = []
        if self.native_files is not None:
            export_row = [
                ft.OutlinedButton("طباعة", icon=ft.Icons.PRINT_OUTLINED, on_click=do_print, expand=True),
                ft.OutlinedButton("PDF", icon=ft.Icons.DESCRIPTION_OUTLINED, on_click=do_pdf, expand=True),
            ]

        body = ft.Column(
            [
                ft.Row([status_pill(status, status_fg, status_bg)], alignment=ft.MainAxisAlignment.START),
                ft.ResponsiveRow(
                    [
                        ft.Container(kpi_card("الإجمالي", self.money(total), ft.Icons.RECEIPT_LONG_OUTLINED, Colors.PRIMARY), col={"xs": 4}),
                        ft.Container(kpi_card("المدفوع", self.money(paid_amount), ft.Icons.CHECK_CIRCLE_OUTLINE, Colors.SUCCESS), col={"xs": 4}),
                        ft.Container(kpi_card("المتبقي", self.money(remaining), ft.Icons.SCHEDULE, Colors.ORANGE if remaining > 1e-9 else Colors.SUCCESS), col={"xs": 4}),
                    ],
                    spacing=7, run_spacing=7,
                ),
                ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                ft.Text("الأصناف", size=13, weight=ft.FontWeight.BOLD, color=Colors.TEXT_SECONDARY),
                ft.Column(line_rows, spacing=6),
                ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                ft.Column(
                    (
                        [ft.Row(export_row, spacing=10)] if export_row else []
                    ) + [
                        ft.Row(
                            [
                                ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=edit, expand=True),
                                ft.FilledButton("إغلاق", on_click=close, expand=True),
                            ],
                            spacing=10,
                        ),
                    ],
                    spacing=8,
                ),
            ],
            spacing=12,
        )

        sheet = self._bottom_sheet(
            icon=ft.Icons.TRENDING_UP if sale else ft.Icons.TRENDING_DOWN,
            icon_color=accent,
            icon_bg=accent_bg,
            title=f"فاتورة {kind} #{invoice_id}",
            subtitle=f"{party} • {invoice.get('invoice_date') or '—'}",
            body=body,
        )

    def show_center(self) -> None:
        """Reference-style invoice browser with mobile-safe cards and chip filters."""
        if self.on_title_change:
            self.on_title_change("الفواتير", "المبيعات والمشتريات وحالات السداد")
        try:
            invoices = self.ctx.invoices.list_invoices(limit=250)
            search = SelectAllTextField(
                label="بحث في الفواتير",
                hint_text="رقم الفاتورة، العميل، المورد أو المرجع",
                prefix_icon=ft.Icons.SEARCH,
                border_radius=16,
            )
            cards = ft.Column(spacing=10)
            filters = {"type": "all", "status": "all"}
            # Same reasoning as the items screen: build only a page of cards
            # at a time instead of all (up to 250) on every keystroke.
            render_limit = {"n": 60}
            type_row = ft.Row(spacing=6, wrap=True)
            status_row = ft.Row(spacing=6, wrap=True)

            outstanding = sum(max(0.0, float(i.get("remaining_amount") or 0)) for i in invoices)
            open_count = sum(1 for i in invoices if i.get("payment_status") != "paid")
            sales_total = sum(float(i.get("total") or 0) for i in invoices if i.get("type") == "sale")

            def days_since(invoice_date_str) -> int | None:
                if not invoice_date_str:
                    return None
                try:
                    return (date.today() - date.fromisoformat(str(invoice_date_str)[:10])).days
                except Exception:
                    return None

            overdue_threshold = invoice_settings.overdue_days(self.ctx.settings)
            overdue_invoices = [
                i for i in invoices
                if i.get("payment_status") != "paid"
                and (days_since(i.get("invoice_date")) or 0) > overdue_threshold
            ]
            overdue_total = sum(max(0.0, float(i.get("remaining_amount") or 0)) for i in overdue_invoices)

            def matches(inv: dict) -> bool:
                query = (search.value or "").strip().lower()
                if filters["type"] != "all" and inv.get("type") != filters["type"]:
                    return False
                if filters["status"] == "outstanding":
                    if inv.get("payment_status") not in {"unpaid", "partial"}:
                        return False
                elif filters["status"] != "all" and inv.get("payment_status") != filters["status"]:
                    return False
                if not query:
                    return True
                haystack = " ".join(
                    [
                        str(inv.get("id") or ""),
                        str(inv.get("party_name") or "نقدي"),
                        str(inv.get("reference") or ""),
                        str(inv.get("invoice_date") or ""),
                    ]
                ).lower()
                return query in haystack

            def invoice_card(inv: dict):
                invoice_id = int(inv["id"])
                sale = inv.get("type") == "sale"
                kind = "بيع" if sale else "شراء"
                party = inv.get("party_name") or "نقدي"
                total = float(inv.get("total") or 0)
                paid_amount = float(inv.get("paid_amount") or 0)
                remaining = max(0.0, float(inv.get("remaining_amount") or 0))
                status_key = inv.get("payment_status") or ""
                status = STATUS_AR.get(status_key, status_key)
                status_bg = Colors.SUCCESS_BG if status_key == "paid" else Colors.WARNING_BG_ALT if status_key == "partial" else Colors.DANGER_BG
                status_fg = Colors.SUCCESS_DARKER if status_key == "paid" else Colors.ORANGE_DARK if status_key == "partial" else Colors.DANGER_DARKER
                has_party = bool(inv.get("customer_id") if sale else inv.get("supplier_id"))
                # Same icon-badge-carries-the-accent language as the items
                # list card (accent lives in the round icon badge, not in a
                # separate border stripe) -- one card language app-wide.
                accent = Colors.SUCCESS if sale else Colors.PURPLE
                accent_bg = Colors.SUCCESS_BG if sale else Colors.PURPLE_BG
                overdue_days = days_since(inv.get("invoice_date")) if remaining > 1e-9 and status_key != "paid" else None
                is_overdue = bool(overdue_days and overdue_days > overdue_threshold)
                can_pay = remaining > 1e-9 and has_party

                # One prominent number instead of always showing three --
                # a fully-paid invoice showing "المدفوع/المتبقي" columns that
                # just restate the total/zero is pure visual noise. Mirrors
                # the items card's single "price + status" pairing.
                if status_key == "paid":
                    highlight_label, highlight_value, highlight_color = "الإجمالي", self.money(total), Colors.SUCCESS
                    secondary_control = ft.Text("مسددة بالكامل", size=10, color=Colors.TEXT_SECONDARY)
                else:
                    highlight_label, highlight_value, highlight_color = "المتبقي", self.money(remaining), (Colors.ORANGE if remaining > 1e-9 else Colors.SUCCESS)
                    secondary_parts: list[ft.Control] = [
                        ft.Text("من إجمالي ", size=10, color=Colors.TEXT_SECONDARY),
                        money_text_from_str(self.money(total), size=10, color=Colors.TEXT_SECONDARY),
                    ]
                    if paid_amount > 1e-9:
                        secondary_parts.extend([
                            ft.Text(" • مدفوع ", size=10, color=Colors.TEXT_SECONDARY),
                            money_text_from_str(self.money(paid_amount), size=10, color=Colors.TEXT_SECONDARY),
                        ])
                    secondary_control = ft.Row(secondary_parts, spacing=0, tight=True)

                status_badges = [status_pill(status, status_fg, status_bg)]
                if is_overdue:
                    status_badges.append(status_pill(f"متأخرة {overdue_days} يوم", Colors.DANGER_DARKER, Colors.DANGER_BG))

                actions = []
                if can_pay:
                    actions.append(
                        ft.OutlinedButton(
                            "تسجيل دفعة", icon=ft.Icons.PAYMENTS_OUTLINED, expand=True,
                            on_click=lambda _, iid=invoice_id: self.show_payment_dialog(iid),
                        )
                    )

                body: list[ft.Control] = [
                    ft.Row(
                        [
                            ft.Container(ft.Icon(ft.Icons.TRENDING_UP if sale else ft.Icons.TRENDING_DOWN, color=accent, size=21), width=44, height=44, alignment=ft.alignment.center, bgcolor=accent_bg, border_radius=14),
                            ft.Column(
                                [
                                    ft.Row([ft.Text(f"فاتورة {kind} #{invoice_id}", weight=ft.FontWeight.BOLD, size=14, expand=True), *status_badges]),
                                    ft.Text(f"{party} • {inv.get('invoice_date') or '—'}", size=10, color=Colors.TEXT_SECONDARY),
                                ],
                                spacing=3, expand=True,
                            ),
                            ft.IconButton(icon=ft.Icons.MORE_VERT, tooltip="المزيد", icon_color=Colors.TEXT_SECONDARY, on_click=lambda _, row=inv: self._invoice_more_dialog(row)),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(highlight_label, size=9, color=Colors.TEXT_FAINT),
                                    money_text_from_str(
                                        highlight_value,
                                        size=17,
                                        weight=ft.FontWeight.BOLD,
                                        color=highlight_color,
                                    ),
                                ],
                                spacing=2,
                            ),
                            # secondary_line may embed money amounts; keep those
                            # LTR so the currency symbol matches list/item cards.
                            secondary_control,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                ]
                if actions:
                    body.append(ft.Row(actions, spacing=8))

                # Whole card is tappable now (like the items row) -- opens a
                # quick detail sheet instead of requiring a permanent "فتح"
                # button just to view the invoice. Buttons/kebab inside sit
                # on top and absorb their own tap, so they don't also
                # trigger this.
                card = ft.Container(
                    ft.Column(body, spacing=9),
                    padding=13, border=ft.border.all(1, Colors.BORDER), border_radius=16,
                    bgcolor=Colors.WHITE, shadow=Shadow.SM, ink=True,
                    on_click=lambda _, iid=invoice_id: self.show_invoice_detail(iid),
                )

                if not can_pay:
                    return card

                # Swipe = quick, non-destructive "تسجيل دفعة" shortcut on
                # outstanding invoices with a known party -- unlike the
                # items list, invoices never get a swipe-to-delete gesture
                # (too easy to trigger by accident on a financial record);
                # the only destructive action stays behind "المزيد" + a
                # confirm dialog. Refreshing right after re-renders this
                # same card in place (the payment doesn't remove it).
                def swipe_to_payment(_, iid=invoice_id):
                    self.show_payment_dialog(iid)
                    refresh_cards()

                payment_background = ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.PAYMENTS_OUTLINED, color=Colors.WHITE, size=22), ft.Text("تسجيل دفعة", color=Colors.WHITE, size=12, weight=ft.FontWeight.W_600)], spacing=6),
                    bgcolor=Colors.SUCCESS_DARK, border_radius=16, padding=ft.padding.symmetric(horizontal=20), alignment=ft.alignment.center_left,
                )
                payment_background_end = ft.Container(
                    content=ft.Row([ft.Text("تسجيل دفعة", color=Colors.WHITE, size=12, weight=ft.FontWeight.W_600), ft.Icon(ft.Icons.PAYMENTS_OUTLINED, color=Colors.WHITE, size=22)], spacing=6, alignment=ft.MainAxisAlignment.END),
                    bgcolor=Colors.SUCCESS_DARK, border_radius=16, padding=ft.padding.symmetric(horizontal=20), alignment=ft.alignment.center_right,
                )
                return ft.Dismissible(
                    key=f"invoice-{invoice_id}",
                    content=card,
                    dismiss_direction=ft.DismissDirection.HORIZONTAL,
                    background=payment_background,
                    secondary_background=payment_background_end,
                    on_dismiss=swipe_to_payment,
                )

            def refresh_cards(_=None):
                matched = [inv for inv in invoices if matches(inv)]
                cards.controls = [invoice_card(inv) for inv in matched[: render_limit["n"]]]
                if not cards.controls:
                    if invoices:
                        cards.controls = [empty_state(
                            "لا توجد فواتير مطابقة",
                            icon=ft.Icons.RECEIPT_LONG_OUTLINED,
                            hint="جرّب تغيير البحث أو عوامل التصفية",
                        )]
                    else:
                        cards.controls = [empty_state(
                            "لا توجد فواتير بعد",
                            icon=ft.Icons.RECEIPT_LONG_OUTLINED,
                            hint="أنشئ أول فاتورة بيع أو شراء",
                            action_label="بيع جديد",
                            on_action=lambda _: self.show_editor(None, "sale"),
                        )]
                elif len(matched) > render_limit["n"]:
                    remaining = len(matched) - render_limit["n"]

                    def load_more(_=None):
                        render_limit["n"] += 60
                        refresh_cards()

                    cards.controls.append(
                        ft.OutlinedButton(
                            f"تحميل المزيد ({remaining})",
                            icon=ft.Icons.EXPAND_MORE_ROUNDED,
                            on_click=load_more,
                        )
                    )
                self.page.update()

            def refresh_from_search(e=None):
                render_limit["n"] = 60
                refresh_cards()

            def chip(text: str, key: str, value: str, row: ft.Row):
                active = filters[key] == value
                return ft.Container(
                    ft.Text(text, size=11, color=Colors.WHITE if active else Colors.TEXT_MUTED, weight=ft.FontWeight.BOLD if active else ft.FontWeight.W_500),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    bgcolor=Colors.PRIMARY if active else Colors.WHITE,
                    border=ft.border.all(1, Colors.PRIMARY if active else Colors.BORDER),
                    border_radius=14,
                    on_click=lambda _: set_filter(key, value), ink=True,
                )

            def render_filters() -> None:
                type_row.controls = [chip("الكل", "type", "all", type_row), chip("مبيعات", "type", "sale", type_row), chip("مشتريات", "type", "purchase", type_row)]
                status_row.controls = [
                    chip("كل الحالات", "status", "all", status_row),
                    chip("المستحق", "status", "outstanding", status_row),
                    chip("غير مدفوعة", "status", "unpaid", status_row),
                    chip("جزئية", "status", "partial", status_row),
                    chip("مدفوعة", "status", "paid", status_row),
                ]

            def set_filter(key: str, value: str) -> None:
                filters[key] = value
                render_limit["n"] = 60
                render_filters()
                refresh_cards()

            search.on_change = refresh_from_search
            render_filters()
            refresh_cards()

            # --- Sticky header: search + filters stay put while the list
            # below scrolls, so they're never lost mid-scroll on a long
            # invoice list. ---
            sticky_header = ft.Container(
                ft.Column(
                    [
                        search,
                        ft.Column([ft.Text("النوع", size=10, color=Colors.TEXT_SECONDARY), type_row], spacing=4),
                        ft.Column([ft.Text("حالة السداد", size=10, color=Colors.TEXT_SECONDARY), status_row], spacing=4),
                    ],
                    spacing=10,
                ),
                padding=ft.padding.only(left=16, right=16, top=14, bottom=12),
                bgcolor=Colors.WHITE,
                border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
                shadow=Shadow.SM,
            )

            # --- Scrollable middle: KPI cards, overdue alert, invoice list. ---
            scroll_body = ft.Column(
                [
                    ft.ResponsiveRow(
                        [
                            ft.Container(
                                kpi_card("إجمالي المبيعات", self.money(sales_total), ft.Icons.TRENDING_UP, Colors.SUCCESS, on_tap=lambda _: set_filter("type", "sale")),
                                col={"xs": 6, "md": 4},
                            ),
                            ft.Container(
                                kpi_card("المستحق", self.money(outstanding), ft.Icons.SCHEDULE, Colors.ORANGE, on_tap=lambda _: set_filter("status", "outstanding")),
                                col={"xs": 6, "md": 4},
                            ),
                            ft.Container(
                                kpi_card("فواتير مفتوحة", str(open_count), ft.Icons.RECEIPT_LONG_OUTLINED, Colors.PRIMARY, on_tap=lambda _: set_filter("status", "outstanding")),
                                col={"xs": 12, "md": 4},
                            ),
                        ], spacing=8, run_spacing=8,
                    ),
                    ft.Container(
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.ERROR_OUTLINE, size=16, color=Colors.DANGER_DARKER),
                                ft.Row(
                                    [
                                        ft.Text(
                                            f"{len(overdue_invoices)} فاتورة متأخرة السداد أكثر من 30 يومًا بقيمة ",
                                            size=11, color=Colors.DANGER_DARKER,
                                        ),
                                        money_text_from_str(
                                            self.money(overdue_total),
                                            size=11, color=Colors.DANGER_DARKER,
                                        ),
                                    ],
                                    spacing=0,
                                    tight=True,
                                    expand=True,
                                ),
                            ],
                            spacing=8,
                        ),
                        padding=ft.padding.symmetric(horizontal=12, vertical=9),
                        bgcolor=Colors.DANGER_BG, border=ft.border.all(1, Colors.DANGER_BORDER), border_radius=12,
                        visible=bool(overdue_invoices),
                    ),
                    cards,
                    # Breathing room so the last card never sits directly
                    # under the floating action button.
                    ft.Container(height=84),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            )

            # --- Floating "new invoice" action: a single FAB that expands
            # into sale/purchase choices instead of two full-width buttons
            # competing with the list for space at the top. ---
            fab_state = {"open": False}

            def close_fab(_=None):
                if fab_state["open"]:
                    fab_state["open"] = False
                    render_fab()
                    self.page.update()

            def pick(kind: str):
                def handler(_):
                    close_fab()
                    self.show_editor(None, kind)
                return handler

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

            mini_purchase = mini_action("شراء جديد", ft.Icons.ADD_SHOPPING_CART, Colors.PURPLE, pick("purchase"))
            mini_sale = mini_action("بيع جديد", ft.Icons.SHOPPING_CART_CHECKOUT, Colors.SUCCESS, pick("sale"))
            main_fab = ft.Container(
                ft.Icon(ft.Icons.ADD_ROUNDED, color=Colors.WHITE, size=26),
                width=56, height=56, border_radius=28,
                bgcolor=Colors.PRIMARY, alignment=ft.alignment.center,
                shadow=Shadow.LG, ink=True, on_click=toggle_fab,
                rotate=ft.Rotate(0), animate_rotation=160,
            )
            fab_column = ft.Column(
                [mini_purchase, mini_sale, main_fab],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.END,
            )
            fab_container = ft.Container(
                fab_column,
                right=16, bottom=16,
                animate_opacity=160,
            )

            def render_fab() -> None:
                is_open = fab_state["open"]
                mini_purchase.visible = is_open
                mini_sale.visible = is_open
                mini_purchase.opacity = 1 if is_open else 0
                mini_sale.opacity = 1 if is_open else 0
                main_fab.rotate = ft.Rotate(0.125 * 6.283) if is_open else ft.Rotate(0)  # 45°
                scrim.visible = is_open

            render_fab()

            self.content.content = ft.Stack(
                [
                    ft.Column([sticky_header, scroll_body], spacing=0, expand=True),
                    scrim,
                    fab_container,
                ],
                expand=True,
            )
            self.page.update()
        except Exception as exc:
            self._show_center_error(exc)

    def show_payment_dialog(self, invoice_id: int) -> None:
        invoice = self.ctx.invoices.get_invoice(invoice_id)
        if not invoice:
            self.notify("الفاتورة غير موجودة")
            return
        remaining = max(0.0, float(invoice["remaining_amount"] or 0))
        if remaining <= 1e-9:
            self.notify("الفاتورة مسددة بالكامل")
            return

        amount = SmartAmountField(
            label=currency.amount_field_label("المبلغ", self.ctx.settings),
            value=currency.to_input_text(remaining, self.ctx.settings),
        )
        payment_date = SmartDateField(label="التاريخ", value=date.today().isoformat())
        reference = SelectAllTextField(label="المرجع")
        notes = SelectAllTextField(label="ملاحظات", multiline=True, min_lines=1, max_lines=3)
        sheet = new_form_sheet()

        def close(_=None):
            self.page.close(sheet)

        def save(_):
            try:
                voucher_id = self.ctx.payments.register_invoice_payment(
                    invoice_id,
                    currency.parse_display_input(amount.value, self.ctx.settings),
                    payment_date=payment_date.value,
                    reference=reference.value,
                    notes=notes.value,
                )
                close()
                self.notify(f"تم تسجيل الدفعة بسند #{voucher_id}", sound_kind="save")
                self.show_center()
                if self.on_saved:
                    self.on_saved()
            except Exception as exc:
                self.notify(str(exc), kind="error")

        render_form_sheet(
            self.page, sheet,
            title=f"تسجيل دفعة — فاتورة #{invoice_id}",
            fields=[
                ft.Row(
                    [
                        ft.Text(f"{invoice.get('party_name') or '—'} • المتبقي ", color=Colors.TEXT_SECONDARY),
                        money_text_from_str(self.money(remaining), color=Colors.TEXT_SECONDARY),
                    ],
                    spacing=0,
                    tight=True,
                ),
                amount, payment_date, reference, notes,
            ],
            on_close=close, on_save=save,
            save_label="تسجيل", save_icon=ft.Icons.PAYMENTS_OUTLINED,
        )
        self.page.open(sheet)

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
                self.notify(f"تم حذف الفاتورة #{invoice_id} وعكس آثارها المحاسبية والمخزنية", kind="success", sound_kind="delete")
                self.show_center()
                if self.on_saved:
                    self.on_saved()
            except Exception as exc:
                self.page.close(dialog)
                self.notify(str(exc), kind="error")

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
        if self.on_title_change:
            kind_label = "بيع" if self.invoice_type == "sale" else "شراء"
            self.on_title_change(
                f"تعديل فاتورة #{invoice_id}" if invoice_id else f"فاتورة {kind_label}",
                "إدارة بيانات الفاتورة والبنود والدفع" if invoice_id else f"إنشاء فاتورة {kind_label} جديدة — النقدي افتراضيًا",
            )
        customers = self.ctx.customers.list()
        suppliers = self.ctx.suppliers.list()
        items = self.ctx.items.list()
        item_map = {int(i["id"]): i for i in items}
        best_sellers = [i for i in self.ctx.items.pos_catalog(limit_best_sellers=10) if i.get("sold_qty")]

        type_dd = SegmentedToggle(
            options=[
                SegmentOption("sale", "بيع", ft.Icons.TRENDING_UP),
                SegmentOption("purchase", "شراء", ft.Icons.TRENDING_DOWN),
            ],
            value=self.invoice_type,
        )
        party_dd = SearchSelect(label="العميل")
        party_insight = ft.Container(visible=False)
        suggestions_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
        suggestions_mode = {"key": "best"}

        def mode_chip(text: str, key: str) -> ft.Container:
            active = suggestions_mode["key"] == key
            return ft.Container(
                ft.Text(text, size=10, color=Colors.WHITE if active else Colors.TEXT_MUTED, weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500),
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                bgcolor=Colors.PRIMARY if active else Colors.WHITE,
                border=ft.border.all(1, Colors.PRIMARY if active else Colors.BORDER),
                border_radius=12,
                ink=True,
                on_click=lambda _, k=key: set_suggestions_mode(k),
            )

        suggestions_mode_row = ft.Row(spacing=6)
        suggestions_column = ft.Column([suggestions_mode_row, suggestions_row], spacing=6, visible=False)
        invoice_date = SmartDateField(label="التاريخ", value=str(existing["invoice_date"] if existing else date.today().isoformat()))
        reference = SelectAllTextField(label="المرجع", value=(existing.get("reference") or "") if existing else "")
        notes = SelectAllTextField(label="ملاحظات", value=(existing.get("notes") or "") if existing else "", multiline=True, min_lines=1, max_lines=3)
        paid = SelectAllTextField(
            label=currency.amount_field_label("الدفعة الأولى", self.ctx.settings),
            value=currency.to_input_text(existing["initial_paid_amount"] if existing else 0, self.ctx.settings),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        lines_column = ft.Column(spacing=8)
        total_text = ft.Text("0.00", size=20, weight=ft.FontWeight.BOLD, text_direction=ft.TextDirection.LTR)
        remaining_text = ft.Text("0.00", size=18, weight=ft.FontWeight.BOLD, text_direction=ft.TextDirection.LTR)
        paid_progress = ft.ProgressBar(value=0, color=Colors.SUCCESS, bgcolor=Colors.BACKGROUND_ALT, height=6, border_radius=6)

        def party_options() -> None:
            is_sale = type_dd.value == "sale"
            source = customers if is_sale else suppliers
            party_dd.label = "العميل" if is_sale else "المورد"
            party_dd.set_choices([(str(p["id"]), p["name"]) for p in source])
            if existing and existing["type"] == type_dd.value:
                pid = existing.get("customer_id") if is_sale else existing.get("supplier_id")
                party_dd.value = str(pid) if pid else None
            elif party_dd.value and not any(str(p["id"]) == party_dd.value for p in source):
                party_dd.value = None

        def party_insight_text(is_sale: bool, party_id: int) -> str | None:
            repo = self.ctx.customers if is_sale else self.ctx.suppliers
            try:
                summary = repo.activity_summary(party_id)
            except Exception:
                return None
            count = int(summary.get("invoice_count") or 0)
            if count == 0:
                return None
            parts: list[str] = []
            last_date_obj: date | None = None
            last_date_str = summary.get("last_invoice_date")
            if last_date_str:
                try:
                    last_date_obj = date.fromisoformat(str(last_date_str)[:10])
                    days_since = (date.today() - last_date_obj).days
                    if days_since <= 0:
                        parts.append("آخر فاتورة اليوم")
                    elif days_since == 1:
                        parts.append("آخر فاتورة أمس")
                    else:
                        parts.append(f"آخر فاتورة قبل {days_since} يوم")
                except Exception:
                    last_date_obj = None
            recent_dates = sorted({
                r["invoice_date"] for r in (summary.get("recent_invoices") or []) if r.get("invoice_date")
            })
            if last_date_obj is not None and len(recent_dates) >= 2:
                try:
                    parsed = [date.fromisoformat(str(d)[:10]) for d in recent_dates]
                    intervals = [
                        (parsed[i + 1] - parsed[i]).days
                        for i in range(len(parsed) - 1)
                        if (parsed[i + 1] - parsed[i]).days > 0
                    ]
                    if intervals:
                        avg_days = round(sum(intervals) / len(intervals))
                        if avg_days >= 1:
                            next_expected = last_date_obj + timedelta(days=avg_days)
                            days_left = (next_expected - date.today()).days
                            if -2 <= days_left <= 3:
                                parts.append("اقترب موعد طلبه المعتاد")
                            elif days_left < -2:
                                parts.append("تجاوز موعد طلبه المعتاد")
                except Exception:
                    pass
            outstanding = float(summary.get("outstanding_total") or 0)
            if outstanding > 1e-9:
                parts.append(f"مستحق عليه {self.money(outstanding)}")
            return " • ".join(parts) if parts else None

        def _safe_update(control) -> None:
            # A control may not be attached to the page yet the first time
            # these run (e.g. the very first render before self.page.update()
            # has ever executed) -- same guard SegmentedToggle uses.
            try:
                control.update()
            except Exception:
                pass

        def update_party_insight() -> None:
            is_sale = type_dd.value == "sale"
            if not party_dd.value:
                party_insight.visible = False
                _safe_update(party_insight)
                return
            text = party_insight_text(is_sale, int(party_dd.value))
            if not text:
                party_insight.visible = False
                _safe_update(party_insight)
                return
            party_insight.content = ft.Row(
                [
                    ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, size=15, color=Colors.PRIMARY),
                    ft.Text(text, size=11, color=Colors.PRIMARY_DARK, expand=True),
                ],
                spacing=8,
            )
            party_insight.padding = ft.padding.symmetric(horizontal=10, vertical=8)
            party_insight.bgcolor = Colors.PRIMARY_BG
            party_insight.border = ft.border.all(1, Colors.PRIMARY_BORDER)
            party_insight.border_radius = 10
            party_insight.visible = True
            _safe_update(party_insight)

        def suggestion_chip(item_row: dict, sub_label: str) -> ft.Container:
            item_id = int(item_row["id"])
            return ft.Container(
                ft.Column(
                    [
                        ft.Text(item_row["name"], size=11, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY, max_lines=1),
                        ft.Text(sub_label, size=9, color=Colors.TEXT_SECONDARY),
                    ],
                    spacing=1, tight=True,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=7),
                bgcolor=Colors.WHITE,
                border=ft.border.all(1, Colors.BORDER),
                border_radius=12,
                ink=True,
                on_click=lambda _, iid=item_id: add_or_bump_item(iid),
                width=130,
            )

        def refresh_suggestions(_=None) -> None:
            is_sale = type_dd.value == "sale"
            source: list[dict] = []
            if suggestions_mode["key"] == "history" and party_dd.value:
                source = self.ctx.items.purchased_by_party(type_dd.value or "sale", int(party_dd.value), limit=10)
            if not source:
                suggestions_mode["key"] = "best"
                source = best_sellers
            chips = []
            for row in source[:10]:
                if suggestions_mode["key"] == "history":
                    sub = f"اشتُري {int(row.get('times_bought') or 1)} مرة"
                else:
                    sub = "الأكثر مبيعًا" if is_sale else "متوفر"
                chips.append(suggestion_chip(row, sub))
            suggestions_row.controls = chips
            mode_row_controls = [mode_chip("الأكثر مبيعًا", "best")]
            if party_dd.value:
                mode_row_controls.append(mode_chip("مشترياته السابقة", "history"))
            suggestions_mode_row.controls = mode_row_controls
            suggestions_column.visible = bool(chips)
            _safe_update(suggestions_column)

        def set_suggestions_mode(key: str) -> None:
            suggestions_mode["key"] = key
            refresh_suggestions()

        def parse_number(control, label: str, allow_zero: bool = True) -> float:
            try:
                value = float(control.value or 0)
            except Exception as exc:
                raise ValueError(f"{label} غير صحيح") from exc
            if value < 0 or (not allow_zero and value <= 0):
                raise ValueError(f"{label} غير صحيح")
            return value

        def parse_money(control, label: str, allow_zero: bool = True) -> float:
            """Like ``parse_number`` but the field holds a displayed-currency figure -- convert to USD for storage."""
            try:
                display_value = float((control.value or "0").replace(",", ""))
            except Exception as exc:
                raise ValueError(f"{label} غير صحيح") from exc
            if display_value < 0 or (not allow_zero and display_value <= 0):
                raise ValueError(f"{label} غير صحيح")
            return currency.parse_display_input(control.value, self.ctx.settings)

        def recalc(_=None) -> None:
            total = 0.0
            for state in self.lines:
                try:
                    qty_value = float(state["qty"].value or 0)
                    price_value = float(state["price"].value or 0)
                    line_total = qty_value * price_value
                except Exception:
                    line_total = 0.0
                state["total"].value = currency.format_plain(line_total)
                total += line_total

            # Anonymous invoices are cash by definition: if no customer/supplier
            # is selected, Nano settles the invoice in full automatically.
            cash_without_party = not bool(party_dd.value)
            paid.disabled = cash_without_party
            paid.label = "مدفوع نقدًا (تلقائي)" if cash_without_party else currency.amount_field_label("الدفعة الأولى", self.ctx.settings)
            if cash_without_party:
                paid.value = currency.format_plain(total)
                paid_value = total
            else:
                try:
                    paid_value = float(paid.value or 0)
                except Exception:
                    paid_value = 0.0
            total_text.value = currency.format_display_value(total, self.ctx.settings)
            remaining_text.value = currency.format_display_value(max(0, total - paid_value), self.ctx.settings)
            remaining_text.color = Colors.SUCCESS if total - paid_value <= 1e-9 else Colors.ORANGE
            paid_progress.value = max(0.0, min(1.0, (paid_value / total))) if total > 1e-9 else 1.0
            self.page.update()

        def update_line_units(state: dict, selected_unit_id: int | None = None) -> None:
            state["unit"].set_choices([])
            state["unit"].value = None
            state["factor"] = 1.0
            if not state["item"].value:
                return
            item_id_value = int(state["item"].value)
            units = self.ctx.items.units(item_id_value)
            state["units"] = {int(u["id"]): u for u in units}
            state["unit"].set_choices([
                (str(u["id"]), f"{u['name']} × {self._qty(u['conversion_factor'])}") for u in units
            ])
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
                base_price_usd = float(item_row["selling_price"] if type_dd.value == "sale" else item_row["purchase_price"])
                state["base_price"] = currency.to_display(base_price_usd, currency.get_effective_rate(self.ctx.settings))
                update_line_units(state)
                state["price"].value = currency.format_plain(state["base_price"] * float(state.get("factor") or 1))
            recalc()

        def unit_changed(state: dict) -> None:
            if state["unit"].value:
                uid = int(state["unit"].value)
                unit_row = state.get("units", {}).get(uid)
                state["factor"] = float(unit_row["conversion_factor"]) if unit_row else 1.0
                if state.get("base_price") is not None:
                    state["price"].value = currency.format_plain(float(state["base_price"]) * state["factor"])
            recalc()

        def remove_line(state: dict) -> None:
            if len(self.lines) <= 1:
                self.notify("يجب أن تحتوي الفاتورة على بند واحد على الأقل")
                return
            self.lines.remove(state)
            lines_column.controls.remove(state["card"])
            recalc()

        def refresh_stock_badge(state: dict) -> None:
            badge = state.get("stock_badge")
            if badge is None:
                return
            item_id_value = state["item"].value
            show = False
            if type_dd.value == "sale" and item_id_value:
                item_row = item_map.get(int(item_id_value))
                if item_row and item_row.get("item_type") == "مخزون":
                    stock_qty = float(item_row.get("quantity") or 0)
                    if stock_qty <= LOW_STOCK_THRESHOLD:
                        label = "نفدت الكمية في المخزون" if stock_qty <= 0 else f"متبقي {self._qty(stock_qty)} فقط في المخزون"
                        badge.content = ft.Row(
                            [
                                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=13, color=Colors.WARNING_DARKER),
                                ft.Text(label, size=10, color=Colors.WARNING_DARKER),
                            ],
                            spacing=5, tight=True,
                        )
                        badge.padding = ft.padding.symmetric(horizontal=8, vertical=4)
                        badge.bgcolor = Colors.WARNING_BG
                        badge.border_radius = 8
                        show = True
            badge.visible = show
            _safe_update(badge)

        def refresh_price_badge(state: dict) -> None:
            # بصمة السعر -- flags a purchase line whose price per base unit
            # is well off the item's recent history (same supplier first,
            # falling back to all suppliers). Purchase-only: sale prices are
            # the merchant's own choice, not something to second-guess here.
            badge = state.get("price_badge")
            if badge is None:
                return
            show = False
            if type_dd.value == "purchase" and state["item"].value:
                try:
                    price_usd = currency.parse_display_input(state["price"].value, self.ctx.settings)
                except Exception:
                    price_usd = None
                factor = float(state.get("factor") or 1)
                if price_usd is not None and price_usd >= 0 and factor > 0:
                    result = check_purchase_price(
                        self.ctx.db,
                        item_id=int(state["item"].value),
                        unit_price=price_usd,
                        conversion_factor=factor,
                        supplier_id=int(party_dd.value) if party_dd.value else None,
                        exclude_invoice_id=self.editing_id,
                    )
                    if result.get("flag"):
                        badge.content = ft.Row(
                            [
                                ft.Icon(ft.Icons.PRICE_CHANGE_OUTLINED, size=13, color=Colors.WARNING_DARKER),
                                ft.Text(result["message"], size=10, color=Colors.WARNING_DARKER, expand=True),
                            ],
                            spacing=5, tight=True,
                        )
                        badge.padding = ft.padding.symmetric(horizontal=8, vertical=4)
                        badge.bgcolor = Colors.WARNING_BG
                        badge.border_radius = 8
                        show = True
            badge.visible = show
            _safe_update(badge)

        def add_line(initial: dict | None = None) -> None:
            initial = initial or {}
            initial_item = item_map.get(int(initial["item_id"])) if initial.get("item_id") else None
            state: dict = {
                "factor": float(initial.get("conversion_factor") or 1),
                "units": {},
                "base_price": (
                    currency.to_display(
                        float(initial_item["selling_price"] if type_dd.value == "sale" else initial_item["purchase_price"]),
                        currency.get_effective_rate(self.ctx.settings),
                    )
                    if initial_item else None
                ),
            }
            item_dd = SearchSelect(
                label="المادة / الخدمة",
                choices=[(str(i["id"]), i["name"]) for i in items],
                value=str(initial["item_id"]) if initial.get("item_id") else None,
            )
            description = SelectAllTextField(label="البيان", value=initial.get("description") or "")
            unit_dd = SearchSelect(label="الوحدة")
            qty = SelectAllTextField(label="الكمية", value=str(initial.get("quantity") or 1), keyboard_type=ft.KeyboardType.NUMBER)
            price = SmartAmountField(
                label=currency.amount_field_label("السعر", self.ctx.settings),
                value=currency.to_input_text(initial.get("unit_price") or 0, self.ctx.settings),
            )
            line_total = ft.Text("0.00", weight=ft.FontWeight.BOLD)
            stock_badge = ft.Container(visible=False)
            price_badge = ft.Container(visible=False)
            state.update({"item": item_dd, "description": description, "unit": unit_dd, "qty": qty, "price": price, "total": line_total, "stock_badge": stock_badge, "price_badge": price_badge})

            def bump_qty(delta: float) -> None:
                try:
                    current = float(qty.value or 0)
                except Exception:
                    current = 0.0
                new_value = max(0.0, current + delta)
                qty.value = str(int(new_value)) if new_value == int(new_value) else self._qty(new_value)
                qty.update()
                recalc()
                refresh_stock_badge(state)

            item_dd.on_change = lambda e: (item_changed(state), refresh_stock_badge(state), refresh_price_badge(state))
            unit_dd.on_change = lambda e: (unit_changed(state), refresh_price_badge(state))
            qty.on_change = lambda e: (recalc(), refresh_stock_badge(state))
            price.on_change = lambda e: (recalc(), refresh_price_badge(state))
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
                                ft.Container(
                                    ft.Row(
                                        [
                                            stepper_icon_button(ft.Icons.REMOVE_CIRCLE_OUTLINE, lambda e: bump_qty(-1), tooltip="إنقاص"),
                                            ft.Container(qty, expand=True),
                                            stepper_icon_button(ft.Icons.ADD_CIRCLE_OUTLINE, lambda e: bump_qty(1), tooltip="زيادة"),
                                        ],
                                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    col={"xs": 12, "md": 3},
                                ),
                                ft.Container(price, col={"xs": 5, "md": 3}),
                                ft.Container(
                                    ft.Column([ft.Text("الإجمالي", size=11, color=Colors.TEXT_SECONDARY), line_total], spacing=2),
                                    col={"xs": 8, "md": 3},
                                    padding=8,
                                ),
                                ft.Container(
                                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="حذف البند", on_click=lambda e: remove_line(state)),
                                    col={"xs": 4, "md": 3},
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        stock_badge,
                        price_badge,
                    ],
                    spacing=4,
                ),
                padding=10,
                border=ft.border.all(1, Colors.BORDER_ALT),
                border_radius=12,
                bgcolor=Colors.WHITE,
                shadow=Shadow.SM,
            )
            state["card"] = card
            self.lines.append(state)
            lines_column.controls.append(card)
            if initial.get("item_id"):
                update_line_units(state, int(initial["unit_id"]) if initial.get("unit_id") else None)
                # `price` above was seeded from initial.get("unit_price"), which
                # callers that only know the item (e.g. barcode scan-to-add)
                # don't have -- compute it the same way item_changed() would,
                # so a scanned line shows a real price and not "0.00".
                if not initial.get("unit_price") and state.get("base_price") is not None:
                    price.value = currency.format_plain(float(state["base_price"]) * float(state.get("factor") or 1))
            refresh_stock_badge(state)
            refresh_price_badge(state)
            recalc()

        def add_or_bump_item(item_id: int) -> str:
            # If this item already has a line on the invoice, bump its
            # quantity by one instead of adding a duplicate row -- matches
            # how a cashier expects repeated scans/taps of the same product
            # to behave at a real point of sale. Returns "bumped"/"added" so
            # callers that want scan feedback (see scan_to_add_line) can
            # tell the two apart; the manual item-picker call site below
            # ignores the return value and stays silent, same as before.
            existing_state = next((s for s in self.lines if s["item"].value == str(item_id)), None)
            if existing_state is not None:
                try:
                    existing_state["qty"].value = str(float(existing_state["qty"].value or 0) + 1)
                except Exception:
                    existing_state["qty"].value = "1"
                existing_state["qty"].update()
                recalc()
                return "bumped"
            add_line({"item_id": item_id, "quantity": 1})
            self.page.update()
            return "added"

        async def scan_to_add_line(_):
            if self.native_files is None:
                self.notify("مسح الباركود غير مهيأ في هذا البناء", kind="error")
                return
            try:
                code = await self.native_files.scan_barcode()
            except Exception as exc:
                self.notify(str(exc), kind="error")
                return
            if not code:
                return
            found = self.ctx.items.find_by_barcode(code)
            if not found:
                self.notify("لا توجد مادة بهذا الباركود", kind="error", sound_kind="barcode_error")
                return
            # Same audible/visual scan feedback as the POS screen's barcode
            # path (core/sound.py's dedicated "scan" tone, gated by the
            # same admin "الباركود" -> "طريقة إشعار المسح" setting) -- this
            # call site used to add the line completely silently, so a
            # successful scan into an invoice looked identical to a failed
            # one that just didn't show anything yet.
            status = add_or_bump_item(int(found["id"]))
            if barcode_settings.scan_feedback_mode(self.ctx.settings) == "brief":
                self.notify("✔", kind="success", sound_kind="scan")
            elif status == "bumped":
                self.notify(f"✔ زيدت الكمية: {found['name']}", kind="success", sound_kind="scan")
            else:
                self.notify(f"✔ أُضيف: {found['name']}", kind="success", sound_kind="scan")

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
                    base_price_usd = float(item_row["selling_price"] if type_dd.value == "sale" else item_row["purchase_price"])
                    state["base_price"] = currency.to_display(base_price_usd, currency.get_effective_rate(self.ctx.settings))
                    state["price"].value = currency.format_plain(state["base_price"] * float(state.get("factor") or 1))
                refresh_stock_badge(state)
                refresh_price_badge(state)
            update_party_insight()
            refresh_suggestions()
            recalc()

        def party_changed(_):
            # Supplier determines the price-history scope for purchase lines.
            for state in self.lines:
                refresh_price_badge(state)
            update_party_insight()
            refresh_suggestions()
            recalc()

        type_dd.on_change = type_changed
        party_dd.on_change = party_changed
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
                            unit_price=parse_money(state["price"], f"سعر البند {idx}"),
                        )
                    )
                paid_value = parse_money(paid, "المبلغ المدفوع")
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
                self.notify(message, sound_kind="save")
                self.show_center()
                if type_dd.value == "sale":
                    # PHASE10: sales move the two numbers on the home screen
                    # widget (today's total, cash) -- refresh it right away
                    # instead of waiting for the next periodic pass.
                    refresh_home_widget(self.page, self.native_files, self.ctx.dashboard)
                if self.on_saved:
                    self.on_saved()
            except Exception as exc:
                self.notify(str(exc), kind="error")

        # Body scrolls; totals + save stay pinned in a sticky footer below it
        # so they're always visible even on a long line-item list, instead
        # of disappearing off the bottom of one long scrollable column.
        # Sticky top: back button + buy/sell toggle stay reachable no matter
        # how far the body is scrolled, instead of scrolling away with the
        # line items below them.
        sticky_top = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.OutlinedButton("رجوع للفواتير", icon=ft.Icons.ARROW_FORWARD, on_click=lambda _: self.show_center()),
                            ft.Container(
                                ft.Text("نقدي تلقائيًا عند عدم اختيار عميل / مورد", size=10, color=Colors.PRIMARY, weight=ft.FontWeight.W_600),
                                padding=ft.padding.symmetric(horizontal=10, vertical=7), bgcolor=Colors.PRIMARY_BG, border_radius=14,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True,
                    ),
                    type_dd,
                ],
                spacing=10,
            ),
            padding=ft.padding.only(left=16, right=16, top=12, bottom=8),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
        )

        scroll_body = ft.Column(
            [
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            ft.Column([party_dd, party_insight], spacing=6),
                            col={"xs": 12, "md": 5},
                        ),
                        ft.Container(invoice_date, col={"xs": 6, "md": 2}),
                        ft.Container(reference, col={"xs": 6, "md": 3}),
                    ]
                ),
                ft.Row(
                    [
                        ft.Text("بنود الفاتورة", size=18, weight=ft.FontWeight.BOLD, expand=True),
                        ft.OutlinedButton("مسح باركود", icon=ft.Icons.QR_CODE_SCANNER, on_click=scan_to_add_line),
                        ft.OutlinedButton("إضافة بند", icon=ft.Icons.ADD, on_click=lambda _: add_line()),
                    ]
                ),
                suggestions_column,
                lines_column,
                paid,
                notes,
                ft.Text(
                    "عند تعديل أو حذف فاتورة تاريخية يعاد احتساب التكلفة المتوسطة، تكلفة المبيعات، المخزون والذمم داخل Transaction واحدة.",
                    size=11,
                    color=Colors.TEXT_SECONDARY,
                ),
                ft.Container(height=8),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        sticky_bar = ft.Container(
            ft.Column(
                [
                    paid_progress,
                    ft.Row(
                        [
                            ft.Column([ft.Text("إجمالي الفاتورة", size=12, color=Colors.TEXT_SECONDARY), total_text], spacing=2, expand=True),
                            ft.Column([ft.Text("المتبقي", size=12, color=Colors.TEXT_SECONDARY), remaining_text], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, expand=True),
                            ft.FilledButton(
                                "حفظ التعديلات" if self.editing_id else "حفظ الفاتورة",
                                icon=ft.Icons.SAVE_OUTLINED,
                                on_click=save,
                                height=46,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=8,
            ),
            padding=ft.padding.only(left=16, right=16, top=10, bottom=12),
            bgcolor=Colors.WHITE,
            border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
            shadow=Shadow.LG,
        )

        self.content.content = ft.Column([sticky_top, scroll_body, sticky_bar], spacing=0, expand=True)
        update_party_insight()
        refresh_suggestions()
        recalc()
