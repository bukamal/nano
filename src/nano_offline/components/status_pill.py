"""Shared status pill (colored chip).

The invoices screen already rendered payment status as a filled pill
(colored background + bold text), while the items screen rendered stock
status as plain colored text with no background. Both are "the state of
this row" in the same visual role, so they should look the same. This is
the one shared shape both screens (and any future one) render it with.
"""

from __future__ import annotations

import flet as ft


def status_pill(text: str, fg: str, bg: str, *, size: int = 9) -> ft.Container:
    return ft.Container(
        ft.Text(text, size=size, color=fg, weight=ft.FontWeight.BOLD),
        padding=ft.padding.symmetric(horizontal=8, vertical=4),
        bgcolor=bg,
        border_radius=12,
    )


__all__ = ["status_pill"]
