from __future__ import annotations

from typing import Callable

import flet as ft

from nano_offline.components.text_field import SelectAllTextField


class SmartAmountField(SelectAllTextField):
    """A :class:`SelectAllTextField` specialised for money/price entry.

    Adds one thing on top of the base field: as the user types, every
    keystroke is filtered down to digits and a single decimal point (a
    second ``.`` is silently dropped, any letter/symbol never lands in
    the field to begin with). This is a real-time guard, not just a
    mobile-keyboard hint -- ``keyboard_type=NUMBER`` alone still lets a
    desktop keyboard, a paste, or an on-screen IME put letters into the
    field, and every price/amount field in the app is eventually read
    with a plain ``float(...)`` or ``currency.parse_display_input(...)``
    that would raise on that input.

    Deliberately does *not* insert thousands separators live -- several
    call sites in the app still read a price field's raw value straight
    through ``float(field.value or 0)`` (not every one goes through
    ``currency.parse_display_input``, which is the only parser that
    tolerates commas), so a live-formatted ``"12,000"`` would crash those
    on submit. Thousands formatting is a display-only concern, already
    handled separately wherever a stored amount is rendered as text
    (``currency.format_display_value``).

    Known trade-off: because the whole value is normalized after every
    change, editing in the *middle* of a number (not at the end) can
    bump the cursor to the end if an invalid character was typed and
    dropped. Typing left-to-right, backspacing, and pasting a clean
    number are all unaffected.
    """

    def __init__(self, *args, on_change: Callable | None = None, allow_negative: bool = False, **kwargs):
        self._user_on_change = on_change
        self._allow_negative = allow_negative
        kwargs.setdefault("keyboard_type", ft.KeyboardType.NUMBER)
        super().__init__(*args, on_change=self._sanitize_and_forward, **kwargs)

    def _sanitize(self, text: str) -> str:
        out: list[str] = []
        seen_dot = False
        for i, ch in enumerate(text):
            if ch.isdigit():
                out.append(ch)
            elif ch == "." and not seen_dot:
                seen_dot = True
                out.append(ch)
            elif ch == "-" and self._allow_negative and i == 0 and "-" not in out:
                out.append(ch)
            # anything else (letters, second '.', spaces, symbols) is dropped
        return "".join(out)

    def _sanitize_and_forward(self, e: ft.ControlEvent) -> None:
        cleaned = self._sanitize(self.value or "")
        if cleaned != (self.value or ""):
            self.value = cleaned
            self.update()
        if self._user_on_change:
            self._user_on_change(e)


__all__ = ["SmartAmountField"]
