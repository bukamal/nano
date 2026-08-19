from __future__ import annotations

import flet as ft


class PatternPad(ft.Column):
    """Simple 3x3 tap pattern pad using nodes 1..9.

    The persisted secret is the ordered node sequence, never the visual labels.
    """

    def __init__(self, *, on_change=None):
        self.sequence: list[str] = []
        self._on_change = on_change
        self.indicator = ft.Text("لم يتم إدخال نمط", size=12, color="#64748B", text_align=ft.TextAlign.CENTER)
        rows: list[ft.Control] = []
        for start in (1, 4, 7):
            buttons = []
            for number in range(start, start + 3):
                buttons.append(
                    ft.OutlinedButton(
                        str(number),
                        width=72,
                        height=56,
                        on_click=lambda _, n=str(number): self._tap(n),
                    )
                )
            rows.append(ft.Row(buttons, alignment=ft.MainAxisAlignment.CENTER, spacing=10))
        self.clear_button = ft.TextButton("مسح النمط", icon=ft.Icons.REFRESH, on_click=lambda _: self.clear())
        super().__init__([self.indicator, *rows, self.clear_button], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    @property
    def value(self) -> str:
        return "".join(self.sequence)

    def _safe_update(self) -> None:
        try:
            self.update()
        except Exception:
            pass

    def _tap(self, node: str) -> None:
        if node in self.sequence or len(self.sequence) >= 9:
            return
        self.sequence.append(node)
        self.indicator.value = "النمط: " + "  →  ".join("●" for _ in self.sequence)
        self._safe_update()
        if self._on_change:
            self._on_change(self.value)

    def clear(self) -> None:
        self.sequence.clear()
        self.indicator.value = "لم يتم إدخال نمط"
        self._safe_update()
        if self._on_change:
            self._on_change(self.value)


__all__ = ["PatternPad"]
