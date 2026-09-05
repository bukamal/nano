"""Shared KPI/summary card.

Both the items screen and the invoices screen used to define their own,
near-identical "icon + label + value" summary card (``stat_card`` /
``summary_card``), one of them additionally tappable to act as a filter
shortcut. Extracting a single component means any future visual tweak
(radius, shadow, spacing) only has to happen once, and every screen that
adds a KPI row automatically gets the tappable-shortcut behavior for free
instead of having to reimplement it.
"""

from __future__ import annotations

from typing import Callable

import flet as ft

from nano_offline.core.theme import Colors, Shadow


def kpi_card(
    label: str,
    value: str,
    icon,
    accent: str,
    *,
    on_tap: Callable[[ft.ControlEvent], None] | None = None,
) -> ft.Container:
    """Build one KPI card for a summary row.

    Args:
        label: Small caption above the value (e.g. "عدد المواد").
        value: The headline number/text.
        icon: Icon shown in the leading badge.
        accent: Icon color -- also implies the "meaning" of the metric
            (success/danger/etc.) to the reader.
        on_tap: If given, the whole card becomes a tappable filter
            shortcut and gets a trailing chevron to hint that.
    """
    return ft.Container(
        ft.Row(
            [
                ft.Container(
                    ft.Icon(icon, color=accent, size=20),
                    width=40, height=40, alignment=ft.alignment.center,
                    bgcolor=Colors.BACKGROUND, border_radius=13,
                ),
                ft.Column(
                    [
                        ft.Text(label, size=10, color=Colors.TEXT_SECONDARY),
                        ft.Text(value, size=16, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=2, expand=True,
                ),
                *([ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=16, color=Colors.TEXT_FAINT)] if on_tap else []),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=11, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER),
        border_radius=16, shadow=Shadow.SM,
        ink=bool(on_tap), on_click=on_tap,
    )


__all__ = ["kpi_card"]
