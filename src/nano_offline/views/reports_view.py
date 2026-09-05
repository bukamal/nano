from __future__ import annotations

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import SmartDateField, empty_state
from nano_offline.core.theme import Colors, Radius, Shadow
from nano_offline.core import currency
from nano_offline.core import reporting_settings


# (key, label, icon) for each report tab. Labels are the exact literal
# strings the report-picking UI shows (and what tools/phase4_flet_ui_
# contract_smoke_test.py checks for verbatim), now driving a chip switcher
# instead of a Dropdown -- same tap-to-select language as FinanceCenter's
# section chips (views/finance_view.py._section_nav) and DashboardCenter's
# period pills, instead of a lone dropdown that read as a different, older
# control language than the rest of the app.
_REPORT_TABS: list[tuple[str, str, str]] = [
    ("pnl", "قائمة الدخل والربحية", ft.Icons.QUERY_STATS_OUTLINED),
    ("profitability", "ربحية الفواتير والمواد", ft.Icons.WORKSPACE_PREMIUM_OUTLINED),
    ("inventory", "حركة وتقييم المخزون", ft.Icons.INVENTORY_2_OUTLINED),
    ("balances", "ذمم العملاء والموردين", ft.Icons.PEOPLE_ALT_OUTLINED),
    ("cash", "حركة الصندوق", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED),
]

# Maps an accent color token to its matching soft-background token, resolved
# fresh on every call (never cached at import time) so it stays correct
# whether light or dark mode is active -- same reasoning as the inline dict
# DashboardCenter._metric builds on every call instead of once at import.
def _badge_bg(accent: str) -> str:
    return {
        Colors.PRIMARY: Colors.PRIMARY_BG,
        Colors.SUCCESS: Colors.SUCCESS_BG,
        Colors.SUCCESS_ALT: Colors.SUCCESS_BG,
        Colors.WARNING: Colors.WARNING_BG,
        Colors.WARNING_DARK: Colors.WARNING_BG,
        Colors.DANGER: Colors.DANGER_BG,
        Colors.DANGER_DARK: Colors.DANGER_BG,
        Colors.PURPLE: Colors.PURPLE_BG,
        Colors.PURPLE_LIGHT: Colors.PURPLE_BG,
        Colors.ORANGE: Colors.WARNING_BG_ALT,
    }.get(accent, Colors.PRIMARY_BG)


class ReportsCenter:
    def __init__(self, page: ft.Page, ctx, content: ft.Container, *, native_files=None, on_title_change=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.native_files = native_files
        self.on_title_change = on_title_change
        self._report_key: str = "pnl"
        self.report_dropdown: ft.Dropdown | None = None
        self.date_from: ft.TextField | None = None
        self.date_to: ft.TextField | None = None
        self.body = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        # NOTE: no wrap=True on this Row. Two fixed action buttons always
        # fit one line, and combining wrap=True with expand=True children
        # is exactly what used to crash this bar's render on Android --
        # Flutter's Wrap (what a wrapping ft.Row becomes) cannot host
        # Expanded/Flexible children, and the failed build painted as a
        # silent solid-gray box swallowing the report body underneath it
        # (see components/segmented_toggle.py's docstring for the same
        # class of bug and why SegmentedToggle deliberately never wraps).
        # That combination was the root cause of the reports tab's gray
        # screen -- this Row is the fix.
        self.export_actions = ft.Row(spacing=10)

    def _set_header(self, title: str, subtitle: str = "") -> None:
        if self.on_title_change:
            self.on_title_change(title, subtitle)

    def money(self, value) -> str:
        return currency.format_amount(value, self.ctx.settings)

    @staticmethod
    def number(value) -> str:
        return f"{float(value or 0):,.3f}".rstrip("0").rstrip(".")

    def notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    # -- shared building blocks ---------------------------------------------
    def _metric(self, title: str, value: str, *, icon, accent: str, note: str = "") -> ft.Container:
        return ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                ft.Icon(icon, size=19, color=accent),
                                width=38, height=38, alignment=ft.alignment.center,
                                bgcolor=_badge_bg(accent), border_radius=13,
                            ),
                            ft.Text(title, size=11.5, color=Colors.TEXT_SECONDARY, weight=ft.FontWeight.W_600, expand=True),
                        ],
                        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(value, size=18, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                    ft.Text(note, size=9.5, color=Colors.TEXT_FAINT) if note else ft.Container(height=1),
                ],
                spacing=7,
            ),
            padding=13,
            border=ft.border.all(1, Colors.BORDER_ALT),
            border_radius=Radius.LG,
            bgcolor=Colors.WHITE,
            shadow=Shadow.SM,
        )

    def _section_title(self, icon, text: str) -> ft.Row:
        return ft.Row(
            [
                ft.Icon(icon, size=17, color=Colors.PRIMARY),
                ft.Text(text, size=15.5, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
            ],
            spacing=7,
        )

    def _card(self, controls: list[ft.Control]) -> ft.Container:
        return ft.Container(
            ft.Column(controls, spacing=6),
            padding=12,
            border=ft.border.all(1, Colors.BORDER_ALT),
            border_radius=Radius.LG,
            bgcolor=Colors.WHITE,
            shadow=Shadow.SM,
        )

    def _entry(
        self, *, icon, accent: str, title: str, subtitle: str,
        value: str, value_sub: str | None = None, footer: ft.Control | None = None,
    ) -> ft.Container:
        """One list row shared by every report's item/invoice/party/movement
        list -- icon badge + title/subtitle + trailing value, same visual
        language as FinanceCenter's voucher rows, instead of each report
        drawing its own bespoke text-stack card."""
        rows: list[ft.Control] = [
            ft.Row(
                [
                    ft.Container(
                        ft.Icon(icon, size=17, color=accent),
                        width=40, height=40, alignment=ft.alignment.center,
                        bgcolor=_badge_bg(accent), border_radius=13,
                    ),
                    ft.Column(
                        [
                            ft.Text(title, size=12.5, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(subtitle, size=10.5, color=Colors.TEXT_SECONDARY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        spacing=2, expand=True,
                    ),
                    ft.Column(
                        [
                            ft.Text(value, size=13.5, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                            *([ft.Text(value_sub, size=9.5, color=Colors.TEXT_FAINT)] if value_sub else []),
                        ],
                        spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        ]
        if footer is not None:
            rows.append(footer)
        return ft.Container(
            ft.Column(rows, spacing=6),
            padding=12,
            bgcolor=Colors.WHITE,
            border=ft.border.all(1, Colors.BORDER_ALT),
            border_radius=Radius.LG,
            shadow=Shadow.SM,
        )

    @staticmethod
    def _footnote(text: str) -> ft.Text:
        return ft.Text(text, size=11, color=Colors.TEXT_SECONDARY)

    def _empty(self, text: str, *, icon=ft.Icons.INSIGHTS_OUTLINED) -> ft.Container:
        return empty_state(text, icon=icon)

    def _error_card(self, exc: Exception) -> ft.Container:
        """Inline failure state for a single report render -- keeps the
        picker/date bar usable and offers a retry instead of leaving the
        body empty (which used to just show bare page background and read
        as a mysterious gray gap) or silently only toasting the error."""
        message = str(exc).strip() or exc.__class__.__name__
        return ft.Container(
            ft.Column(
                [
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=34, color=Colors.DANGER_DARKER),
                    ft.Text("تعذر تحميل هذا التقرير", size=14, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                    ft.Text("جرّب تحديث الفترة أو الضغط على إعادة المحاولة.", size=11, color=Colors.TEXT_SECONDARY, text_align=ft.TextAlign.CENTER),
                    ft.Text(message, size=10.5, color=Colors.DANGER_DARKER, selectable=True, text_align=ft.TextAlign.CENTER),
                    ft.FilledButton("إعادة المحاولة", icon=ft.Icons.REFRESH, on_click=self._refresh),
                ],
                spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=20,
            border=ft.border.all(1, Colors.DANGER_BORDER),
            border_radius=Radius.LG,
            bgcolor=Colors.DANGER_BG,
            alignment=ft.alignment.center,
        )

    _DONUT_PALETTE = [
        Colors.PRIMARY, Colors.PURPLE_LIGHT, Colors.ORANGE,
        Colors.WARNING, Colors.DANGER, Colors.SUCCESS_ALT,
    ]

    def _category_donut(self, rows: list[dict], *, label_key: str, value_key: str) -> ft.Control | None:
        """Donut breakdown for a list of {label_key, value_key} rows.

        Used for the expense-by-category breakdown in the P&L report, which
        was previously a text-only list — the categories with the largest
        share are now visible at a glance instead of requiring the reader to
        scan and mentally compare numbers.
        """
        positive = [r for r in rows if float(r.get(value_key) or 0) > 0]
        if not positive:
            return None
        total = sum(float(r[value_key]) for r in positive)
        sections = []
        legend = []
        for index, row in enumerate(sorted(positive, key=lambda r: -float(r[value_key]))[:6]):
            color = self._DONUT_PALETTE[index % len(self._DONUT_PALETTE)]
            value = float(row[value_key])
            pct = (value / total * 100) if total else 0
            sections.append(ft.PieChartSection(value=value, color=color, radius=11))
            legend.append(
                ft.Row(
                    [
                        ft.Container(width=10, height=10, bgcolor=color, border_radius=3),
                        ft.Text(str(row[label_key]), size=11, expand=True),
                        ft.Text(f"{pct:.0f}%", size=11, weight=ft.FontWeight.BOLD, color=Colors.TEXT_SECONDARY),
                    ],
                    spacing=6,
                )
            )
        return ft.Row(
            [
                ft.Container(
                    ft.PieChart(sections=sections, sections_space=2, center_space_radius=22, height=110, width=110),
                    width=110, height=110,
                ),
                ft.Column(legend, spacing=6, expand=True),
            ],
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # -- report tab chips -----------------------------------------------------
    def _on_report_dropdown_change(self, e: ft.ControlEvent) -> None:
        self._select_report(e.control.value)

    def _select_report(self, key: str) -> None:
        if key == self._report_key:
            return
        self._report_key = key
        if self.report_dropdown is not None:
            self.report_dropdown.value = key
        self._refresh()

    # -- screen shell ---------------------------------------------------------
    def show_center(self) -> None:
        """Public entry point -- kept crash-proof end to end. Anything that
        goes wrong while *building* the screen (not just while rendering a
        report's data, handled separately by ``_refresh``) now falls back to
        a recoverable in-app error card instead of leaving a raw Flutter
        build failure on screen, same defensive pattern InvoiceCenter uses
        (views/invoice_view.py's ``_show_center_error``)."""
        try:
            self._build_center()
        except Exception as exc:
            self._show_center_error(exc)

    def _show_center_error(self, exc: Exception) -> None:
        self._set_header("التقارير", "تعذر تحميل شاشة التقارير")
        message = str(exc).strip() or exc.__class__.__name__
        self.content.content = ft.Column(
            [
                ft.Container(
                    ft.Column(
                        [
                            ft.Icon(ft.Icons.ERROR_OUTLINE, size=42, color=Colors.DANGER_DARKER),
                            ft.Text("تعذر تحميل شاشة التقارير", size=18, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "تم منع انهيار الواجهة. أعد المحاولة، وإذا تكرر الخطأ فاحتفظ بالتفاصيل التالية.",
                                size=12, color=Colors.TEXT_SECONDARY, text_align=ft.TextAlign.CENTER,
                            ),
                            ft.Text(message, size=11, color=Colors.DANGER_DARKER, selectable=True),
                            ft.FilledButton("إعادة المحاولة", icon=ft.Icons.REFRESH, on_click=lambda _: self.show_center()),
                        ],
                        spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=20,
                    border=ft.border.all(1, Colors.DANGER_BORDER),
                    border_radius=Radius.LG,
                    bgcolor=Colors.DANGER_BG,
                ),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def _build_center(self) -> None:
        self._set_header("التقارير", "التقارير المالية والمخزون والربحية")
        self._report_key = reporting_settings.default_report(self.ctx.settings)
        _default_from, _default_to = reporting_settings.default_range_dates(self.ctx.settings)
        self.date_from = SmartDateField(label="من تاريخ YYYY-MM-DD", hint_text="اتركه فارغًا لكل الفترة", value=_default_from)
        self.date_to = SmartDateField(label="إلى تاريخ / كما في YYYY-MM-DD", hint_text="اتركه فارغًا حتى آخر حركة", value=_default_to)

        self.report_dropdown = ft.Dropdown(
            label="نوع التقرير",
            value=self._report_key,
            options=[ft.dropdown.Option(key=key, text=label) for key, label, icon in _REPORT_TABS],
            on_change=self._on_report_dropdown_change,
            filled=True,
            bgcolor=Colors.BACKGROUND_ALT,
            border_radius=Radius.MD,
            border_color=Colors.BORDER,
        )

        # Sticky header: the report picker + date range stay reachable while
        # scrolling a long report, matching the same sticky_top/bottom_bar
        # treatment used on the items and stocktake screens -- only the
        # report body itself scrolls in between.
        sticky_top = ft.Container(
            ft.Column(
                [
                    self.report_dropdown,
                    ft.ResponsiveRow(
                        [
                            ft.Container(self.date_from, col={"xs": 6, "md": 4}),
                            ft.Container(self.date_to, col={"xs": 6, "md": 4}),
                            ft.Container(
                                ft.FilledButton("تحديث", icon=ft.Icons.REFRESH, on_click=self._refresh),
                                col={"xs": 12, "md": 4},
                            ),
                        ],
                        spacing=10, run_spacing=10,
                    ),
                ],
                spacing=12,
            ),
            padding=ft.padding.only(left=18, right=18, top=14, bottom=14),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
        )

        # Sticky footer: طباعة/مشاركة PDF stay one tap away regardless of
        # scroll position, same as the primary action bars on other screens.
        # Rounded top corners + equal-width buttons read as a deliberate
        # floating action bar instead of a plain strip butting against the
        # last report card.
        bottom_bar = ft.Container(
            self.export_actions,
            padding=ft.padding.only(left=18, right=18, top=12, bottom=12),
            bgcolor=Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=20, top_right=20),
            border=ft.border.all(1, Colors.BORDER),
            shadow=Shadow.LG,
        )

        self.content.content = ft.Column(
            [
                sticky_top,
                ft.Container(
                    self.body,
                    padding=ft.padding.only(left=18, right=18, top=14, bottom=22),
                    expand=True,
                ),
                bottom_bar,
            ],
            spacing=0,
            expand=True,
        )
        self._refresh()

    def _dates(self) -> tuple[str | None, str | None]:
        return (
            (self.date_from.value or "").strip() or None,
            (self.date_to.value or "").strip() or None,
        )

    def _refresh(self, _=None) -> None:
        report = self._report_key or "pnl"
        try:
            if report == "pnl":
                controls = self._render_pnl()
            elif report == "profitability":
                controls = self._render_profitability()
            elif report == "inventory":
                controls = self._render_inventory()
            elif report == "balances":
                controls = self._render_balances()
            else:
                controls = self._render_cash()
        except Exception as exc:
            self.notify(str(exc), kind="error")
            controls = [self._error_card(exc)]
        self.body.controls = controls
        self.export_actions.controls = [
            ft.Container(ft.OutlinedButton("طباعة التقرير", icon=ft.Icons.PRINT_OUTLINED, on_click=self._print_report), expand=True),
            ft.Container(ft.OutlinedButton("مشاركة PDF", icon=ft.Icons.PICTURE_AS_PDF_OUTLINED, on_click=self._share_report_pdf), expand=True),
        ]
        self.page.update()

    def _report_html(self) -> str:
        """Build the printable HTML for whichever report is on screen now,
        re-reading the same data the cards were just drawn from -- so print
        and PDF share always match what the user is currently looking at.
        """
        report = self._report_key or "pnl"
        date_from, date_to = self._dates()
        documents = self.ctx.documents
        if report == "pnl":
            data = self.ctx.reports.income_statement(date_from=date_from, date_to=date_to)
            return documents.pnl_report_html(data, date_from=date_from, date_to=date_to)
        if report == "profitability":
            invoices = self.ctx.reports.invoice_profitability(date_from=date_from, date_to=date_to)
            items = self.ctx.reports.item_profitability(date_from=date_from, date_to=date_to)
            top = self.ctx.reports.top_selling_items(date_from=date_from, date_to=date_to, limit=5)
            return documents.profitability_report_html(
                invoices=invoices, items=items, top=top, date_from=date_from, date_to=date_to
            )
        if report == "inventory":
            rows = self.ctx.reports.inventory_report(date_from=date_from, date_to=date_to)
            valuation = self.ctx.reports.inventory_valuation(as_of=date_to)
            return documents.inventory_report_html(rows=rows, valuation=valuation, date_from=date_from, date_to=date_to)
        if report == "balances":
            customers = self.ctx.reports.party_balances("customer", as_of=date_to)
            suppliers = self.ctx.reports.party_balances("supplier", as_of=date_to)
            open_customers = self.ctx.reports.outstanding_invoices("customer", as_of=date_to)
            open_suppliers = self.ctx.reports.outstanding_invoices("supplier", as_of=date_to)
            return documents.balances_report_html(
                customers=customers, suppliers=suppliers,
                open_customers=open_customers, open_suppliers=open_suppliers, as_of=date_to,
            )
        data = self.ctx.reports.cash_movement(date_from=date_from, date_to=date_to)
        return documents.cash_report_html(data, date_from=date_from, date_to=date_to)

    async def _print_report(self, _=None) -> None:
        if self.native_files is None:
            self.notify("الطباعة الأصلية غير مهيأة في هذا البناء")
            return
        try:
            html = self._report_html()
            report = self._report_key or "pnl"
            await self.native_files.print_html(html, name=f"nano-report-{report}")
        except Exception as exc:
            self.notify(str(exc), kind="error")

    async def _share_report_pdf(self, _=None) -> None:
        if self.native_files is None:
            self.notify("تصدير PDF غير مهيأ في هذا البناء")
            return
        try:
            html = self._report_html()
            report = self._report_key or "pnl"
            await self.native_files.share_pdf(html, filename=f"nano_report_{report}.pdf")
        except Exception as exc:
            self.notify(str(exc), kind="error")

    def _render_pnl(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        report = self.ctx.reports.income_statement(date_from=date_from, date_to=date_to)
        metrics = ft.ResponsiveRow(
            [
                ft.Container(self._metric("المبيعات", self.money(report["sales"]), icon=ft.Icons.POINT_OF_SALE_OUTLINED, accent=Colors.PRIMARY), col={"xs": 6, "md": 4}),
                ft.Container(self._metric("تكلفة المبيعات", self.money(report["cogs"]), icon=ft.Icons.RECEIPT_LONG_OUTLINED, accent=Colors.ORANGE), col={"xs": 6, "md": 4}),
                ft.Container(self._metric("مجمل الربح", self.money(report["gross_profit"]), icon=ft.Icons.TRENDING_UP_ROUNDED, accent=Colors.SUCCESS, note=f"هامش {report['gross_margin_percent']:.1f}%"), col={"xs": 6, "md": 4}),
                ft.Container(self._metric("المصروفات", self.money(report["expenses"]), icon=ft.Icons.PAYMENTS_OUTLINED, accent=Colors.DANGER), col={"xs": 6, "md": 4}),
                ft.Container(self._metric("صافي الربح", self.money(report["net_profit"]), icon=ft.Icons.SAVINGS_OUTLINED, accent=Colors.SUCCESS_ALT), col={"xs": 6, "md": 4}),
                ft.Container(self._metric("المشتريات", self.money(report["purchases"]), icon=ft.Icons.ADD_SHOPPING_CART_OUTLINED, accent=Colors.PURPLE_LIGHT, note="معلومة مشتريات وليست تكلفة مبيعات"), col={"xs": 6, "md": 4}),
            ],
            spacing=10, run_spacing=10,
        )
        expenses = ft.Column(spacing=6)
        for row in report["expense_breakdown"]:
            expenses.controls.append(
                self._entry(
                    icon=ft.Icons.SELL_OUTLINED, accent=Colors.WARNING_DARK,
                    title=row["category"], subtitle=f"عدد الحركات: {int(row['count'])}",
                    value=self.money(row["amount"]),
                )
            )
        if not expenses.controls:
            expenses.controls.append(self._empty("لا توجد مصروفات في الفترة.", icon=ft.Icons.PAYMENTS_OUTLINED))
        result: list[ft.Control] = [metrics, self._section_title(ft.Icons.CATEGORY_OUTLINED, "المصروفات حسب التصنيف")]
        donut = self._category_donut(report["expense_breakdown"], label_key="category", value_key="amount")
        if donut is not None:
            result.append(self._card([donut]))
        result.append(expenses)
        return result

    def _render_profitability(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        invoices = self.ctx.reports.invoice_profitability(date_from=date_from, date_to=date_to)
        items = self.ctx.reports.item_profitability(date_from=date_from, date_to=date_to)
        top = self.ctx.reports.top_selling_items(date_from=date_from, date_to=date_to, limit=5)

        top_cards = ft.Column(spacing=6)
        for index, row in enumerate(top, 1):
            top_cards.controls.append(
                self._entry(
                    icon=ft.Icons.WORKSPACE_PREMIUM_ROUNDED, accent=Colors.WARNING if index == 1 else Colors.PRIMARY,
                    title=f"#{index} {row['item_name']}",
                    subtitle=f"الكمية الأساسية: {self.number(row['quantity_in_base'])} • الربح: {self.money(row['gross_profit'])}",
                    value=self.money(row["revenue"]),
                )
            )
        if not top_cards.controls:
            top_cards.controls.append(self._empty("لا توجد مبيعات في الفترة.", icon=ft.Icons.WORKSPACE_PREMIUM_OUTLINED))

        invoice_cards = ft.Column(spacing=6)
        for row in invoices:
            margin = float(row["margin_percent"] or 0)
            invoice_cards.controls.append(
                self._entry(
                    icon=ft.Icons.RECEIPT_LONG_OUTLINED, accent=Colors.SUCCESS if margin >= 0 else Colors.DANGER,
                    title=f"فاتورة بيع #{row['id']}",
                    subtitle=f"{row['invoice_date']} • {row['customer_name']}",
                    value=f"{margin:.1f}%",
                    footer=self._footnote(f"المبيعات {self.money(row['total'])} • التكلفة {self.money(row['cogs'])} • الربح {self.money(row['gross_profit'])}"),
                )
            )
        if not invoice_cards.controls:
            invoice_cards.controls.append(self._empty("لا توجد فواتير بيع في الفترة.", icon=ft.Icons.RECEIPT_LONG_OUTLINED))

        item_cards = ft.Column(spacing=6)
        for row in items:
            unit = f" {row['base_unit_name']}" if row.get("base_unit_name") else ""
            item_cards.controls.append(
                self._entry(
                    icon=ft.Icons.INVENTORY_2_OUTLINED, accent=Colors.PURPLE_LIGHT,
                    title=row["item_name"],
                    subtitle=f"مبيعات {self.money(row['revenue'])} • تكلفة {self.money(row['cogs'])} • هامش {row['margin_percent']:.1f}%",
                    value=self.money(row["gross_profit"]),
                    footer=self._footnote(f"الكمية: {self.number(row['quantity_in_base'])}{unit} • فواتير: {int(row['invoice_count'])}"),
                )
            )
        if not item_cards.controls:
            item_cards.controls.append(self._empty("لا توجد مواد مباعة في الفترة.", icon=ft.Icons.INVENTORY_2_OUTLINED))

        return [
            self._section_title(ft.Icons.WORKSPACE_PREMIUM_ROUNDED, "الأكثر مبيعًا"), top_cards,
            self._section_title(ft.Icons.RECEIPT_LONG_OUTLINED, "ربحية الفواتير"), invoice_cards,
            self._section_title(ft.Icons.INVENTORY_2_OUTLINED, "ربحية المواد والخدمات"), item_cards,
        ]

    def _render_inventory(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        rows = self.ctx.reports.inventory_report(date_from=date_from, date_to=date_to)
        valuation = self.ctx.reports.inventory_valuation(as_of=date_to)
        cards = ft.Column(spacing=6)
        for row in rows:
            unit = f" {row['unit_name']}" if row.get("unit_name") else ""
            cards.controls.append(
                self._entry(
                    icon=ft.Icons.INVENTORY_2_OUTLINED, accent=Colors.PRIMARY,
                    title=row["name"],
                    subtitle=f"افتتاحي {self.number(row['opening_quantity_period'])}{unit} • وارد {self.number(row['purchases_quantity'])} • صادر {self.number(row['sales_quantity'])}",
                    value=self.money(row["closing_value"]),
                    footer=self._footnote(f"ختامي {self.number(row['closing_quantity'])}{unit} • متوسط تكلفة ختامي {self.money(row['closing_unit_cost'])}"),
                )
            )
        if not cards.controls:
            cards.controls.append(self._empty("لا توجد مواد مخزنية.", icon=ft.Icons.INVENTORY_2_OUTLINED))
        return [
            ft.ResponsiveRow(
                [
                    ft.Container(self._metric("قيمة المخزون", self.money(valuation["total_value"]), icon=ft.Icons.INVENTORY_2_OUTLINED, accent=Colors.PRIMARY, note=f"كما في {date_to or 'آخر حركة'}"), col={"xs": 6, "md": 4}),
                    ft.Container(self._metric("عدد المواد المخزنية", str(valuation["item_count"]), icon=ft.Icons.CATEGORY_OUTLINED, accent=Colors.WARNING), col={"xs": 6, "md": 4}),
                ],
                spacing=10, run_spacing=10,
            ),
            self._section_title(ft.Icons.SYNC_ALT_ROUNDED, "حركة المخزون حسب المادة"),
            cards,
        ]

    def _render_balances(self) -> list[ft.Control]:
        _, date_to = self._dates()
        customers = self.ctx.reports.party_balances("customer", as_of=date_to)
        suppliers = self.ctx.reports.party_balances("supplier", as_of=date_to)
        open_customers = self.ctx.reports.outstanding_invoices("customer", as_of=date_to)
        open_suppliers = self.ctx.reports.outstanding_invoices("supplier", as_of=date_to)

        def party_cards(report: dict, label: str, icon) -> ft.Column:
            column = ft.Column(spacing=6)
            for row in report["rows"]:
                balance = float(row["balance"] or 0)
                balance_label = "مستحق" if balance >= 0 else "رصيد دائن/مقدم"
                column.controls.append(
                    self._entry(
                        icon=icon, accent=Colors.WARNING if balance >= 0 else Colors.SUCCESS,
                        title=row["name"],
                        subtitle=f"{balance_label} • فواتير: {int(row['invoice_count'])}",
                        value=self.money(abs(balance)),
                    )
                )
            if not column.controls:
                column.controls.append(self._empty(f"لا توجد {label}.", icon=icon))
            return column

        def open_cards(rows: list[dict], label: str) -> ft.Column:
            column = ft.Column(spacing=6)
            for row in rows:
                column.controls.append(
                    self._entry(
                        icon=ft.Icons.RECEIPT_LONG_OUTLINED, accent=Colors.WARNING,
                        title=f"فاتورة #{row['id']} • {row['party_name']}",
                        subtitle=f"{row['invoice_date']} • الإجمالي {self.money(row['total'])} • المدفوع {self.money(row['paid_as_of'])}",
                        value=self.money(row["remaining_amount"]),
                    )
                )
            if not column.controls:
                column.controls.append(self._empty(f"لا توجد فواتير {label} مفتوحة.", icon=ft.Icons.RECEIPT_LONG_OUTLINED))
            return column

        return [
            ft.ResponsiveRow(
                [
                    ft.Container(self._metric("ذمم العملاء", self.money(customers["positive_total"]), icon=ft.Icons.PEOPLE_OUTLINE, accent=Colors.WARNING), col={"xs": 6, "md": 3}),
                    ft.Container(self._metric("أرصدة دائنة للعملاء", self.money(customers["credit_total"]), icon=ft.Icons.SAVINGS_OUTLINED, accent=Colors.SUCCESS), col={"xs": 6, "md": 3}),
                    ft.Container(self._metric("ذمم الموردين", self.money(suppliers["positive_total"]), icon=ft.Icons.LOCAL_SHIPPING_OUTLINED, accent=Colors.DANGER), col={"xs": 6, "md": 3}),
                    ft.Container(self._metric("دفعات مقدمة للموردين", self.money(suppliers["credit_total"]), icon=ft.Icons.PAYMENTS_OUTLINED, accent=Colors.PRIMARY), col={"xs": 6, "md": 3}),
                ],
                spacing=10, run_spacing=10,
            ),
            self._section_title(ft.Icons.PEOPLE_ALT_OUTLINED, "العملاء"), party_cards(customers, "عملاء", ft.Icons.PERSON_OUTLINE),
            self._section_title(ft.Icons.RECEIPT_LONG_OUTLINED, "فواتير العملاء المفتوحة"), open_cards(open_customers, "بيع"),
            self._section_title(ft.Icons.LOCAL_SHIPPING_OUTLINED, "الموردون"), party_cards(suppliers, "موردون", ft.Icons.LOCAL_SHIPPING_OUTLINED),
            self._section_title(ft.Icons.RECEIPT_LONG_OUTLINED, "فواتير الموردين المفتوحة"), open_cards(open_suppliers, "شراء"),
        ]

    def _render_cash(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        report = self.ctx.reports.cash_movement(date_from=date_from, date_to=date_to)
        cards = ft.Column(spacing=6)
        for row in reversed(report["rows"]):
            incoming = float(row["debit"] or 0)
            outgoing = float(row["credit"] or 0)
            cards.controls.append(
                self._entry(
                    icon=ft.Icons.SOUTH_WEST_ROUNDED if incoming else ft.Icons.NORTH_EAST_ROUNDED,
                    accent=Colors.SUCCESS if incoming else Colors.DANGER,
                    title=str(row.get("description") or row["source_type"]),
                    subtitle=str(row["entry_date"]),
                    value=self.money(incoming if incoming else outgoing),
                    footer=self._footnote(f"{'قبض' if incoming else 'صرف'} • الرصيد بعد الحركة {self.money(row['balance'])}"),
                )
            )
        if not cards.controls:
            cards.controls.append(self._empty("لا توجد حركات صندوق في الفترة.", icon=ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED))
        return [
            ft.ResponsiveRow(
                [
                    ft.Container(self._metric("رصيد افتتاحي", self.money(report["opening_balance"]), icon=ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, accent=Colors.PRIMARY), col={"xs": 6, "md": 3}),
                    ft.Container(self._metric("المقبوضات", self.money(report["receipts"]), icon=ft.Icons.SOUTH_WEST_ROUNDED, accent=Colors.SUCCESS), col={"xs": 6, "md": 3}),
                    ft.Container(self._metric("المدفوعات", self.money(report["payments"]), icon=ft.Icons.NORTH_EAST_ROUNDED, accent=Colors.DANGER), col={"xs": 6, "md": 3}),
                    ft.Container(self._metric("الرصيد الختامي", self.money(report["closing_balance"]), icon=ft.Icons.ACCOUNT_BALANCE_OUTLINED, accent=Colors.PRIMARY), col={"xs": 6, "md": 3}),
                ],
                spacing=10, run_spacing=10,
            ),
            self._section_title(ft.Icons.SWAP_VERT_ROUNDED, "حركات الصندوق"),
            cards,
        ]


__all__ = ["ReportsCenter"]
