"""Shared button widgets for roles that recur across many views.

The app already keeps a clean 4-way split by *widget type* (see
``core/theme.py``'s docstring style): ``FilledButton`` for the primary
action, ``OutlinedButton`` for a secondary action, ``TextButton`` for a
low-emphasis/cancel action, ``IconButton`` for icon-only actions. That part
was already consistent. What drifted was everything *below* that choice —
a handful of roles got re-implemented by hand at each call site, each time
with a slightly different pixel value or a copy-pasted ``ft.ButtonStyle(...)``
block, so the same kind of action ended up looking subtly different from
screen to screen:

- the small header "close (X)" icon button in dialogs/sheets
  (``form_sheet.py``, the definitions sheet, the notifications panel)
- the quantity +/- stepper icon button (invoice editor vs. POS cart)
- the destructive/danger filled button (delete, remove, etc.)
- the single prominent "pay" CTA button on the POS screen

Centralizing each of those here means the *role* now has one look, defined
once, instead of N hand-tuned copies that can quietly diverge again the
next time someone touches one of them. Colors are read from
``core.theme.Colors`` at call time (never cached at import time) so these
stay dark-mode-aware the same way the rest of the app is — see
``core/theme.py``'s module docstring for why that matters.

Usage:
    from nano_offline.components.buttons import danger_button, stepper_icon_button, header_close_button, hero_button
"""

from __future__ import annotations

from typing import Callable

import flet as ft

from nano_offline.core.theme import Colors, IconSize, Radius


def danger_button(text: str, *, icon: str | None = None, on_click: Callable | None = None, **kwargs) -> ft.FilledButton:
    """A destructive-action ``FilledButton`` (delete/remove/deactivate/etc.)

    Same shape as every other filled button in the app, just recolored to
    the danger token, so a "حذف" button looks the same whether it's in the
    items list, the security screen, or anywhere else.
    """
    return ft.FilledButton(
        text,
        icon=icon,
        on_click=on_click,
        style=ft.ButtonStyle(bgcolor=Colors.DANGER, color=Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=Radius.MD)),
        **kwargs,
    )


def hero_button(text: str, *, icon: str | None = None, on_click: Callable | None = None, **kwargs) -> ft.FilledButton:
    """The single prominent, full-height primary CTA used at the bottom of
    a checkout/payment flow (POS "دفع"/"بيع"). Was previously two identical
    ``ft.ButtonStyle(...)`` blocks copy-pasted between the cash-payment
    sheet and the card-payment sheet — now one definition shared by both.
    """
    kwargs.setdefault("height", 52)
    kwargs.setdefault("width", None)
    return ft.FilledButton(
        text,
        icon=icon,
        on_click=on_click,
        style=ft.ButtonStyle(bgcolor=Colors.PRIMARY, color=Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=Radius.MD)),
        **kwargs,
    )


def stepper_icon_button(icon: str, on_click: Callable, *, tooltip: str | None = None, danger: bool = False) -> ft.IconButton:
    """A quantity +/-/remove icon button, sized and colored the same
    wherever a row-level quantity is adjusted (invoice editor line items,
    POS cart rows). Pass one of the ``*_CIRCLE_OUTLINE`` icon glyphs
    (``ft.Icons.ADD_CIRCLE_OUTLINE`` / ``REMOVE_CIRCLE_OUTLINE``) for the
    +/- controls, or ``ft.Icons.CLOSE`` with ``danger=True`` for a
    remove-this-row action.
    """
    return ft.IconButton(
        icon=icon,
        icon_size=IconSize.INLINE,
        tooltip=tooltip,
        icon_color=Colors.DANGER if danger else Colors.PRIMARY,
        on_click=on_click,
    )


def header_close_button(on_click: Callable, *, tooltip: str | None = None) -> ft.IconButton:
    """The small "X" icon button in a dialog/sheet/panel header. Replaces
    three separately hand-tuned copies (form sheets, the definitions
    sheet, the notifications panel) that had drifted to slightly different
    icon sizes over time.
    """
    return ft.IconButton(ft.Icons.CLOSE, icon_size=IconSize.HEADER, icon_color=Colors.TEXT_SECONDARY, tooltip=tooltip, on_click=on_click)


def inline_icon_button(icon: str, on_click: Callable, *, tooltip: str | None = None, color: str | None = None) -> ft.IconButton:
    """A small row-level action icon (edit, etc.) — same size as
    ``stepper_icon_button`` since it plays the same "compact inline
    action" role, just without the quantity-specific coloring default.
    """
    return ft.IconButton(icon, icon_size=IconSize.INLINE, icon_color=color or Colors.TEXT_SECONDARY, tooltip=tooltip, on_click=on_click)


__all__ = ["danger_button", "hero_button", "stepper_icon_button", "header_close_button", "inline_icon_button"]
