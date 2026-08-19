from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import flet as ft


@dataclass(frozen=True, slots=True)
class SearchChoice:
    key: str
    label: str


class SearchSelect(ft.Column):
    """Text-field based searchable selector.

    It intentionally avoids Dropdown so selection remains usable on Android
    keyboards and long Arabic datasets. The selected machine value is exposed
    through ``value`` while the field shows the human label.
    """

    def __init__(
        self,
        *,
        label: str,
        choices: Iterable[tuple[str, str]] = (),
        value: str | None = None,
        hint_text: str | None = "اكتب للبحث والاختيار",
        allow_clear: bool = True,
        max_results: int = 6,
        on_change: Callable | None = None,
    ):
        self._label = label
        self._choices: list[SearchChoice] = []
        self._value: str | None = None
        self._on_change = on_change
        self.allow_clear = allow_clear
        self.max_results = max(1, int(max_results))
        self.field = ft.TextField(
            label=label,
            hint_text=hint_text,
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._field_changed,
            on_focus=self._field_focused,
        )
        self.results = ft.Column(spacing=0, tight=True)
        self.results_box = ft.Container(
            content=self.results,
            visible=False,
            padding=4,
            border=ft.border.all(1, "#E2E8F0"),
            border_radius=10,
            bgcolor="#FFFFFF",
        )
        super().__init__([self.field, self.results_box], spacing=3, tight=True)
        self.set_choices(choices, preserve_value=False)
        self.value = value

    @property
    def label(self) -> str:
        return self._label

    @label.setter
    def label(self, value: str) -> None:
        self._label = value
        self.field.label = value

    @property
    def value(self) -> str | None:
        return self._value

    @value.setter
    def value(self, key: str | None) -> None:
        normalized = str(key) if key not in (None, "") else None
        self._value = normalized
        label = self._label_for(normalized) if normalized else ""
        self.field.value = label or ""
        self.results_box.visible = False

    @property
    def on_change(self):
        return self._on_change

    @on_change.setter
    def on_change(self, callback) -> None:
        self._on_change = callback

    def set_choices(self, choices: Iterable[tuple[str, str]], *, preserve_value: bool = True) -> None:
        previous = self._value if preserve_value else None
        self._choices = [SearchChoice(str(key), str(label)) for key, label in choices]
        if previous and any(c.key == previous for c in self._choices):
            self.value = previous
        elif not preserve_value:
            self._value = None
            self.field.value = ""
        elif previous:
            self.value = None
        self._render_results("")

    def select_first(self) -> None:
        if self._choices:
            self.value = self._choices[0].key

    def _label_for(self, key: str | None) -> str | None:
        if key is None:
            return None
        for choice in self._choices:
            if choice.key == str(key):
                return choice.label
        return None

    def _safe_update(self) -> None:
        try:
            self.update()
        except Exception:
            pass

    def _field_focused(self, _=None) -> None:
        self._render_results((self.field.value or "").strip())
        self.results_box.visible = bool(self.results.controls)
        self._safe_update()

    def _field_changed(self, _=None) -> None:
        typed = (self.field.value or "").strip()
        previous = self._value
        # Editing after a selection invalidates the key until a suggestion is chosen.
        if self._value and typed != (self._label_for(self._value) or ""):
            self._value = None
        exact = [c for c in self._choices if c.label.casefold() == typed.casefold()] if typed else []
        if len(exact) == 1:
            self._value = exact[0].key
        self._render_results(typed)
        self.results_box.visible = bool(self.results.controls)
        self._safe_update()
        if previous != self._value and self._on_change:
            self._on_change(None)

    def _render_results(self, query: str) -> None:
        q = (query or "").casefold()
        matches = [c for c in self._choices if not q or q in c.label.casefold()][: self.max_results]
        controls: list[ft.Control] = []
        if self.allow_clear and not q:
            controls.append(
                ft.TextButton(
                    "بدون اختيار",
                    icon=ft.Icons.CLEAR,
                    on_click=lambda _: self._choose(None),
                )
            )
        for choice in matches:
            controls.append(
                ft.ListTile(
                    title=ft.Text(choice.label, size=14),
                    dense=True,
                    on_click=lambda _, c=choice: self._choose(c),
                )
            )
        if q and not matches:
            controls.append(ft.Container(ft.Text("لا توجد نتائج", size=12, color="#64748B"), padding=8))
        self.results.controls = controls

    def _choose(self, choice: SearchChoice | None) -> None:
        self._value = choice.key if choice else None
        self.field.value = choice.label if choice else ""
        self.results_box.visible = False
        self._safe_update()
        if self._on_change:
            self._on_change(None)


__all__ = ["SearchSelect", "SearchChoice"]
