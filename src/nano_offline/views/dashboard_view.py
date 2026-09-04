from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

import flet as ft

from nano_offline.core.theme import Colors, Radius, SEVERITY_STYLE, Shadow
from nano_offline.core import currency
from nano_offline.core.toast import toast
from nano_offline.components import SelectAllTextField, new_form_sheet, render_form_sheet

# Arabic weekday/month names for the header's live date line -- kept local
# (rather than relying on locale-dependent strftime) so it renders correctly
# regardless of the host OS's configured locale.
_AR_WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
_AR_MONTHS = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]

# (key, label, days) -- "days" is the window length in days ending today,
# used both to compute the period itself and an equal-length "previous"
# window immediately before it for the trend comparison.
_PERIOD_OPTIONS: list[tuple[str, str, int]] = [
    ("today", "اليوم", 1),
    ("week", "٧ أيام", 7),
    ("month", "٣٠ يومًا", 30),
]

# Where a dashboard alert card navigates when tapped, keyed by
# NotificationService.Alert.entity_type. None (backup/license/insights
# alerts have no single-entity target) falls back to the notifications panel.
_ALERT_NAV = {"customer": "customers", "item": "items"}


class DashboardCenter:
    """Home dashboard: KPIs, quick actions, sales/purchases flow, smart
    alerts, business insights, and recent invoices.

    Extracted from ``main.py`` (previously the inline ``show_dashboard`` closure)
    to keep the shell file focused on shell/navigation wiring only.
    """

    def __init__(
        self,
        page: ft.Page,
        ctx,
        content: ft.Container,
        *,
        on_title_change: Callable[[str, str], None] | None = None,
        on_navigate: Callable[[str], None],
        on_open_sale: Callable[[], None],
        on_open_purchase: Callable[[], None],
        on_open_notifications: Callable[..., None] | None = None,
    ):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_title_change = on_title_change
        self.on_navigate = on_navigate
        self.on_open_sale = on_open_sale
        self.on_open_purchase = on_open_purchase
        self.on_open_notifications = on_open_notifications
        # Which period tab is selected for the "period performance" section
        # and the best/worst-seller lists. Persists across re-renders of
        # this same dashboard instance (e.g. after navigating away and back)
        # but always starts on "week" for a fresh session.
        self._period = "week"

    def _set_header(self, title: str, subtitle: str = "") -> None:
        if self.on_title_change:
            self.on_title_change(title, subtitle)

    def _notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    def money(self, value) -> str:
        return currency.format_amount(value, self.ctx.settings)

    @staticmethod
    def _greeting_and_date() -> tuple[str, str]:
        """Return (Arabic time-of-day greeting, formatted Arabic date)."""
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12:
            greeting = "صباح الخير"
        elif 12 <= hour < 17:
            greeting = "نهارك سعيد"
        elif 17 <= hour < 21:
            greeting = "مساء الخير"
        else:
            greeting = "مساء النور"
        today = now.date()
        weekday = _AR_WEEKDAYS[today.weekday()]
        month = _AR_MONTHS[today.month - 1]
        return greeting, f"{weekday}، {today.day} {month} {today.year}"

    # -- period helpers ---------------------------------------------------
    @staticmethod
    def _period_range(days: int) -> tuple[str, str, str, str]:
        """Return (current_from, current_to, previous_from, previous_to)."""
        today = date.today()
        current_to = today
        current_from = today - timedelta(days=days - 1)
        previous_to = current_from - timedelta(days=1)
        previous_from = previous_to - timedelta(days=days - 1)
        return (
            current_from.isoformat(),
            current_to.isoformat(),
            previous_from.isoformat(),
            previous_to.isoformat(),
        )

    @staticmethod
    def _percent_change(current: float, previous: float) -> float | None:
        if abs(previous) < 1e-9:
            return None if abs(current) < 1e-9 else 100.0
        return (current - previous) / abs(previous) * 100.0

    @staticmethod
    def _trend_badge(change: float | None, *, invert: bool = False) -> ft.Control:
        """Small up/down chip. ``invert`` treats a decrease as the good
        direction (e.g. purchases/expenses going down is positive news)."""
        if change is None:
            return ft.Text("—", size=11, color=Colors.TEXT_FAINT)
        good = (change >= 0) if not invert else (change <= 0)
        color = Colors.SUCCESS if good else Colors.DANGER
        icon = ft.Icons.ARROW_UPWARD_ROUNDED if change >= 0 else ft.Icons.ARROW_DOWNWARD_ROUNDED
        return ft.Row(
            [ft.Icon(icon, size=12, color=color), ft.Text(f"{abs(change):.0f}%", size=11, weight=ft.FontWeight.W_600, color=color)],
            spacing=2, tight=True,
        )

    def _period_selector(self) -> ft.Row:
        pills = []
        for key, label, _days in _PERIOD_OPTIONS:
            active = key == self._period

            def _select(_e, key=key):
                self._period = key
                self.show_center()

            pills.append(
                ft.Container(
                    ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=Colors.WHITE if active else Colors.TEXT_MUTED),
                    padding=ft.padding.symmetric(horizontal=14, vertical=7),
                    bgcolor=Colors.PRIMARY if active else Colors.BACKGROUND_ALT,
                    border_radius=Radius.SM,
                    on_click=_select,
                    ink=True,
                )
            )
        return ft.Row(pills, spacing=6)

    # -- currency rate quick-edit (also available in لوحة الإدارة → العملة) --
    def _open_rate_sheet(self, _e=None) -> None:
        current_rate = currency.get_exchange_rate(self.ctx.settings)
        rate_display = f"{current_rate:.0f}" if abs(current_rate - round(current_rate)) < 0.005 else f"{current_rate:.2f}"

        preview = ft.Text("", size=12, color=Colors.TEXT_MUTED)

        def _refresh_preview() -> None:
            try:
                r = float((rate_field.value or "0").replace(",", "").strip())
            except ValueError:
                r = 0
            if r > 0:
                preview.value = f"١ $ = {r:,.0f} ل.س      •      ١٠٠ $ = {r * 100:,.0f} ل.س"
                preview.color = Colors.TEXT_MUTED
            else:
                preview.value = "أدخل رقمًا أكبر من صفر"
                preview.color = Colors.DANGER

        rate_field = SelectAllTextField(
            label="سعر صرف الدولار (ل.س لكل 1$)",
            value=rate_display,
            keyboard_type=ft.KeyboardType.NUMBER,
            hint_text="مثال: 13500",
            autofocus=True,
            prefix_icon=ft.Icons.CURRENCY_EXCHANGE_ROUNDED,
        )

        def field_changed(_ev=None):
            _refresh_preview()
            self.page.update()

        rate_field.on_change = field_changed

        # Quick-nudge chips: bump the current rate by a common step in
        # either direction without retyping the whole number -- handy when
        # the parallel-market rate only moved a little since it was last set.
        def _nudge(step: float):
            def handler(_e):
                try:
                    r = float((rate_field.value or "0").replace(",", "").strip())
                except ValueError:
                    r = 0
                new_value = max(0.0, r + step)
                rate_field.value = f"{new_value:.0f}" if abs(new_value - round(new_value)) < 0.5 else f"{new_value:.2f}"
                _refresh_preview()
                self.page.update()
            return handler

        def nudge_chip(label: str, step: float) -> ft.Container:
            return ft.Container(
                ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=Colors.PRIMARY),
                padding=ft.padding.symmetric(horizontal=12, vertical=7),
                bgcolor=Colors.PRIMARY_BG, border_radius=Radius.MD,
                on_click=_nudge(step), ink=True,
            )

        sheet = new_form_sheet()

        def close(_ev=None) -> None:
            self.page.close(sheet)

        def save(_ev=None) -> None:
            rate_text = (rate_field.value or "").replace(",", "").strip()
            try:
                rate_value = float(rate_text)
            except ValueError:
                rate_value = 0
            if rate_value <= 0:
                self._notify("سعر الصرف يجب أن يكون رقمًا أكبر من صفر", kind="error")
                return
            self.ctx.settings.set_many({currency.EXCHANGE_RATE_KEY: str(rate_value)})
            close()
            self._notify("تم تحديث سعر الصرف — سيظهر في كل الشاشات والمستندات فورًا", kind="success", sound_kind="save")
            self.show_center()

        _refresh_preview()
        render_form_sheet(
            self.page, sheet,
            title="تحديث سعر الصرف",
            fields=[
                rate_field,
                preview,
                ft.Row(
                    [
                        ft.Text("تعديل سريع:", size=11, color=Colors.TEXT_FAINT),
                        nudge_chip("-100", -100),
                        nudge_chip("+100", 100),
                        nudge_chip("+500", 500),
                        nudge_chip("+1000", 1000),
                    ],
                    spacing=6, wrap=True,
                ),
            ],
            on_close=close, on_save=save,
            save_label="حفظ السعر",
            save_icon=ft.Icons.CHECK_ROUNDED,
        )
        self.page.open(sheet)

    def _rate_chip(self) -> ft.Container:
        """Compact live exchange-rate widget with inline edit — the same
        value the admin screen edits, surfaced here so a rate update doesn't
        require a trip to الإدارة → إعدادات العملة."""
        is_syp = currency.get_display_currency(self.ctx.settings) == currency.DISPLAY_CURRENCY_SYP
        rate = currency.get_exchange_rate(self.ctx.settings)
        rate_text = f"{rate:,.0f}" if abs(rate - round(rate)) < 0.5 else f"{rate:,.2f}"
        return ft.Container(
            ft.Row(
                [
                    ft.Container(
                        ft.Icon(ft.Icons.CURRENCY_EXCHANGE_ROUNDED, size=18, color=Colors.PRIMARY),
                        width=34, height=34, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=12,
                    ),
                    ft.Column(
                        [
                            ft.Text("سعر صرف الدولار" + ("" if is_syp else " (غير مُستخدم للعرض حاليًا)"), size=10, color=Colors.TEXT_FAINT),
                            ft.Text(f"{rate_text} ل.س", size=14, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                        ],
                        spacing=1, tight=True,
                    ),
                    ft.Container(
                        ft.Icon(ft.Icons.EDIT_ROUNDED, size=15, color=Colors.PRIMARY),
                        width=30, height=30, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=10,
                        on_click=self._open_rate_sheet, ink=True, tooltip="تحديث سعر الصرف",
                    ),
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=Colors.WHITE,
            border=ft.border.all(1, Colors.BORDER),
            border_radius=Radius.XL,
            shadow=Shadow.SM,
            on_click=self._open_rate_sheet,
            ink=True,
        )

    # -- smart insight banner ------------------------------------------------
    def _smart_insight(self, *, alerts: list, best_sellers: list, profit_change: float | None, net_profit: float) -> ft.Container:
        """One headline insight, picked by priority: an urgent smart alert,
        otherwise the current top seller, otherwise the profit trend, with a
        friendly fallback for a brand-new/quiet business."""
        icon, title, body, color, bg = ft.Icons.AUTO_AWESOME_ROUNDED, "لا جديد اليوم", "استمر بأداء عملك — لا توجد تنبيهات مهمة حاليًا.", Colors.PRIMARY, Colors.PRIMARY_BG
        urgent = next((a for a in alerts if getattr(a, "severity", "info") == "urgent"), None)
        if urgent is not None:
            color, bg, icon = SEVERITY_STYLE["urgent"]
            title, body = urgent.title, urgent.body
        elif best_sellers and float(best_sellers[0].get("revenue") or 0) > 0:
            top = best_sellers[0]
            icon, color, bg = ft.Icons.WORKSPACE_PREMIUM_ROUNDED, Colors.SUCCESS, Colors.SUCCESS_BG
            title = "الأكثر مبيعًا حاليًا"
            body = f"{top.get('item_name') or '—'} حقق {self.money(top.get('revenue'))} خلال هذه الفترة"
        elif profit_change is not None and abs(profit_change) >= 1:
            up = profit_change >= 0
            icon = ft.Icons.TRENDING_UP_ROUNDED if up else ft.Icons.TRENDING_DOWN_ROUNDED
            color, bg = (Colors.SUCCESS, Colors.SUCCESS_BG) if up else (Colors.DANGER, Colors.DANGER_BG)
            title = "صافي الربح يتحسن" if up else "تراجع في صافي الربح"
            body = f"تغيّر بنسبة {abs(profit_change):.0f}% مقارنةً بالفترة السابقة — الصافي الحالي {self.money(net_profit)}"

        return ft.Container(
            ft.Row(
                [
                    ft.Container(
                        ft.Icon(icon, size=22, color=color),
                        width=44, height=44, alignment=ft.alignment.center, bgcolor=Colors.WHITE, border_radius=14,
                    ),
                    ft.Column(
                        [
                            ft.Row([ft.Icon(ft.Icons.BOLT_ROUNDED, size=13, color=color), ft.Text("رؤية ذكية", size=11, weight=ft.FontWeight.W_700, color=color)], spacing=4),
                            ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                            ft.Text(body, size=11, color=Colors.TEXT_MUTED),
                        ],
                        spacing=2, expand=True,
                    ),
                ],
                spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
            bgcolor=bg,
            border=ft.border.all(1, color),
            border_radius=Radius.XL,
        )

    # -- small building blocks ---------------------------------------------
    @staticmethod
    def _metric(title: str, value: str, *, icon, accent: str, note: str = "") -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                ft.Icon(icon, size=20, color=accent),
                                width=40, height=40, alignment=ft.alignment.center,
                                bgcolor={Colors.SUCCESS: Colors.SUCCESS_BG, Colors.PRIMARY: Colors.PRIMARY_BG, Colors.WARNING: Colors.WARNING_BG, Colors.DANGER: Colors.DANGER_BG}.get(accent, Colors.PRIMARY_BG), border_radius=13,
                            ),
                            ft.Text(title, size=12, color=Colors.TEXT_SECONDARY, weight=ft.FontWeight.W_600, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                    ft.Text(note, size=10, color=Colors.TEXT_FAINT) if note else ft.Container(height=2),
                ],
                spacing=7,
            ),
            padding=16,
            border=ft.border.all(1, Colors.BORDER),
            border_radius=20,
            bgcolor=Colors.WHITE,
            shadow=Shadow.MD,
        )

    @staticmethod
    def _action(label: str, icon, on_click, *, primary: bool = False) -> ft.Container:
        return ft.Container(
            ft.Column(
                [
                    ft.Container(
                        ft.Icon(icon, color=Colors.WHITE if primary else Colors.PRIMARY, size=24),
                        width=48, height=48, alignment=ft.alignment.center,
                        bgcolor=Colors.PRIMARY if primary else Colors.PRIMARY_BG,
                        border_radius=16,
                    ),
                    ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY, text_align=ft.TextAlign.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=7,
            ),
            padding=10,
            border_radius=18,
            on_click=on_click,
            ink=True,
        )

    def _period_stat(self, title: str, value: float, change: float | None, *, invert: bool = False) -> ft.Column:
        return ft.Column(
            [
                ft.Text(title, size=11, color=Colors.TEXT_SECONDARY),
                ft.Text(self.money(value), size=16, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                self._trend_badge(change, invert=invert),
            ],
            spacing=3,
        )

    @staticmethod
    def _flow_donut(sales: float, purchases: float) -> ft.Container:
        """Small proportion donut: sales vs purchases share of total flow.

        Complements ``flow_row`` (the two bars below it) rather than
        replacing it — bars are best for reading absolute amounts, the
        donut is best for reading the *proportion* between them at a
        glance. Falls back to a neutral empty ring when there's no flow
        yet, instead of a division-by-zero or a blank gap.
        """
        total = sales + purchases
        if total <= 0:
            sections = [
                ft.PieChartSection(value=1, color=Colors.BACKGROUND_ALT, radius=9)
            ]
        else:
            sections = [
                ft.PieChartSection(value=max(sales, 0.0001), color=Colors.PRIMARY, radius=9),
                ft.PieChartSection(value=max(purchases, 0.0001), color=Colors.PURPLE_LIGHT, radius=9),
            ]
        return ft.Container(
            ft.PieChart(
                sections=sections,
                sections_space=2,
                center_space_radius=14,
                height=52,
                width=52,
            ),
            width=52, height=52,
        )

    @staticmethod
    def _sparkline(trend: list[dict]) -> ft.Control:
        """Tiny bar-sparkline of daily sales for the last N days.

        Built from plain ``Container`` bars (the same primitive already
        proven to render correctly in ``flow_row`` below) instead of a
        dedicated chart widget, since nothing else in this codebase uses
        ``ft.LineChart``/``ft.BarChart`` yet.
        """
        values = [max(0.0, float(p["total"])) for p in trend]
        peak = max(values, default=0.0) or 1.0
        bars = []
        for point in trend:
            value = max(0.0, float(point["total"]))
            ratio = value / peak
            is_today = point["date"] == date.today().isoformat()
            bars.append(
                ft.Container(
                    height=max(3, 34 * ratio),
                    expand=True,
                    bgcolor=Colors.PRIMARY if is_today else Colors.PRIMARY_BORDER,
                    border_radius=3,
                    tooltip=f"{point['date']}",
                )
            )
        return ft.Container(
            ft.Row(bars, spacing=3, alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.END),
            height=34,
        )

    def _alert_card(self, alert) -> ft.Container:
        color, bg, icon = SEVERITY_STYLE.get(alert.severity, SEVERITY_STYLE["info"])
        target = _ALERT_NAV.get(alert.entity_type)

        def _click(_e):
            if target:
                self.on_navigate(target)
            elif self.on_open_notifications:
                self.on_open_notifications()

        return ft.Container(
            ft.Row(
                [
                    ft.Icon(icon, color=color, size=18),
                    ft.Column(
                        [
                            ft.Text(alert.title, size=12, weight=ft.FontWeight.W_600, expand=True),
                            ft.Text(alert.body, size=10, color=Colors.TEXT_SECONDARY),
                        ],
                        spacing=1, expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_LEFT, color=Colors.TEXT_FAINT, size=16) if (target or self.on_open_notifications) else ft.Container(width=0),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START, spacing=8,
            ),
            padding=12, bgcolor=bg, border_radius=14,
            on_click=_click if (target or self.on_open_notifications) else None,
            ink=bool(target or self.on_open_notifications),
        )

    def _best_seller_row(self, row: dict, rank: int) -> ft.Row:
        return ft.Row(
            [
                ft.Container(
                    ft.Text(str(rank), size=11, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY),
                    width=22, height=22, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=11,
                ),
                ft.Text(str(row.get("item_name") or "—"), size=12, expand=True, weight=ft.FontWeight.W_600),
                ft.Text(self.money(row.get("revenue")), size=12, color=Colors.TEXT_SECONDARY),
            ],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _restock_row(self, row: dict) -> ft.Row:
        days_left = row["days_left"]
        urgent = days_left <= 3
        return ft.Row(
            [
                ft.Icon(ft.Icons.SCHEDULE_ROUNDED, size=16, color=Colors.DANGER if urgent else Colors.WARNING_DARK),
                ft.Text(str(row.get("name") or "—"), size=12, expand=True, weight=ft.FontWeight.W_600),
                ft.Text(f"يكفي ~{days_left:.0f} يوم", size=11, color=Colors.DANGER if urgent else Colors.WARNING_DARK, weight=ft.FontWeight.W_600),
            ],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def show_center(self) -> None:
        self._set_header("لوحة التحكم", "نظرة عامة على أداء عملك")
        summary = self.ctx.dashboard.summary()
        invoices = self.ctx.invoices.list_invoices(limit=100)
        recent = invoices[:5]

        sales = max(0.0, float(summary["sales"]))
        purchases = max(0.0, float(summary["purchases"]))
        max_flow = max(sales, purchases, 1.0)

        # -- selected-period performance (sales/purchases/profit + trend vs
        # the immediately preceding period of the same length) -----------
        period_days = next(d for k, _l, d in _PERIOD_OPTIONS if k == self._period)
        cur_from, cur_to, prev_from, prev_to = self._period_range(period_days)
        current_stmt = self.ctx.reports.income_statement(date_from=cur_from, date_to=cur_to)
        previous_stmt = self.ctx.reports.income_statement(date_from=prev_from, date_to=prev_to)
        sales_change = self._percent_change(current_stmt["sales"], previous_stmt["sales"])
        purchases_change = self._percent_change(current_stmt["purchases"], previous_stmt["purchases"])
        profit_change = self._percent_change(current_stmt["net_profit"], previous_stmt["net_profit"])

        sparkline = self.ctx.dashboard.sales_trend(14)

        # -- smart alerts (same rules engine behind the notifications bell,
        # recomputed live -- see NotificationService.generate_alerts) -----
        try:
            smart_alerts = self.ctx.notifications.generate_alerts()
        except Exception:
            smart_alerts = []

        # -- business insights: best sellers this period + items projected
        # to run out soon based on actual sale velocity ------------------
        try:
            best_sellers = self.ctx.reports.top_selling_items(date_from=cur_from, date_to=cur_to, limit=5, order_by="revenue")
        except Exception:
            best_sellers = []
        try:
            restock_predictions = self.ctx.dashboard.restock_predictions(limit=5)
        except Exception:
            restock_predictions = []

        def flow_row(label: str, value: float, color: str):
            ratio = max(0.04, min(1.0, value / max_flow)) if value else 0.02
            return ft.Column(
                [
                    ft.Row([ft.Text(label, size=12, color=Colors.TEXT_MUTED, expand=True), ft.Text(self.money(value), size=12, weight=ft.FontWeight.BOLD)]),
                    ft.Stack(
                        [
                            ft.Container(height=8, bgcolor=Colors.BACKGROUND_ALT, border_radius=10),
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
                                ft.Icon(ft.Icons.TRENDING_UP if sale else ft.Icons.TRENDING_DOWN, size=18, color=Colors.SUCCESS if sale else Colors.PURPLE),
                                width=38, height=38, alignment=ft.alignment.center,
                                bgcolor=Colors.SUCCESS_BG if sale else Colors.PURPLE_BG, border_radius=12,
                            ),
                            ft.Column(
                                [
                                    ft.Text(f"فاتورة {'بيع' if sale else 'شراء'} #{inv['id']}", size=13, weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{inv.get('party_name') or 'نقدي'} • {inv.get('invoice_date') or '—'}", size=10, color=Colors.TEXT_SECONDARY),
                                ], spacing=2, expand=True,
                            ),
                            ft.Column(
                                [
                                    ft.Text(self.money(inv.get("total")), size=13, weight=ft.FontWeight.BOLD),
                                    ft.Text("مسددة" if remaining <= 1e-9 else f"متبقي {self.money(remaining)}", size=9, color=Colors.SUCCESS if remaining <= 1e-9 else Colors.ORANGE),
                                ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=10,
                    border_radius=14,
                    bgcolor=Colors.BACKGROUND,
                )
            )
        if not recent_cards:
            recent_cards.append(ft.Container(ft.Text("لا توجد فواتير بعد", color=Colors.TEXT_SECONDARY, size=12), padding=12))

        alerts_controls: list[ft.Control] = [self._alert_card(a) for a in smart_alerts[:5]]
        if not alerts_controls:
            alerts_controls.append(ft.Container(ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color=Colors.SUCCESS), ft.Text("لا توجد تنبيهات مهمة حاليًا", size=12)]), padding=12, bgcolor=Colors.SUCCESS_BG, border_radius=14))

        best_seller_rows: list[ft.Control] = [self._best_seller_row(r, i + 1) for i, r in enumerate(best_sellers) if float(r.get("revenue") or 0) > 0]
        if not best_seller_rows:
            best_seller_rows.append(ft.Text("لا توجد مبيعات كافية خلال هذه الفترة", size=11, color=Colors.TEXT_FAINT))

        restock_rows: list[ft.Control] = [self._restock_row(r) for r in restock_predictions]
        if not restock_rows:
            restock_rows.append(ft.Text("لا توجد أصناف مرشحة لإعادة الطلب حاليًا", size=11, color=Colors.TEXT_FAINT))

        period_label = next(l for k, l, _d in _PERIOD_OPTIONS if k == self._period)
        greeting, date_line = self._greeting_and_date()

        # Greeting/date + live currency rate stay pinned above the scroll --
        # everything else (KPIs, quick actions, alerts, lists...) lives in
        # the nested scrollable Column below so this row is always visible,
        # instead of disappearing the moment the user scrolls past it.
        pinned_header = ft.Container(
            ft.ResponsiveRow(
                [
                    ft.Container(
                        ft.Column(
                            [
                                ft.Text(greeting, size=17, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                                ft.Text(date_line, size=11, color=Colors.TEXT_FAINT),
                            ],
                            spacing=2,
                        ),
                        col={"xs": 12, "md": 7},
                    ),
                    ft.Container(self._rate_chip(), col={"xs": 12, "md": 5}),
                ],
                spacing=10, run_spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(bottom=14),
        )

        scrollable_body = ft.Column(
            [
                self._smart_insight(alerts=smart_alerts, best_sellers=best_sellers, profit_change=profit_change, net_profit=current_stmt["net_profit"]),
                ft.ResponsiveRow(
                    [
                        ft.Container(self._metric("صافي الربح", self.money(summary["net_profit"]), icon=ft.Icons.QUERY_STATS, accent=Colors.SUCCESS, note="بعد تكلفة المبيعات والمصروفات"), col={"xs": 6, "md": 3}),
                        ft.Container(self._metric("رصيد الصندوق", self.money(summary["cash"]), icon=ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, accent=Colors.PRIMARY, note="الرصيد النقدي الحالي"), col={"xs": 6, "md": 3}),
                        ft.Container(self._metric("ذمم العملاء", self.money(summary["receivables"]), icon=ft.Icons.PEOPLE_OUTLINE, accent=Colors.WARNING, note="مبالغ مستحقة التحصيل"), col={"xs": 6, "md": 3}),
                        ft.Container(self._metric("ذمم الموردين", self.money(summary["payables"]), icon=ft.Icons.LOCAL_SHIPPING_OUTLINED, accent=Colors.DANGER, note="مبالغ مستحقة الدفع"), col={"xs": 6, "md": 3}),
                    ], spacing=10, run_spacing=10,
                ),
                ft.Container(
                    ft.Column(
                        [
                            ft.Row([ft.Text("إجراءات سريعة", size=16, weight=ft.FontWeight.BOLD, expand=True), ft.Text("الأكثر استخدامًا", size=10, color=Colors.TEXT_FAINT)]),
                            ft.Row(
                                [
                                    self._action("بيع", ft.Icons.SHOPPING_CART_CHECKOUT, lambda _: self.on_open_sale(), primary=True),
                                    self._action("شراء", ft.Icons.ADD_SHOPPING_CART, lambda _: self.on_open_purchase()),
                                    self._action("الفواتير", ft.Icons.RECEIPT_LONG_OUTLINED, lambda _: self.on_navigate("invoices")),
                                    self._action("المواد", ft.Icons.INVENTORY_2_OUTLINED, lambda _: self.on_navigate("items")),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_AROUND,
                            ),
                        ], spacing=12,
                    ),
                    padding=15, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=20, shadow=Shadow.SM,
                ),
                ft.Container(
                    ft.Column(
                        [
                            ft.Row([ft.Text("أداء الفترة", size=16, weight=ft.FontWeight.BOLD, expand=True), self._period_selector()]),
                            ft.ResponsiveRow(
                                [
                                    ft.Container(self._period_stat("المبيعات", current_stmt["sales"], sales_change), col={"xs": 4}),
                                    ft.Container(self._period_stat("المشتريات", current_stmt["purchases"], purchases_change, invert=True), col={"xs": 4}),
                                    ft.Container(self._period_stat("صافي الربح", current_stmt["net_profit"], profit_change), col={"xs": 4}),
                                ],
                            ),
                            ft.Text("اتجاه المبيعات آخر ١٤ يومًا", size=10, color=Colors.TEXT_FAINT),
                            self._sparkline(sparkline),
                        ], spacing=12,
                    ),
                    padding=16, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=20, shadow=Shadow.SM,
                ),
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            ft.Container(
                                ft.Column(
                                    [
                                        ft.Row(
                                            [
                                                ft.Text("المبيعات والمشتريات", size=16, weight=ft.FontWeight.BOLD, expand=True),
                                                self._flow_donut(sales, purchases),
                                            ],
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        flow_row("المبيعات", sales, Colors.PRIMARY),
                                        flow_row("المشتريات", purchases, Colors.PURPLE_LIGHT),
                                        ft.Row([ft.Text("قيمة المخزون", size=11, color=Colors.TEXT_SECONDARY, expand=True), ft.Text(self.money(summary["inventory_value"]), weight=ft.FontWeight.BOLD, size=12)]),
                                    ], spacing=13,
                                ),
                                padding=16, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=20, shadow=Shadow.SM,
                            ),
                            col={"xs": 12, "md": 6},
                        ),
                        ft.Container(
                            ft.Container(
                                ft.Column([ft.Text("تنبيهات ذكية", size=16, weight=ft.FontWeight.BOLD), *alerts_controls], spacing=10),
                                padding=16, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=20, shadow=Shadow.SM,
                            ),
                            col={"xs": 12, "md": 6},
                        ),
                    ], spacing=10, run_spacing=10,
                ),
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            ft.Container(
                                ft.Column(
                                    [
                                        ft.Row([ft.Text("أفضل الأصناف مبيعًا", size=15, weight=ft.FontWeight.BOLD, expand=True), ft.Text(period_label, size=10, color=Colors.TEXT_FAINT)]),
                                        *best_seller_rows,
                                    ], spacing=9,
                                ),
                                padding=16, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=20, shadow=Shadow.SM,
                            ),
                            col={"xs": 12, "md": 6},
                        ),
                        ft.Container(
                            ft.Container(
                                ft.Column(
                                    [
                                        ft.Row([ft.Text("مرشحة لإعادة الطلب", size=15, weight=ft.FontWeight.BOLD, expand=True), ft.Icon(ft.Icons.TIPS_AND_UPDATES_OUTLINED, size=16, color=Colors.TEXT_FAINT)]),
                                        *restock_rows,
                                    ], spacing=9,
                                ),
                                padding=16, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=20, shadow=Shadow.SM,
                            ),
                            col={"xs": 12, "md": 6},
                        ),
                    ], spacing=10, run_spacing=10,
                ),
                ft.Container(
                    ft.Column([ft.Row([ft.Text("آخر الفواتير", size=16, weight=ft.FontWeight.BOLD, expand=True), ft.TextButton("عرض الكل", on_click=lambda _: self.on_navigate("invoices"))]), *recent_cards], spacing=8),
                    padding=14, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=20, shadow=Shadow.SM,
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.content.content = ft.Column(
            [pinned_header, scrollable_body],
            spacing=0,
            expand=True,
        )
        self.page.update()


__all__ = ["DashboardCenter"]
