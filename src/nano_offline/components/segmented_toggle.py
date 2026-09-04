from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import flet as ft

from nano_offline.core.theme import Colors


@dataclass(frozen=True, slots=True)
class SegmentOption:
    key: str
    label: str
    icon: str | None = None


class SegmentedToggle(ft.Row):
    """Pill-style segmented control for a small, fixed set of choices.

    Built for cases like "العملة المعروضة" (2-3 options) where a
    text-field-based ``SearchSelect`` is overkill and feels dated --
    tapping the right chip is faster than typing/searching to pick between
    two currencies. Exposes the same minimal ``value``/``on_change`` shape
    as ``SearchSelect`` so it drops into existing forms without touching
    the surrounding save/read logic.
    """

    def __init__(
        self,
        *,
        options: Iterable[SegmentOption | tuple[str, str] | tuple[str, str, str]],
        value: str | None = None,
        on_change: Callable | None = None,
        label: str | None = None,
    ):
        self._options: list[SegmentOption] = [
            o if isinstance(o, SegmentOption) else SegmentOption(*o) for o in options
        ]
        self._value: str | None = value
        self._on_change = on_change
        self._label = label
        self._chips: dict[str, ft.Container] = {}
        # NOTE: no wrap=True here. Flutter's Wrap (what a wrapping ft.Row
        # renders as) cannot host Expanded/Flexible children, and each chip
        # below uses expand=True so the options split the row evenly --
        # combining the two crashes the render (that crash is exactly what
        # showed up as an unrelated-looking blank gray box swallowing the
        # rest of the page). A plain non-wrapping Row is what we want here
        # anyway: 2-3 short chips always fit on one line.
        super().__init__(controls=list(self._build_chips()), spacing=8)

    def _build_chips(self):
        for option in self._options:
            chip = self._chip(option)
            self._chips[option.key] = chip
            yield chip

    def _chip(self, option: SegmentOption) -> ft.Container:
        active = option.key == self._value
        row_items: list[ft.Control] = []
        if option.icon:
            row_items.append(ft.Icon(option.icon, size=16, color=Colors.WHITE if active else Colors.TEXT_MUTED))
        row_items.append(
            ft.Text(
                option.label,
                size=13,
                color=Colors.WHITE if active else Colors.TEXT_MUTED,
                weight=ft.FontWeight.BOLD if active else ft.FontWeight.W_500,
            )
        )
        return ft.Container(
            content=ft.Row(row_items, spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=16, vertical=11),
            bgcolor=Colors.PRIMARY if active else Colors.WHITE,
            border=ft.border.all(1, Colors.PRIMARY if active else Colors.BORDER),
            border_radius=14,
            ink=True,
            expand=True,
            animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
            on_click=lambda _, k=option.key: self._select(k),
        )

    def _select(self, key: str) -> None:
        if key == self._value:
            return
        self._value = key
        self._refresh_styles()
        self._safe_update()
        if self._on_change:
            self._on_change(None)

    def _refresh_styles(self) -> None:
        for option in self._options:
            active = option.key == self._value
            chip = self._chips[option.key]
            row = chip.content
            row.controls[-1].color = Colors.WHITE if active else Colors.TEXT_MUTED
            row.controls[-1].weight = ft.FontWeight.BOLD if active else ft.FontWeight.W_500
            if option.icon:
                row.controls[0].color = Colors.WHITE if active else Colors.TEXT_MUTED
            chip.bgcolor = Colors.PRIMARY if active else Colors.WHITE
            chip.border = ft.border.all(1, Colors.PRIMARY if active else Colors.BORDER)

    def _safe_update(self) -> None:
        try:
            self.update()
        except Exception:
            pass

    @property
    def value(self) -> str | None:
        return self._value

    @value.setter
    def value(self, key: str | None) -> None:
        self._value = key
        self._refresh_styles()

    @property
    def on_change(self):
        return self._on_change

    @on_change.setter
    def on_change(self, callback) -> None:
        self._on_change = callback


__all__ = ["SegmentedToggle", "SegmentOption"]
