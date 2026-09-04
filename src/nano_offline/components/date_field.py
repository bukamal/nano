from __future__ import annotations

from datetime import date, datetime
from typing import Callable

import flet as ft

from nano_offline.components.text_field import SelectAllTextField
from nano_offline.core.theme import Colors


class SmartDateField(SelectAllTextField):
    """A :class:`SelectAllTextField` specialised for date entry.

    Every date field in the app used to be a bare text box where the
    user had to type an ISO date (``YYYY-MM-DD``) by hand -- easy to
    mistype (day/month swapped, wrong separator) with nothing catching
    it before it hits storage/reports. This adds a calendar-icon button
    that opens the native date picker and writes the chosen date back in
    the same ``YYYY-MM-DD`` format every call site already expects, so
    no downstream parsing changes. Typing a date by hand still works
    exactly as before -- the picker is an addition, not a replacement.

    Takes over the field's suffix slot for the calendar button (like
    :class:`SmartAmountField`, this intentionally skips the base class's
    auto clear button -- re-opening the picker and choosing a different
    date is the natural way to change a date field).
    """

    def __init__(
        self,
        *args,
        on_change: Callable | None = None,
        first_date: date | None = None,
        last_date: date | None = None,
        **kwargs,
    ):
        self._user_on_change = on_change
        self._picker = ft.DatePicker(
            on_change=self._date_picked,
            first_date=first_date or date(2015, 1, 1),
            last_date=last_date or date(2035, 12, 31),
        )
        self._picker_mounted = False
        kwargs["suffix"] = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
            icon_size=18,
            icon_color=Colors.PRIMARY,
            on_click=self._open_picker,
            width=32,
            height=32,
            tooltip="اختيار من التقويم",
        )
        kwargs.setdefault("keyboard_type", ft.KeyboardType.DATETIME)
        super().__init__(*args, on_change=self._forward_change, **kwargs)

    def _forward_change(self, e: ft.ControlEvent) -> None:
        if self._user_on_change:
            self._user_on_change(e)

    def _open_picker(self, _=None) -> None:
        if not self._picker_mounted:
            self.page.overlay.append(self._picker)
            self._picker_mounted = True
            # The client doesn't know this control exists until a page.update()
            # actually pushes it down -- calling page.open() right after
            # overlay.append() sets open=True on a control the client hasn't
            # received yet, so nothing appears. It only shows up later once
            # some unrelated update (e.g. switching tabs) finally syncs the
            # full tree. Force that sync here, before opening, so the picker
            # shows on the very first tap.
            self.page.update()
        try:
            self._picker.value = date.fromisoformat((self.value or "")[:10])
        except ValueError:
            pass
        self.page.open(self._picker)

    def _date_picked(self, _=None) -> None:
        picked = self._picker.value
        if picked is None:
            return
        picked_date = picked.date() if isinstance(picked, datetime) else picked
        self.value = picked_date.isoformat()
        # self.update() alone leaves the field showing its old value until
        # something else (like switching tabs) forces a full page refresh --
        # the DatePicker overlay closing seems to race with a lone control
        # update. page.update() is what every other refresh path in this
        # app already relies on, and it reliably repaints the field right
        # after a date is picked.
        self.page.update()
        if self._user_on_change:
            self._user_on_change(None)


__all__ = ["SmartDateField"]
