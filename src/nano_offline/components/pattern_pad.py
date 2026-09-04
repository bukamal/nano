from __future__ import annotations

import asyncio
import math

import flet as ft
import flet.canvas as cv

from nano_offline.core.theme import Colors

_MIN_NODES = 4
_MAX_NODES = 9
_GRID_SIZE = 252.0
_PADDING = 36.0
_GAP = (_GRID_SIZE - 2 * _PADDING) / 2
_HIT_RADIUS = 30.0
_RING_RADIUS = 13.0
_DOT_RADIUS = 4.0
_SELECTED_RADIUS = 10.0
_HALO_RADIUS = 22.0
_ERROR_FLASH_SECONDS = 0.32


class PatternPad(ft.Container):
    """Draw-to-connect pattern lock (3x3 dots), matching Android/iOS gesture UX.

    The persisted secret is the ordered node sequence ("1".."9"), never pixel
    coordinates -- identical wire format to the previous tap-grid version, so
    this is a drop-in replacement for every existing call site.
    """

    def __init__(self, *, on_change=None, on_complete=None):
        self._on_change = on_change
        self._on_complete = on_complete
        self._nodes: dict[str, tuple[float, float]] = {}
        node_id = 1
        for row in range(3):
            for col in range(3):
                x = _PADDING + col * _GAP
                y = _PADDING + row * _GAP
                self._nodes[str(node_id)] = (x, y)
                node_id += 1

        self._sequence: list[str] = []
        self._drag_point: tuple[float, float] | None = None
        self._dragging = False
        self._error = False

        self.status = ft.Text("اسحب إصبعك لرسم النمط", size=12, color=Colors.TEXT_SECONDARY, text_align=ft.TextAlign.CENTER)
        self.canvas = cv.Canvas(
            width=_GRID_SIZE,
            height=_GRID_SIZE,
            shapes=self._build_shapes(),
            content=ft.GestureDetector(
                width=_GRID_SIZE,
                height=_GRID_SIZE,
                drag_interval=16,
                mouse_cursor=ft.MouseCursor.CLICK,
                on_pan_start=self._on_pan_start,
                on_pan_update=self._on_pan_update,
                on_pan_end=self._on_pan_end,
            ),
        )
        self.clear_button = ft.TextButton("مسح النمط", icon=ft.Icons.REFRESH, on_click=lambda _: self.clear())

        board = ft.Container(
            self.canvas,
            width=_GRID_SIZE,
            height=_GRID_SIZE,
            padding=6,
            bgcolor=Colors.BACKGROUND_ALT,
            border=ft.border.all(1, Colors.BORDER),
            border_radius=20,
        )

        super().__init__(
            content=ft.Column(
                [self.status, board, self.clear_button],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            alignment=ft.alignment.center,
        )

    # -- public API (unchanged from the tap-grid version) -----------------

    @property
    def value(self) -> str:
        return "".join(self._sequence)

    def clear(self) -> None:
        self._sequence.clear()
        self._drag_point = None
        self._dragging = False
        self._error = False
        self.status.value = "اسحب إصبعك لرسم النمط"
        self.status.color = Colors.TEXT_SECONDARY
        self._redraw()
        if self._on_change:
            self._on_change(self.value)

    # -- geometry -----------------------------------------------------------

    def _hit_test(self, point: tuple[float, float]) -> str | None:
        px, py = point
        best_id, best_dist = None, _HIT_RADIUS
        for node_id, (nx, ny) in self._nodes.items():
            dist = math.hypot(px - nx, py - ny)
            if dist <= best_dist:
                best_id, best_dist = node_id, dist
        return best_id

    # -- gesture handlers -----------------------------------------------------

    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        # NOTE: DragStartEvent/DragUpdateEvent expose flat `local_x`/`local_y`
        # floats in Flet 0.28.x -- there is no `local_position` attribute.
        # Reading `e.local_position.x/.y` raised an AttributeError on every
        # touch, which Flet's event dispatcher swallowed silently, so the
        # pad looked like it just never drew anything.
        point = (e.local_x, e.local_y)
        self._sequence.clear()
        self._error = False
        self._dragging = True
        node = self._hit_test(point)
        if node:
            self._sequence.append(node)
        self._drag_point = point
        self.status.value = "تابع الرسم..."
        self.status.color = Colors.TEXT_SECONDARY
        self._redraw()

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        if not self._dragging:
            return
        point = (e.local_x, e.local_y)
        self._drag_point = point
        node = self._hit_test(point)
        if node and node not in self._sequence and len(self._sequence) < _MAX_NODES:
            self._sequence.append(node)
            if self._on_change:
                self._on_change(self.value)
        self._redraw()

    async def _on_pan_end(self, e: ft.DragEndEvent) -> None:
        self._dragging = False
        self._drag_point = None
        if len(self._sequence) < _MIN_NODES:
            self._error = True
            self.status.value = "نمط قصير جدًا -- التزم بأربع نقاط على الأقل"
            self.status.color = Colors.DANGER
            self._redraw()
            if self._on_change:
                self._on_change(self.value)
            await asyncio.sleep(_ERROR_FLASH_SECONDS)
            self._sequence.clear()
            self._error = False
            self.status.value = "اسحب إصبعك لرسم النمط"
            self.status.color = Colors.TEXT_SECONDARY
            self._redraw()
            if self._on_change:
                self._on_change(self.value)
            return
        self.status.value = f"تم رسم {len(self._sequence)} نقاط"
        self.status.color = Colors.SUCCESS
        self._redraw()
        if self._on_change:
            self._on_change(self.value)
        if self._on_complete:
            self._on_complete(self.value)

    # -- rendering -----------------------------------------------------------

    def _redraw(self) -> None:
        self.canvas.shapes = self._build_shapes()
        try:
            self.canvas.update()
        except Exception:
            pass

    def _build_shapes(self) -> list:
        line_color = Colors.DANGER if self._error else Colors.PRIMARY
        dot_color = Colors.DANGER if self._error else Colors.PRIMARY
        halo_color = ft.Colors.with_opacity(0.16, dot_color)
        shapes: list = []

        # connecting lines between confirmed nodes
        for a, b in zip(self._sequence, self._sequence[1:]):
            ax, ay = self._nodes[a]
            bx, by = self._nodes[b]
            shapes.append(cv.Line(ax, ay, bx, by, paint=ft.Paint(color=line_color, stroke_width=5, stroke_cap=ft.StrokeCap.ROUND)))

        # live trailing line following the finger/pointer while dragging
        if self._dragging and self._sequence and self._drag_point:
            lx, ly = self._nodes[self._sequence[-1]]
            dx, dy = self._drag_point
            shapes.append(cv.Line(lx, ly, dx, dy, paint=ft.Paint(color=line_color, stroke_width=5, stroke_cap=ft.StrokeCap.ROUND)))

        # dots
        for node_id, (x, y) in self._nodes.items():
            if node_id in self._sequence:
                shapes.append(cv.Circle(x, y, _HALO_RADIUS, paint=ft.Paint(color=halo_color, style=ft.PaintingStyle.FILL)))
                shapes.append(cv.Circle(x, y, _SELECTED_RADIUS, paint=ft.Paint(color=dot_color, style=ft.PaintingStyle.FILL)))
            else:
                shapes.append(
                    cv.Circle(x, y, _RING_RADIUS, paint=ft.Paint(color=Colors.BORDER_STRONG, style=ft.PaintingStyle.STROKE, stroke_width=2))
                )
                shapes.append(cv.Circle(x, y, _DOT_RADIUS, paint=ft.Paint(color=Colors.BORDER_STRONG, style=ft.PaintingStyle.FILL)))
        return shapes


__all__ = ["PatternPad"]
