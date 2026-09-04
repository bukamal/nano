from __future__ import annotations

from typing import Callable, Iterable

import flet as ft

from nano_offline.components.buttons import header_close_button
from nano_offline.core.theme import Colors, Shadow


def render_form_sheet(
    page: ft.Page,
    sheet: ft.BottomSheet,
    *,
    title: str,
    fields: Iterable[ft.Control],
    on_close: Callable,
    on_save: Callable,
    save_label: str = "حفظ",
    save_icon: str | None = None,
) -> None:
    """Fill an already-created ``ft.BottomSheet`` with the standard add/edit
    form chrome: drag handle, header (title + close), the form fields, and
    a Cancel/Save footer.

    No manual height math here on purpose. This used to compute an
    explicit pixel height for the outer Container from ``page.height``
    (see git history / the old "Root cause" comment this replaced) to
    work around Flutter's modal bottom sheet shrink-wrapping to a fixed
    ~9/16-screen ceiling -- but that fixed height is exactly what stopped
    the sheet from being able to grow *above* the on-screen keyboard, so
    a field near the bottom of a tall form would still end up hidden
    underneath it.

    The actual fix -- and the one Flutter/Flet officially recommend for
    this -- is ``new_form_sheet()``'s ``is_scroll_controlled=True``
    (removes that shrink-wrap ceiling entirely, so the sheet is free to
    take whatever height it needs, up to the full screen) together with
    ``maintain_bottom_view_insets_padding=True`` (pads the sheet by the
    keyboard's height so the whole thing rises above it automatically).
    With both set, a single scrollable ``Column`` holding header + fields
    + footer is all that's needed: whichever field the user taps gets
    auto-scrolled into view above the keyboard by Flutter itself, with no
    pixel math to keep in sync as forms change. Same shape as the
    security_view.py sheets, which already worked this way.
    """
    save_icon = save_icon or ft.Icons.SAVE_OUTLINED

    sheet.content = ft.Container(
        ft.Column(
            [
                ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10, alignment=ft.alignment.center),
                ft.Row(
                    [
                        ft.Text(title, size=18, weight=ft.FontWeight.BOLD, expand=True),
                        header_close_button(on_close),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Column(list(fields), spacing=9),
                ft.Row(
                    [
                        ft.OutlinedButton("إلغاء", on_click=on_close, expand=True),
                        ft.FilledButton(save_label, icon=save_icon, on_click=on_save, expand=True),
                    ],
                    spacing=10,
                ),
            ],
            spacing=16, tight=True, scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        padding=ft.padding.only(left=18, right=18, top=12, bottom=20),
        bgcolor=Colors.WHITE,
        border_radius=ft.border_radius.only(top_left=28, top_right=28),
        shadow=Shadow.LG,
    )


def new_form_sheet() -> ft.BottomSheet:
    """A bare ``ft.BottomSheet`` pre-configured the same way every form
    sheet in the app needs: draggable, allowed to grow past Flutter's
    default ~9/16-screen shrink-wrap cap (``is_scroll_controlled``), and
    padded to rise above the on-screen keyboard
    (``maintain_bottom_view_insets_padding``) so the field being typed
    into is never hidden behind it. Fill its ``content`` via
    :func:`render_form_sheet` before opening it.
    """
    return ft.BottomSheet(
        content=ft.Container(),
        is_scroll_controlled=True,
        enable_drag=True,
        maintain_bottom_view_insets_padding=True,
    )


__all__ = ["render_form_sheet", "new_form_sheet"]
