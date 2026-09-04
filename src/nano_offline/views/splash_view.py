from __future__ import annotations

import asyncio
import time

import flet as ft

from nano_offline.version import APP_VERSION
from nano_offline.core.theme import Colors, Shadow


class SplashGate:
    """Branded loading screen shown once at cold start.

    Sits *before* both ``ActivationGate`` and ``LoginGate`` -- whichever one
    ``main()`` decides to show next is decided while this is on screen, so
    the very first frame the user sees is a live, breathing brand moment
    instead of a blank flash while SQLite opens/migrates, the license file
    is parsed, and a saved session is restored. Purely presentational: it
    owns no app state and makes no decisions -- it just holds the screen
    for a minimum, intentional beat and then hands off via ``on_ready``.
    """

    # Floor on how long the splash stays up, so on fast devices where the
    # startup checks resolve near-instantly it still reads as a deliberate
    # brand beat rather than a one-frame flicker.
    MIN_DISPLAY_SECONDS = 1.1

    _MESSAGES = [
        "جارٍ التحقق من الترخيص...",
        "جارٍ تحميل البيانات المحلية...",
        "جارٍ تجهيز الواجهة...",
    ]

    def __init__(self, page: ft.Page, *, on_ready):
        self.page = page
        self.on_ready = on_ready
        self._alive = True

        icon_inner = ft.Container(
            ft.Image(src="icon.png", width=68, height=68, fit=ft.ImageFit.CONTAIN),
            width=104,
            height=104,
            alignment=ft.alignment.center,
            bgcolor=Colors.WHITE,
            border_radius=30,
            shadow=ft.BoxShadow(blur_radius=16, spread_radius=0, color=Colors.BORDER, offset=ft.Offset(0, 4)),
        )
        self._icon_badge = ft.Container(
            icon_inner,
            width=120,
            height=120,
            alignment=ft.alignment.center,
            border_radius=34,
            gradient=ft.LinearGradient(
                colors=[Colors.PRIMARY, Colors.PURPLE_LIGHT],
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
            ),
            shadow=ft.BoxShadow(blur_radius=32, spread_radius=2, color=Colors.PRIMARY_BORDER, offset=ft.Offset(0, 12)),
            opacity=0,
            scale=0.9,
            animate_opacity=ft.Animation(420, ft.AnimationCurve.EASE_OUT),
            animate_scale=ft.Animation(900, ft.AnimationCurve.EASE_IN_OUT),
        )

        self._title = ft.Text(
            "Nano | نانو",
            size=26,
            weight=ft.FontWeight.BOLD,
            color=Colors.PRIMARY_DARK,
            opacity=0,
            animate_opacity=ft.Animation(420, ft.AnimationCurve.EASE_OUT),
        )
        self._subtitle = ft.Text(
            "نظام المحاسبة الذكي دون اتصال",
            size=12,
            color=Colors.TEXT_SECONDARY,
            opacity=0,
            animate_opacity=ft.Animation(420, ft.AnimationCurve.EASE_OUT),
        )

        self._ring = ft.ProgressRing(width=22, height=22, stroke_width=3, color=Colors.PRIMARY)
        self._status_text = ft.Text(self._MESSAGES[0], size=11, color=Colors.TEXT_FAINT)
        self._status_row = ft.Container(
            ft.Row(
                [self._ring, self._status_text],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            opacity=0,
            animate_opacity=ft.Animation(420, ft.AnimationCurve.EASE_OUT),
        )

        self._version_text = ft.Text(f"الإصدار {APP_VERSION}", size=10, color=Colors.TEXT_FAINT, opacity=0, animate_opacity=ft.Animation(420, ft.AnimationCurve.EASE_OUT))

        self._card = ft.Column(
            [
                self._icon_badge,
                ft.Container(height=8),
                self._title,
                self._subtitle,
                ft.Container(height=22),
                self._status_row,
            ],
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self._root = ft.Container(
            ft.Column(
                [
                    ft.Container(expand=True),
                    self._card,
                    ft.Container(expand=True),
                    self._version_text,
                    ft.Container(height=22),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            ),
            expand=True,
            padding=16,
            alignment=ft.alignment.center,
            gradient=ft.LinearGradient(
                colors=[Colors.PRIMARY_BG, Colors.BACKGROUND, Colors.BACKGROUND],
                begin=ft.alignment.top_center,
                end=ft.alignment.bottom_center,
            ),
        )

    def show(self) -> None:
        self.page.add(self._root)
        self.page.update()
        # kick the entrance transition on the next frame
        self._icon_badge.opacity = 1
        self._icon_badge.scale = 1
        self._title.opacity = 1
        self._subtitle.opacity = 1
        self._status_row.opacity = 1
        self._version_text.opacity = 1
        self.page.update()
        self.page.run_task(self._run)

    def dismiss(self) -> None:
        """Stop the breathing/message loop early (e.g. app shutdown)."""
        self._alive = False

    async def _run(self) -> None:
        start = time.monotonic()
        msg_idx = 0
        pulse_up = True
        # Alternates the badge's gentle breathing pulse and cycles the
        # status line while the minimum display window is still open --
        # both are purely cosmetic and simply stop once the window closes,
        # whatever real work the caller does in parallel/after on_ready.
        while self._alive and (time.monotonic() - start) < self.MIN_DISPLAY_SECONDS:
            self._icon_badge.scale = 1.06 if pulse_up else 1.0
            pulse_up = not pulse_up
            msg_idx = (msg_idx + 1) % len(self._MESSAGES)
            self._status_text.value = self._MESSAGES[msg_idx]
            self.page.update()
            await asyncio.sleep(0.42)

        if not self._alive:
            return
        self._alive = False
        self.on_ready()


__all__ = ["SplashGate"]
