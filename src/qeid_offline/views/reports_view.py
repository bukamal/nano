from __future__ import annotations

import flet as ft


class ReportsCenter:
    def __init__(self, page: ft.Page, ctx, content: ft.Container):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.report_type: ft.Dropdown | None = None
        self.date_from: ft.TextField | None = None
        self.date_to: ft.TextField | None = None
        self.body = ft.Column(spacing=10)

    @staticmethod
    def money(value) -> str:
        return f"{float(value or 0):,.2f}"

    @staticmethod
    def number(value) -> str:
        return f"{float(value or 0):,.3f}".rstrip("0").rstrip(".")

    def notify(self, text: str) -> None:
        self.page.open(ft.SnackBar(ft.Text(text)))

    def _metric(self, title: str, value: str, subtitle: str | None = None) -> ft.Container:
        controls = [
            ft.Text(title, size=11, color="#64748B"),
            ft.Text(value, size=19, weight=ft.FontWeight.BOLD),
        ]
        if subtitle:
            controls.append(ft.Text(subtitle, size=10, color="#64748B"))
        return ft.Container(
            ft.Column(controls, spacing=3),
            padding=12,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=12,
            bgcolor="#FFFFFF",
        )

    def _card(self, controls: list[ft.Control]) -> ft.Container:
        return ft.Container(
            ft.Column(controls, spacing=6),
            padding=11,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=12,
            bgcolor="#FFFFFF",
        )

    def show_center(self) -> None:
        self.report_type = ft.Dropdown(
            label="التقرير",
            value="pnl",
            options=[
                ft.dropdown.Option("pnl", "قائمة الدخل والربحية"),
                ft.dropdown.Option("profitability", "ربحية الفواتير والمواد"),
                ft.dropdown.Option("inventory", "حركة وتقييم المخزون"),
                ft.dropdown.Option("balances", "ذمم العملاء والموردين"),
                ft.dropdown.Option("cash", "حركة الصندوق"),
            ],
        )
        self.date_from = ft.TextField(label="من تاريخ YYYY-MM-DD", hint_text="اتركه فارغًا لكل الفترة")
        self.date_to = ft.TextField(label="إلى تاريخ / كما في YYYY-MM-DD", hint_text="اتركه فارغًا حتى آخر حركة")
        self.report_type.on_change = self._refresh

        self.content.content = ft.Column(
            [
                ft.Text("مركز التقارير", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "التقارير محلية بالكامل وتُقرأ من SQLite. الربح يعتمد على تكلفة البضاعة المباعة المخزنة وقت البيع، وليس على إجمالي المشتريات.",
                    size=12,
                    color="#64748B",
                ),
                ft.ResponsiveRow(
                    [
                        ft.Container(self.report_type, col={"xs": 12, "md": 4}),
                        ft.Container(self.date_from, col={"xs": 6, "md": 3}),
                        ft.Container(self.date_to, col={"xs": 6, "md": 3}),
                        ft.Container(
                            ft.FilledButton("تحديث", icon=ft.Icons.REFRESH, on_click=self._refresh),
                            col={"xs": 12, "md": 2},
                        ),
                    ]
                ),
                ft.Divider(),
                self.body,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )
        self._refresh()

    def _dates(self) -> tuple[str | None, str | None]:
        return (
            (self.date_from.value or "").strip() or None,
            (self.date_to.value or "").strip() or None,
        )

    def _refresh(self, _=None) -> None:
        try:
            report = self.report_type.value if self.report_type else "pnl"
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
            self.body.controls = controls
            self.page.update()
        except Exception as exc:
            self.notify(str(exc))

    def _render_pnl(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        report = self.ctx.reports.income_statement(date_from=date_from, date_to=date_to)
        metrics = ft.ResponsiveRow(
            [
                ft.Container(self._metric("المبيعات", self.money(report["sales"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("تكلفة المبيعات", self.money(report["cogs"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("مجمل الربح", self.money(report["gross_profit"]), f"هامش {report['gross_margin_percent']:.1f}%"), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("المصروفات", self.money(report["expenses"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("صافي الربح", self.money(report["net_profit"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("المشتريات", self.money(report["purchases"]), "معلومة مشتريات وليست تكلفة مبيعات"), col={"xs": 6, "md": 3}),
            ]
        )
        expenses = ft.Column(spacing=6)
        for row in report["expense_breakdown"]:
            expenses.controls.append(
                self._card([
                    ft.Row([
                        ft.Text(row["category"], weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(self.money(row["amount"]), weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Text(f"عدد الحركات: {int(row['count'])}", size=11, color="#64748B"),
                ])
            )
        if not expenses.controls:
            expenses.controls.append(ft.Text("لا توجد مصروفات في الفترة.", color="#64748B"))
        return [metrics, ft.Text("المصروفات حسب التصنيف", size=17, weight=ft.FontWeight.BOLD), expenses]

    def _render_profitability(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        invoices = self.ctx.reports.invoice_profitability(date_from=date_from, date_to=date_to)
        items = self.ctx.reports.item_profitability(date_from=date_from, date_to=date_to)
        top = self.ctx.reports.top_selling_items(date_from=date_from, date_to=date_to, limit=5)

        top_cards = ft.Column(spacing=6)
        for index, row in enumerate(top, 1):
            top_cards.controls.append(self._card([
                ft.Row([
                    ft.Text(f"#{index} {row['item_name']}", weight=ft.FontWeight.BOLD, expand=True),
                    ft.Text(self.money(row["revenue"]), weight=ft.FontWeight.BOLD),
                ]),
                ft.Text(f"الكمية الأساسية: {self.number(row['quantity_in_base'])} • الربح: {self.money(row['gross_profit'])}", size=11, color="#64748B"),
            ]))
        if not top_cards.controls:
            top_cards.controls.append(ft.Text("لا توجد مبيعات في الفترة.", color="#64748B"))

        invoice_cards = ft.Column(spacing=6)
        for row in invoices:
            invoice_cards.controls.append(self._card([
                ft.Row([
                    ft.Column([
                        ft.Text(f"فاتورة بيع #{row['id']}", weight=ft.FontWeight.BOLD),
                        ft.Text(f"{row['invoice_date']} • {row['customer_name']}", size=11, color="#64748B"),
                    ], spacing=2, expand=True),
                    ft.Text(f"{row['margin_percent']:.1f}%", weight=ft.FontWeight.BOLD),
                ]),
                ft.Text(
                    f"المبيعات {self.money(row['total'])} • التكلفة {self.money(row['cogs'])} • الربح {self.money(row['gross_profit'])}",
                    size=11,
                ),
            ]))
        if not invoice_cards.controls:
            invoice_cards.controls.append(ft.Text("لا توجد فواتير بيع في الفترة.", color="#64748B"))

        item_cards = ft.Column(spacing=6)
        for row in items:
            unit = f" {row['base_unit_name']}" if row.get("base_unit_name") else ""
            item_cards.controls.append(self._card([
                ft.Row([
                    ft.Text(row["item_name"], weight=ft.FontWeight.BOLD, expand=True),
                    ft.Text(self.money(row["gross_profit"]), weight=ft.FontWeight.BOLD),
                ]),
                ft.Text(
                    f"مبيعات {self.money(row['revenue'])} • تكلفة {self.money(row['cogs'])} • هامش {row['margin_percent']:.1f}%",
                    size=11,
                ),
                ft.Text(f"الكمية: {self.number(row['quantity_in_base'])}{unit} • فواتير: {int(row['invoice_count'])}", size=11, color="#64748B"),
            ]))
        if not item_cards.controls:
            item_cards.controls.append(ft.Text("لا توجد مواد مباعة في الفترة.", color="#64748B"))

        return [
            ft.Text("الأكثر مبيعًا", size=17, weight=ft.FontWeight.BOLD), top_cards,
            ft.Text("ربحية الفواتير", size=17, weight=ft.FontWeight.BOLD), invoice_cards,
            ft.Text("ربحية المواد والخدمات", size=17, weight=ft.FontWeight.BOLD), item_cards,
        ]

    def _render_inventory(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        rows = self.ctx.reports.inventory_report(date_from=date_from, date_to=date_to)
        valuation = self.ctx.reports.inventory_valuation(as_of=date_to)
        cards = ft.Column(spacing=6)
        for row in rows:
            unit = f" {row['unit_name']}" if row.get("unit_name") else ""
            cards.controls.append(self._card([
                ft.Row([
                    ft.Text(row["name"], weight=ft.FontWeight.BOLD, expand=True),
                    ft.Text(self.money(row["closing_value"]), weight=ft.FontWeight.BOLD),
                ]),
                ft.Text(
                    f"افتتاحي {self.number(row['opening_quantity_period'])}{unit} • وارد {self.number(row['purchases_quantity'])} • صادر {self.number(row['sales_quantity'])}",
                    size=11,
                ),
                ft.Text(
                    f"ختامي {self.number(row['closing_quantity'])}{unit} • متوسط تكلفة ختامي {self.money(row['closing_unit_cost'])}",
                    size=11,
                    color="#64748B",
                ),
            ]))
        if not cards.controls:
            cards.controls.append(ft.Text("لا توجد مواد مخزنية.", color="#64748B"))
        return [
            ft.ResponsiveRow([
                ft.Container(self._metric("قيمة المخزون", self.money(valuation["total_value"]), f"كما في {date_to or 'آخر حركة'}"), col={"xs": 6, "md": 4}),
                ft.Container(self._metric("عدد المواد المخزنية", str(valuation["item_count"])), col={"xs": 6, "md": 4}),
            ]),
            ft.Text("حركة المخزون حسب المادة", size=17, weight=ft.FontWeight.BOLD),
            cards,
        ]

    def _render_balances(self) -> list[ft.Control]:
        _, date_to = self._dates()
        customers = self.ctx.reports.party_balances("customer", as_of=date_to)
        suppliers = self.ctx.reports.party_balances("supplier", as_of=date_to)
        open_customers = self.ctx.reports.outstanding_invoices("customer", as_of=date_to)
        open_suppliers = self.ctx.reports.outstanding_invoices("supplier", as_of=date_to)

        def party_cards(report: dict, label: str) -> ft.Column:
            column = ft.Column(spacing=6)
            for row in report["rows"]:
                balance = float(row["balance"] or 0)
                balance_label = "مستحق" if balance >= 0 else "رصيد دائن/مقدم"
                column.controls.append(self._card([
                    ft.Row([
                        ft.Text(row["name"], weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(self.money(abs(balance)), weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Text(f"{balance_label} • فواتير: {int(row['invoice_count'])}", size=11, color="#64748B"),
                ]))
            if not column.controls:
                column.controls.append(ft.Text(f"لا توجد {label}.", color="#64748B"))
            return column

        def open_cards(rows: list[dict], label: str) -> ft.Column:
            column = ft.Column(spacing=6)
            for row in rows:
                column.controls.append(self._card([
                    ft.Row([
                        ft.Text(f"فاتورة #{row['id']} • {row['party_name']}", weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(self.money(row["remaining_amount"]), weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Text(f"{row['invoice_date']} • الإجمالي {self.money(row['total'])} • المدفوع {self.money(row['paid_as_of'])}", size=11, color="#64748B"),
                ]))
            if not column.controls:
                column.controls.append(ft.Text(f"لا توجد فواتير {label} مفتوحة.", color="#64748B"))
            return column

        return [
            ft.ResponsiveRow([
                ft.Container(self._metric("ذمم العملاء", self.money(customers["positive_total"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("أرصدة دائنة للعملاء", self.money(customers["credit_total"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("ذمم الموردين", self.money(suppliers["positive_total"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("دفعات مقدمة للموردين", self.money(suppliers["credit_total"])), col={"xs": 6, "md": 3}),
            ]),
            ft.Text("العملاء", size=17, weight=ft.FontWeight.BOLD), party_cards(customers, "عملاء"),
            ft.Text("فواتير العملاء المفتوحة", size=17, weight=ft.FontWeight.BOLD), open_cards(open_customers, "بيع"),
            ft.Text("الموردون", size=17, weight=ft.FontWeight.BOLD), party_cards(suppliers, "موردون"),
            ft.Text("فواتير الموردين المفتوحة", size=17, weight=ft.FontWeight.BOLD), open_cards(open_suppliers, "شراء"),
        ]

    def _render_cash(self) -> list[ft.Control]:
        date_from, date_to = self._dates()
        report = self.ctx.reports.cash_movement(date_from=date_from, date_to=date_to)
        cards = ft.Column(spacing=6)
        for row in reversed(report["rows"]):
            incoming = float(row["debit"] or 0)
            outgoing = float(row["credit"] or 0)
            cards.controls.append(self._card([
                ft.Row([
                    ft.Column([
                        ft.Text(row.get("description") or row["source_type"], weight=ft.FontWeight.BOLD),
                        ft.Text(str(row["entry_date"]), size=11, color="#64748B"),
                    ], spacing=2, expand=True),
                    ft.Text(self.money(incoming if incoming else outgoing), weight=ft.FontWeight.BOLD),
                ]),
                ft.Text(
                    f"{'قبض' if incoming else 'صرف'} • الرصيد بعد الحركة {self.money(row['balance'])}",
                    size=11,
                    color="#64748B",
                ),
            ]))
        if not cards.controls:
            cards.controls.append(ft.Text("لا توجد حركات صندوق في الفترة.", color="#64748B"))
        return [
            ft.ResponsiveRow([
                ft.Container(self._metric("رصيد افتتاحي", self.money(report["opening_balance"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("المقبوضات", self.money(report["receipts"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("المدفوعات", self.money(report["payments"])), col={"xs": 6, "md": 3}),
                ft.Container(self._metric("الرصيد الختامي", self.money(report["closing_balance"])), col={"xs": 6, "md": 3}),
            ]),
            ft.Text("حركات الصندوق", size=17, weight=ft.FontWeight.BOLD),
            cards,
        ]
