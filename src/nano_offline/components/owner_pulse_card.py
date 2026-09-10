"""Owner Pulse Card — the 15-second business summary widget."""

from __future__ import annotations

from typing import Callable

import flet as ft

from nano_offline.core.theme import Colors, Radius, Shadow, SEVERITY_STYLE
from nano_offline.core import currency


def build_owner_pulse_card(
    pulse,
    *,
    money_fmt: Callable[[float], str],
    on_action: Callable[[object], None] | None = None,
    on_crisis_tap: Callable[[], None] | None = None,
) -> ft.Container:
    """Render a rich pulse card from an OwnerPulse instance."""

    sev = getattr(pulse, "severity", "info") or "info"
    try:
        color, bg, icon = SEVERITY_STYLE.get(sev, SEVERITY_STYLE.get("info", (Colors.PRIMARY, Colors.PRIMARY_BG, ft.Icons.INFO_ROUNDED)))
    except Exception:
        color, bg, icon = Colors.PRIMARY, Colors.PRIMARY_BG, ft.Icons.INFO_ROUNDED

    metrics = getattr(pulse, "metrics", {}) or {}
    chips: list[ft.Control] = []

    sales = metrics.get("sales_7d")
    if sales is not None:
        change = metrics.get("sales_change_pct")
        change_txt = ""
        if change is not None:
            arrow = "↑" if change >= 0 else "↓"
            change_txt = f"  {arrow}{abs(change):.0f}%"
        chips.append(_metric_chip("مبيعات ٧ أيام", f"{money_fmt(sales)}{change_txt}", Colors.PRIMARY))

    profit = metrics.get("approx_profit_7d")
    if profit is not None:
        pcolor = Colors.SUCCESS if profit >= 0 else Colors.DANGER
        chips.append(_metric_chip("ربح تقريبي", money_fmt(profit), pcolor))

    recv = metrics.get("receivables")
    if recv is not None and recv > 0:
        chips.append(_metric_chip("ذمم مدينة", money_fmt(recv), Colors.WARNING))

    low = metrics.get("low_stock_count")
    if low is not None and low > 0:
        chips.append(_metric_chip("مخزون منخفض", str(low), Colors.DANGER))

    crisis_banner = ft.Container(height=0)
    if metrics.get("crisis_active"):
        crisis_banner = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=16, color=Colors.DANGER),
                    ft.Text("وضع الطوارئ الاقتصادي مفعّل", size=11, weight=ft.FontWeight.W_600, color=Colors.DANGER),
                ],
                spacing=6,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=Colors.DANGER_BG if hasattr(Colors, "DANGER_BG") else "#FEE2E2",
            border_radius=10,
            on_click=(lambda e: on_crisis_tap()) if on_crisis_tap else None,
            ink=True if on_crisis_tap else False,
        )

    primary = getattr(pulse, "primary_decision", None)
    action_row = ft.Container(height=0)
    if primary is not None and getattr(primary, "action_label", None):
        def _tap(_e=None, d=primary):
            if on_action:
                on_action(d)

        action_row = ft.Container(
            ft.Row(
                [
                    ft.Text(primary.action_label, size=12, weight=ft.FontWeight.W_600, color=Colors.WHITE),
                    ft.Icon(ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, size=12, color=Colors.WHITE),
                ],
                spacing=4,
                tight=True,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            bgcolor=color,
            border_radius=12,
            on_click=_tap,
            ink=True,
        )

    return ft.Container(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Container(
                            ft.Icon(icon, size=22, color=color),
                            width=44,
                            height=44,
                            alignment=ft.alignment.center,
                            bgcolor=Colors.WHITE,
                            border_radius=14,
                        ),
                        ft.Column(
                            [
                                ft.Text("نبض المالك", size=10, color=Colors.TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                                ft.Text(pulse.headline, size=15, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(pulse.body, size=12, color=Colors.TEXT_SECONDARY),
                crisis_banner,
                ft.Row(chips, spacing=8, wrap=True) if chips else ft.Container(height=0),
                action_row,
            ],
            spacing=10,
        ),
        padding=14,
        bgcolor=bg,
        border=ft.border.all(1, color),
        border_radius=18,
        shadow=Shadow.SM,
    )


def _metric_chip(label: str, value: str, color: str) -> ft.Container:
    return ft.Container(
        ft.Column(
            [
                ft.Text(label, size=9, color=Colors.TEXT_MUTED),
                ft.Text(value, size=12, weight=ft.FontWeight.BOLD, color=color),
            ],
            spacing=1,
            tight=True,
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
        bgcolor=Colors.WHITE,
        border_radius=10,
        border=ft.border.all(1, Colors.BORDER),
    )


__all__ = ["build_owner_pulse_card"]
