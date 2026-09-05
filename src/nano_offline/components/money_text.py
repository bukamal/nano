"""Unified currency amount display for the UI.

Formats amounts via ``currency.format_amount`` and returns plain ``ft.Text``
controls. Prefer separating the Arabic label from the amount in a ``Row``
when embedding money inside RTL sentences (see ``labeled_money_from_str``),
so the symbol order matches standalone list cards without relying on
``text_direction`` (which some Flet/Flutter builds reject at render time).
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
    # Drop any text_direction kwarg callers may still pass — plain Text only.
    kwargs.pop("text_direction", None)
    opts: dict[str, Any] = {"value": str(formatted if formatted is not None else "")}
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
