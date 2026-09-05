"""Unified currency amount display for the UI.

Every money figure shown on screen should go through this helper so the
currency symbol always appears in the same order as on the material/invoice
list cards (amount then symbol), regardless of surrounding RTL Arabic text.

Why LTR on the Text itself?
  ``currency.format_amount`` returns a plain string like ``"1,000 ل.س"``.
  When that string is embedded inside a longer Arabic sentence the Unicode
  bidirectional algorithm can reorder the symbol relative to the digits.
  Putting the formatted amount in its own ``ft.Text`` with
  ``text_direction=LTR`` pins the visual order to match standalone cards.

Usage
-----
Standalone (same as a list-card price column)::

    money_text(amount_usd, settings, size=12, weight=ft.FontWeight.BOLD)

After an Arabic label (detail sheets, summaries)::

    labeled_money("سعر البيع:", amount_usd, settings, size=11)

When you only have the already-formatted string (e.g. view.money())::

    money_text_from_str(formatted, size=12, weight=ft.FontWeight.BOLD)
"""

from __future__ import annotations

from typing import Any

import flet as ft

from nano_offline.core import currency


def money_text(
    amount_usd: float | int | None,
    settings=None,
    *,
    size: float | None = None,
    weight: ft.FontWeight | None = None,
    color: str | None = None,
    with_symbol: bool = True,
    decimals: int | None = None,
    **kwargs: Any,
) -> ft.Text:
    """Format a stored USD amount and return an LTR ``ft.Text`` for the UI."""
    text = currency.format_amount(
        amount_usd,
        settings,
        with_symbol=with_symbol,
        decimals=decimals,
    )
    return money_text_from_str(text, size=size, weight=weight, color=color, **kwargs)


def money_text_from_str(
    formatted: str,
    *,
    size: float | None = None,
    weight: ft.FontWeight | None = None,
    color: str | None = None,
    **kwargs: Any,
) -> ft.Text:
    """Wrap an already-formatted amount string in an LTR ``ft.Text``.

    Prefer :func:`money_text` when you still have the numeric value; use
    this when a view helper (``self.money``) has already produced the string.
    """
    opts: dict[str, Any] = {
        "value": formatted,
        "text_direction": ft.TextDirection.LTR,
    }
    if size is not None:
        opts["size"] = size
    if weight is not None:
        opts["weight"] = weight
    if color is not None:
        opts["color"] = color
    opts.update(kwargs)
    return ft.Text(**opts)


def labeled_money(
    label: str,
    amount_usd: float | int | None,
    settings=None,
    *,
    size: float = 11,
    color: str | None = None,
    amount_weight: ft.FontWeight | None = ft.FontWeight.BOLD,
    with_symbol: bool = True,
    decimals: int | None = None,
    spacing: float = 6,
) -> ft.Row:
    """Arabic label + LTR amount in one tight row (detail sheets / summaries)."""
    from nano_offline.core.theme import Colors

    fg = color if color is not None else Colors.TEXT_SECONDARY
    return ft.Row(
        [
            ft.Text(label, size=size, color=fg),
            money_text(
                amount_usd,
                settings,
                size=size,
                weight=amount_weight,
                color=fg,
                with_symbol=with_symbol,
                decimals=decimals,
            ),
        ],
        spacing=spacing,
        tight=True,
    )


def labeled_money_from_str(
    label: str,
    formatted: str,
    *,
    size: float = 11,
    color: str | None = None,
    amount_weight: ft.FontWeight | None = ft.FontWeight.BOLD,
    spacing: float = 6,
) -> ft.Row:
    """Like :func:`labeled_money` but the amount is already a formatted string."""
    from nano_offline.core.theme import Colors

    fg = color if color is not None else Colors.TEXT_SECONDARY
    return ft.Row(
        [
            ft.Text(label, size=size, color=fg),
            money_text_from_str(formatted, size=size, weight=amount_weight, color=fg),
        ],
        spacing=spacing,
        tight=True,
    )


__all__ = [
    "money_text",
    "money_text_from_str",
    "labeled_money",
    "labeled_money_from_str",
]
