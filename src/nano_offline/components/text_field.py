from __future__ import annotations

from typing import Callable

import flet as ft

from nano_offline.core.theme import Colors, Radius


class SelectAllTextField(ft.TextField):
    """App-wide drop-in replacement for ``ft.TextField``.

    Two things live here, both applied automatically to every text field
    in the app (there are ~80 call sites and none of them talk to
    ``ft.TextField`` directly -- this is the one place that shapes how an
    input feels everywhere at once):

    1. Select-all-on-focus. Tapping into a field selects its entire
       current value instead of clearing it or leaving the cursor
       wherever it lands. This is the safe alternative to a "clear on
       focus, restore on blur if untouched" pattern, which has a real
       data-loss window: a stray tap, a slow re-render, or a user who
       taps out without typing anything leaves the field genuinely empty
       in the meantime, with only the "restore" step standing between
       that and a lost price, quantity, or exchange rate.
       - Start typing right away -> the selection is replaced, same
         practical effect as clearing first, no manual delete needed.
       - Tap out without typing -> the original value is simply still
         there, because it was never removed in the first place.

    2. Modern styling + a smart inline clear button, both opt-out via
       normal kwargs (any style kwarg a caller passes through explicitly
       always wins over these defaults):
       - filled surface, colored border that visibly thickens on focus,
         and consistent label/hint/value typography, so a field looks
         deliberately designed instead of falling back to bare Material
         defaults whenever a view doesn't bother re-declaring the usual
         handful of style kwargs.
       - a small "x" that fades in once the field has text and clears it
         in one tap. Skipped automatically for passwords (the reveal
         toggle already owns that slot), multiline fields, fields that
         already declare their own suffix/suffix_icon, and narrow
         counter-style fields (width < 100) where it would just crowd a
         couple of digits.

    Any ``on_focus``/``on_change`` passed in are preserved and still run
    (after this class's own handling), so existing per-field behavior
    (``SearchSelect`` opening its results list, live search-as-you-type,
    the login screen's quick-auth chip, etc.) keeps working unchanged.
    """

    def __init__(self, *args, on_focus: Callable | None = None, on_change: Callable | None = None, **kwargs):
        self._also_on_focus = on_focus
        self._also_on_change = on_change

        # -- modern, app-wide defaults; anything the caller passes wins --
        kwargs.setdefault("filled", True)
        kwargs.setdefault("bgcolor", Colors.BACKGROUND_ALT)
        kwargs.setdefault("border_radius", Radius.MD)
        kwargs.setdefault("border_color", Colors.BORDER)
        kwargs.setdefault("border_width", 1.3)
        kwargs.setdefault("focused_border_color", Colors.PRIMARY)
        kwargs.setdefault("focused_border_width", 2)
        kwargs.setdefault("cursor_color", Colors.PRIMARY)
        kwargs.setdefault("text_style", ft.TextStyle(size=14, color=Colors.TEXT_PRIMARY, weight=ft.FontWeight.W_500))
        kwargs.setdefault("label_style", ft.TextStyle(size=13, color=Colors.TEXT_SECONDARY))
        kwargs.setdefault("hint_style", ft.TextStyle(size=13, color=Colors.TEXT_FAINT))
        if not kwargs.get("dense"):
            kwargs.setdefault("content_padding", ft.padding.symmetric(horizontal=14, vertical=13))

        # -- smart inline clear ("x") button, only where it makes sense --
        width = kwargs.get("width")
        self._show_clear = (
            not kwargs.get("password")
            and not kwargs.get("multiline")
            and "suffix" not in kwargs
            and "suffix_icon" not in kwargs
            and (width is None or width >= 100)
        )
        self._clear_button: ft.IconButton | None = None
        if self._show_clear:
            self._clear_button = ft.IconButton(
                icon=ft.Icons.CANCEL_ROUNDED,
                icon_size=16,
                icon_color=Colors.TEXT_FAINT,
                on_click=self._handle_clear,
                visible=bool(kwargs.get("value")),
                width=28,
                height=28,
                tooltip="مسح",
            )
            kwargs["suffix"] = self._clear_button

        super().__init__(*args, on_focus=self._handle_focus, on_change=self._handle_change, **kwargs)

    def _handle_focus(self, e: ft.ControlEvent) -> None:
        value = self.value or ""
        # NOTE: relies on ft.TextField.selection / ft.TextSelection
        # (present in flet==0.28.3, pinned in pyproject.toml). If a future
        # flet upgrade renames/removes this API, this is the one place to
        # update -- every field in the app goes through here.
        self.selection = ft.TextSelection(base_offset=0, extent_offset=len(value))
        self.update()
        if self._also_on_focus:
            self._also_on_focus(e)

    def _handle_change(self, e: ft.ControlEvent) -> None:
        if self._clear_button is not None:
            self._clear_button.visible = bool(self.value)
            self.update()
        if self._also_on_change:
            self._also_on_change(e)

    def _handle_clear(self, _=None) -> None:
        self.value = ""
        if self._clear_button is not None:
            self._clear_button.visible = False
        self.focus()
        self.update()
        # Every existing on_change handler in the app ignores the event
        # object and re-reads state off the field itself (see e.g.
        # LoginGate._refresh_quick, SearchSelect._field_changed), so a
        # bare None here is enough to tell them the value just changed.
        if self._also_on_change:
            self._also_on_change(None)


__all__ = ["SelectAllTextField"]
