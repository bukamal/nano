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

    def _greeting_and_date(self) -> tuple[str, str, str]:
        """Return (greeting, subtitle line, icon name) for the header.

        The greeting now folds in the store name (so it reads as one
        welcoming line instead of a generic phrase floating above it) and
        picks a time-of-day icon to go with it; the subtitle keeps the
        Arabic weekday/date line. Kept as an instance method (was
        ``@staticmethod``) purely to reach ``self.ctx.settings`` for the
        store name -- nothing else about the time-of-day logic changed.
        """
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12:
            greeting, icon = "صباح الخير", ft.Icons.WB_SUNNY_ROUNDED
        elif 12 <= hour < 17:
            greeting, icon = "نهارك سعيد", ft.Icons.LIGHT_MODE_ROUNDED
        elif 17 <= hour < 21:
            greeting, icon = "مساء الخير", ft.Icons.WB_TWILIGHT_ROUNDED
        else:
            greeting, icon = "مساء النور", ft.Icons.NIGHTLIGHT_ROUND
        company = (self.ctx.settings.get("company_name") or "").strip()
        if company and company != "نانو":
            greeting = f"{greeting}، {company} 👋"
        today = now.date()
        weekday = _AR_WEEKDAYS[today.weekday()]
        month = _AR_MONTHS[today.month - 1]
        return greeting, f"{weekday}، {today.day} {month} {today.year}", icon

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

    def _set_display_currency(self, code: str) -> None:
        code = (code or "").strip().upper()
        if code not in currency.SUPPORTED_DISPLAY_CURRENCIES:
            return
        if currency.get_display_currency(self.ctx.settings) == code:
            return
        self.ctx.settings.set_many({currency.DISPLAY_CURRENCY_KEY: code})
        symbol = currency.get_display_symbol(self.ctx.settings)
        label = "الليرة السورية" if code == currency.DISPLAY_CURRENCY_SYP else "الدولار الأمريكي"
        self._notify(
            f"عملة العرض: {label} ({symbol})",
            kind="success",
            sound_kind="save",
        )
        self.show_center()

    def _rate_chip(self) -> ft.Container:
        """Currency control: one-tap SYP/USD switch + rate editor entry."""
        display_currency = currency.get_display_currency(self.ctx.settings)
        is_syp = display_currency == currency.DISPLAY_CURRENCY_SYP
        display_symbol = currency.get_display_symbol(self.ctx.settings)
        rate = currency.get_exchange_rate(self.ctx.settings)
        rate_text = f"{rate:,.0f}" if abs(rate - round(rate)) < 0.5 else f"{rate:,.2f}"

        def _seg(code: str, label: str, symbol: str) -> ft.Container:
            active = display_currency == code

            def _tap(_e, c=code):
                self._set_display_currency(c)

            return ft.Container(
                ft.Row(
                    [
                        ft.Text(symbol, size=13, weight=ft.FontWeight.BOLD,
                                color=Colors.WHITE if active else Colors.TEXT_SECONDARY),
                        ft.Text(label, size=11, weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500,
                                color=Colors.WHITE if active else Colors.TEXT_MUTED),
                    ],
                    spacing=4,
                    tight=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                bgcolor=Colors.PRIMARY if active else None,
                border_radius=12,
                expand=True,
                on_click=_tap,
                ink=True,
            )

        switch = ft.Container(
            ft.Row(
                [
                    _seg(currency.DISPLAY_CURRENCY_SYP, "ليرة", currency.DEFAULT_DISPLAY_SYMBOL),
                    _seg(currency.DISPLAY_CURRENCY_USD, "دولار", currency.DEFAULT_USD_DISPLAY_SYMBOL),
                ],
                spacing=2,
            ),
            bgcolor=Colors.BACKGROUND_ALT,
            border=ft.border.all(1, Colors.BORDER),
            border_radius=14,
            padding=3,
        )

        if is_syp:
            status_line = ft.Text(
                f"١ $ = {rate_text} {display_symbol}",
                size=11,
                weight=ft.FontWeight.W_600,
                color=Colors.TEXT_PRIMARY,
            )
        else:
            status_line = ft.Text(
                f"العرض بالدولار ({display_symbol})",
                size=11,
                weight=ft.FontWeight.W_600,
                color=Colors.TEXT_PRIMARY,
            )

        return ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                ft.Icon(ft.Icons.CURRENCY_EXCHANGE_ROUNDED, size=18, color=Colors.PRIMARY),
                                width=34, height=34, alignment=ft.alignment.center,
                                bgcolor=Colors.PRIMARY_BG, border_radius=12,
                            ),
                            ft.Text("عملة العرض", size=12, weight=ft.FontWeight.W_600,
                                    color=Colors.TEXT_SECONDARY, expand=True),
                            ft.Container(
                                ft.Icon(ft.Icons.TUNE_ROUNDED, size=16, color=Colors.PRIMARY),
                                width=32, height=32, alignment=ft.alignment.center,
                                bgcolor=Colors.PRIMARY_BG, border_radius=10,
                                on_click=self._open_rate_sheet, ink=True,
                                tooltip="تعديل سعر الصرف",
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    switch,
                    ft.Container(status_line, on_click=self._open_rate_sheet, ink=True, padding=ft.padding.only(top=2)),
                ],
                spacing=8,
                tight=True,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=Colors.WHITE,
            border=ft.border.all(1, Colors.BORDER),
            border_radius=Radius.XL,
            shadow=Shadow.SM,
        )

    # -- decision of the day (smart assistant) ------------------------------
    def _decision_of_day_card(self, decision) -> ft.Container:
        """Hero card: the single most important next step for the owner."""
        severity = getattr(decision, "severity", "info") or "info"
        try:
            color, bg, icon = SEVERITY_STYLE.get(severity, SEVERITY_STYLE.get("info"))
        except Exception:
            color, bg, icon = Colors.PRIMARY, Colors.PRIMARY_BG, ft.Icons.AUTO_AWESOME_ROUNDED
        kind_icons = {
            "restock": ft.Icons.INVENTORY_2_OUTLINED,
            "collect": ft.Icons.PERSON_OUTLINE,
            "stock": ft.Icons.WARNING_AMBER_ROUNDED,
            "backup": ft.Icons.BACKUP_OUTLINED,
            "license": ft.Icons.VERIFIED_USER_OUTLINED,
            "cash": ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
            "fx": ft.Icons.CURRENCY_EXCHANGE_ROUNDED,
            "insight": ft.Icons.LIGHTBULB_OUTLINE,
        }
        icon = kind_icons.get(getattr(decision, "kind", ""), icon)

        def _act(_e=None):
            kind = getattr(decision, "kind", None)
            target = getattr(decision, "action_target", None)
            if kind == "restock":
                self._open_purchase_list()
            elif kind == "cash":
                self._open_day_close()
            elif target == "dashboard":
                self._open_rate_sheet()
            elif target and self.on_navigate:
                self.on_navigate(target)
            elif self.on_open_notifications:
                self.on_open_notifications()

        actions = []
        if getattr(decision, "action_label", None):
            actions.append(
                ft.Container(
                    ft.Text(decision.action_label, size=11, weight=ft.FontWeight.W_600, color=Colors.WHITE),
                    padding=ft.padding.symmetric(horizontal=12, vertical=7),
                    bgcolor=color,
                    border_radius=20,
                    on_click=_act,
                    ink=True,
                )
            )

        return ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                ft.Icon(icon, size=22, color=color),
                                width=44, height=44, alignment=ft.alignment.center,
                                bgcolor=Colors.WHITE, border_radius=14,
                            ),
                            ft.Column(
                                [
                                    ft.Text("قرار اليوم", size=10, color=Colors.TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                                    ft.Text(decision.title, size=15, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                                ],
                                spacing=2, expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(decision.body, size=12, color=Colors.TEXT_SECONDARY),
                    ft.Row(actions, spacing=8) if actions else ft.Container(height=0),
                ],
                spacing=10,
            ),
            padding=14,
            bgcolor=bg,
            border=ft.border.all(1, color),
            border_radius=18,
            shadow=Shadow.SM,
        )

    def _decisions_list(self, decisions: list) -> list[ft.Control]:
        """Compact follow-up decisions under the hero card."""
        rows: list[ft.Control] = []
        for d in decisions[1:6]:
            sev = getattr(d, "severity", "info") or "info"
            try:
                color, _bg, _ic = SEVERITY_STYLE.get(sev, SEVERITY_STYLE.get("info"))
            except Exception:
                color = Colors.PRIMARY

            def _make_click(decision):
                def _click(_e=None):
                    kind = getattr(decision, "kind", None)
                    target = getattr(decision, "action_target", None)
                    if kind == "restock":
                        self._open_purchase_list()
                    elif kind == "cash":
                        self._open_day_close()
                    elif target == "dashboard":
                        self._open_rate_sheet()
                    elif target and self.on_navigate:
                        self.on_navigate(target)
                return _click

            rows.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Container(width=8, height=8, bgcolor=color, border_radius=4),
                            ft.Column(
                                [
                                    ft.Text(d.title, size=12, weight=ft.FontWeight.W_600),
                                    ft.Text(d.body, size=10, color=Colors.TEXT_FAINT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                ],
                                spacing=1, expand=True,
                            ),
                            ft.Icon(ft.Icons.CHEVRON_LEFT, size=16, color=Colors.TEXT_FAINT),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    bgcolor=Colors.BACKGROUND,
                    border_radius=12,
                    on_click=_make_click(d),
                    ink=True,
                )
            )
        return rows

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

    def _open_purchase_list(self, _e=None) -> None:
        """Suggested purchase order from restock predictions."""
        from nano_offline.components.form_sheet import new_form_sheet, render_form_sheet
        try:
            data = self.ctx.dashboard.purchase_list(limit=40)
        except Exception as exc:
            self._notify(str(exc), kind="error")
            return
        lines = data.get("lines") or []
        sheet = new_form_sheet()

        def close(_=None):
            self.page.close(sheet)

        rows: list[ft.Control] = []
        if not lines:
            rows.append(ft.Text("لا توجد مواد تحتاج إعادة طلب حاليًا.", size=12, color=Colors.TEXT_SECONDARY))
        else:
            for line in lines:
                rows.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(str(line.get("name") or "—"), size=13, weight=ft.FontWeight.W_600),
                                        ft.Text(
                                            f"متبقي {float(line.get('quantity') or 0):g} · يكفي ~{float(line.get('days_left') or 0):.0f} يوم",
                                            size=10, color=Colors.TEXT_FAINT,
                                        ),
                                    ],
                                    spacing=2, expand=True,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(f"اطلب {float(line.get('suggested_qty') or 0):g}", size=12, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY),
                                        ft.Text(self.money(line.get("line_cost_usd")), size=10, color=Colors.TEXT_SECONDARY),
                                    ],
                                    spacing=2,
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=10,
                        bgcolor=Colors.BACKGROUND,
                        border_radius=12,
                    )
                )
            rows.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Text("تكلفة تقديرية", size=12, color=Colors.TEXT_SECONDARY, expand=True),
                            ft.Text(self.money(data.get("estimated_cost_usd")), size=14, weight=ft.FontWeight.BOLD),
                        ]
                    ),
                    padding=12,
                    bgcolor=Colors.PRIMARY_BG,
                    border_radius=12,
                )
            )

        render_form_sheet(
            self.page,
            sheet,
            title="قائمة شراء مقترحة",
            fields=[
                ft.Text("حسب سرعة البيع خلال 30 يومًا — للتحضير لطلب المورد.", size=12, color=Colors.TEXT_SECONDARY),
                ft.Column(rows, spacing=6, scroll=ft.ScrollMode.AUTO, height=360),
            ],
            on_close=close,
            on_save=lambda _: (close(), self.on_navigate("items") if self.on_navigate else None),
            save_label="فتح المواد",
            save_icon=ft.Icons.INVENTORY_2_OUTLINED,
        )
        self.page.open(sheet)

    def _open_day_close(self, _e=None) -> None:
        """End-of-day cash count vs book balance."""
        from nano_offline.components.form_sheet import new_form_sheet, render_form_sheet
        from nano_offline.components.text_field import SelectAllTextField
        from nano_offline.core import currency as currency_mod

        book = self.ctx.cash_day_close.book_cash()
        movement = self.ctx.cash_day_close.today_cash_movement()
        last = self.ctx.cash_day_close.last_close()
        sheet = new_form_sheet()
        counted_field = SelectAllTextField(
            label=currency_mod.amount_field_label("المبلغ المعدود في الصندوق", self.ctx.settings),
            value=currency_mod.to_input_text(book, self.ctx.settings),
            keyboard_type=ft.KeyboardType.NUMBER,
            prefix_icon=ft.Icons.PAYMENTS_OUTLINED,
        )
        note_field = SelectAllTextField(label="ملاحظة (اختياري)", multiline=True, min_lines=1, max_lines=3)
        adjust_switch = ft.Switch(label="ترحيل تسوية للصندوق لتطابق العدّ", value=True)
        preview = ft.Text("", size=12, color=Colors.TEXT_SECONDARY)

        def refresh_preview(_=None):
            try:
                counted_disp = float((counted_field.value or "0").replace(",", "").strip() or 0)
                counted_usd = currency_mod.parse_display_input(counted_field.value, self.ctx.settings)
            except Exception:
                counted_usd = 0.0
            var = counted_usd - book
            preview.value = (
                f"دفتر الصندوق: {self.money(book)} · معدود: {self.money(counted_usd)} · "
                f"الفرق: {self.money(var)}"
            )
            preview.color = Colors.SUCCESS if abs(var) < 1e-6 else Colors.WARNING_DARK
            try:
                preview.update()
            except Exception:
                pass

        counted_field.on_change = refresh_preview
        refresh_preview()

        def close(_=None):
            self.page.close(sheet)

        def save(_=None):
            try:
                counted_usd = currency_mod.parse_display_input(counted_field.value, self.ctx.settings)
            except Exception as exc:
                self._notify(str(exc), kind="error")
                return
            session = None
            try:
                session = self.ctx.auth.current()
            except Exception:
                pass
            try:
                result = self.ctx.cash_day_close.close_day(
                    counted_cash=counted_usd,
                    note=note_field.value or "",
                    post_adjustment=bool(adjust_switch.value),
                    username=getattr(session, "username", None) if session else None,
                    user_id=getattr(session, "id", None) if session else None,
                )
            except Exception as exc:
                self._notify(str(exc), kind="error")
                return
            close()
            var = float(result.get("variance") or 0)
            msg = "تم إغلاق يوم الصندوق"
            if abs(var) > 1e-6:
                msg += f" — فرق {self.money(var)}"
                if result.get("adjustment_posted"):
                    msg += " (مع تسوية)"
            self._notify(msg, kind="success", sound_kind="save")
            self.show_center()

        last_line = ""
        if last:
            last_line = f"آخر إغلاق: {last.get('date') or '—'} · معدود {self.money(last.get('counted_cash'))}"

        render_form_sheet(
            self.page,
            sheet,
            title="إغلاق يوم الصندوق",
            fields=[
                ft.Text(
                    f"حركة اليوم — وارد: {self.money(movement['inflow'])} · صادر: {self.money(movement['outflow'])}",
                    size=12, color=Colors.TEXT_SECONDARY,
                ),
                ft.Text(f"رصيد الدفتر الآن: {self.money(book)}", size=13, weight=ft.FontWeight.BOLD),
                counted_field,
                preview,
                adjust_switch,
                note_field,
                ft.Text(last_line, size=10, color=Colors.TEXT_FAINT) if last_line else ft.Container(height=0),
            ],
            on_close=close,
            on_save=save,
            save_label="إغلاق اليوم",
            save_icon=ft.Icons.LOCK_CLOCK_OUTLINED,
        )
        self.page.open(sheet)

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
        try:
            decisions = self.ctx.smart_assistant.decisions(limit=8)
            decision_today = self.ctx.smart_assistant.decision_of_the_day()
        except Exception:
            decisions = []
            decision_today = None

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
        greeting, date_line, greeting_icon = self._greeting_and_date()

        # Greeting/date + live currency rate stay pinned above the scroll --
        # everything else (KPIs, quick actions, alerts, lists...) lives in
        # the nested scrollable Column below so this row is always visible,
        # instead of disappearing the moment the user scrolls past it.
        pinned_header = ft.Container(
            ft.ResponsiveRow(
                [
                    ft.Container(
                        ft.Row(
                            [
                                ft.Container(
                                    ft.Icon(greeting_icon, size=20, color=Colors.PRIMARY),
                                    width=40, height=40, alignment=ft.alignment.center,
                                    bgcolor=Colors.PRIMARY_BG, border_radius=13,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(greeting, size=17, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                                        ft.Text(date_line, size=11, color=Colors.TEXT_FAINT),
                                    ],
                                    spacing=2, tight=True,
                                ),
                            ],
                            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
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
                self._decision_of_day_card(decision_today) if decision_today is not None else ft.Container(),
                ft.Column(self._decisions_list(decisions), spacing=6) if decisions and len(decisions) > 1 else ft.Container(),
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
                                    self._action("قائمة شراء", ft.Icons.SHOPPING_BAG_OUTLINED, lambda _: self._open_purchase_list()),
                                    self._action("إغلاق يوم", ft.Icons.LOCK_CLOCK_OUTLINED, lambda _: self._open_day_close()),
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
