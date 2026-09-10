"""In-app continuous voice session — «مكالمة صوتية» while Nano is open.

Not a true Android background service (that would need a foreground
notification and drains battery). This is a *foreground* session:
  • user starts it from the floating call chip
  • the app keeps listen → parse → execute → listen until they say
    «إيقاف» or tap the red hang-up control
  • survives section changes (dashboard → POS → items) because state
    lives on the shell, not on a single view

Wiring (main.build_shell):
    session = VoiceSessionController(page, ctx, navigate=navigate, ...)
    page.overlay.append(session.banner)
    session.attach_fab()  # optional floating action
"""

from __future__ import annotations

import threading
from typing import Callable

import flet as ft

from nano_offline.core import voice_command as voice_cmd
from nano_offline.core.theme import Colors
from nano_offline.core.toast import toast


class VoiceSessionController:
    def __init__(
        self,
        page: ft.Page,
        ctx,
        *,
        navigate: Callable[[str], None],
        notify: Callable[..., None] | None = None,
    ) -> None:
        self.page = page
        self.ctx = ctx
        self.navigate = navigate
        self.notify = notify or (lambda text, **kw: toast(page, text, **kw))

        self.active = False
        self.listening = False
        self._status = ft.Text("جلسة صوتية", size=12, weight=ft.FontWeight.W_600, color=Colors.WHITE)
        self._hint = ft.Text("قل أمراً… أو «إيقاف»", size=10, color=Colors.WHITE)
        self._pulse = ft.Icon(ft.Icons.GRAPHIC_EQ, size=18, color=Colors.WHITE)

        hang = ft.Container(
            ft.Icon(ft.Icons.CALL_END_ROUNDED, size=18, color=Colors.WHITE),
            width=36,
            height=36,
            alignment=ft.alignment.center,
            bgcolor="#B91C1C",
            border_radius=18,
            on_click=lambda e: self.stop(reason="ended"),
            ink=True,
            tooltip="إنهاء الجلسة الصوتية",
        )

        self.banner = ft.Container(
            content=ft.Row(
                [
                    self._pulse,
                    ft.Column([self._status, self._hint], spacing=1, expand=True),
                    hang,
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            bgcolor=Colors.PRIMARY,
            border_radius=16,
            visible=False,
            animate_opacity=200,
            shadow=ft.BoxShadow(blur_radius=12, color="#40000000", offset=ft.Offset(0, 4)),
        )

        self.fab = ft.FloatingActionButton(
            icon=ft.Icons.PHONE_IN_TALK_ROUNDED,
            bgcolor=Colors.PRIMARY,
            foreground_color=Colors.WHITE,
            tooltip="بدء مكالمة أوامر صوتية",
            on_click=self.toggle,
            visible=True,
        )

    # -- public API ------------------------------------------------------

    def toggle(self, _e=None) -> None:
        if self.active:
            self.stop(reason="toggle")
        else:
            self.start()

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        self.banner.visible = True
        self.banner.bgcolor = Colors.PRIMARY
        self._status.value = "مكالمة صوتية نشطة"
        self._hint.value = "يستمع… أعطِ أوامرك"
        self.fab.icon = ft.Icons.CALL_END_ROUNDED
        self.fab.bgcolor = Colors.DANGER if hasattr(Colors, "DANGER") else "#DC2626"
        self.fab.tooltip = "إنهاء المكالمة الصوتية"
        self._safe_update()
        self.notify("بدأت المكالمة الصوتية — قل أوامرك. قل «إيقاف» للإنهاء", kind="info")
        self._listen()

    def stop(self, reason: str = "stop") -> None:
        self.active = False
        self.listening = False
        try:
            voice_cmd.cancel()
        except Exception:
            pass
        self.banner.visible = False
        self.fab.icon = ft.Icons.PHONE_IN_TALK_ROUNDED
        self.fab.bgcolor = Colors.PRIMARY
        self.fab.tooltip = "بدء مكالمة أوامر صوتية"
        self._safe_update()
        if reason != "silent":
            self.notify("انتهت المكالمة الصوتية", kind="info")

    # -- listen loop -----------------------------------------------------

    def _listen(self) -> None:
        if not self.active or self.listening:
            return
        self.listening = True
        self._hint.value = "يستمع…"
        self.banner.bgcolor = Colors.DANGER if hasattr(Colors, "DANGER") else "#DC2626"
        self._safe_update()

        def on_final(text: str):
            self.listening = False
            text = (text or "").strip()
            if not text:
                self._schedule_relisten(0.5)
                return
            self._hint.value = f"«{text}»"
            self.banner.bgcolor = Colors.PRIMARY
            self._safe_update()
            self._execute(text)

        def on_error(msg: str):
            self.listening = False
            self._hint.value = (msg or "…")[:60]
            self.banner.bgcolor = Colors.PRIMARY
            self._safe_update()
            soft = any(
                x in (msg or "")
                for x in ("لم يُلتقط", "لم يُفهم", "انتهى وقت", "NO_MATCH", "SPEECH_TIMEOUT", "timeout", "permission")
            )
            if self.active and soft:
                self._schedule_relisten(0.9)
            elif self.active and "permission" in (msg or "").lower():
                self.stop(reason="permission")
            elif self.active:
                self._schedule_relisten(1.2)

        def on_partial(text: str):
            if text:
                self._hint.value = text[:40]
                self._safe_update()

        try:
            voice_cmd.listen_once(
                language="ar-SY",
                on_partial=on_partial,
                on_final=on_final,
                on_error=on_error,
                timeout_sec=8.0,
            )
        except Exception as exc:
            on_error(str(exc))

    def _schedule_relisten(self, delay: float) -> None:
        if not self.active:
            return

        def _go():
            if self.active and not self.listening:
                self._listen()

        threading.Timer(max(0.3, delay), _go).start()

    def _execute(self, text: str) -> None:
        try:
            result = self.ctx.quick_commands.parse(text)
        except Exception as exc:
            self.notify(str(exc), kind="error")
            self._schedule_relisten(0.6)
            return

        action = result.action
        if action == "voice_stop":
            self.stop(reason="voice")
            return

        if action in ("pos_add", "pos_pay", "pos_clear"):
            try:
                setattr(self.ctx, "_pending_voice_command", result)
            except Exception:
                pass
            try:
                self.navigate("pos")
            except Exception as exc:
                self.notify(str(exc), kind="error")
            # POS will consume pending; keep session alive
            self._schedule_relisten(1.0)
            return

        if action == "navigate" and result.target:
            try:
                self.navigate(result.target)
                self.notify(result.message or f"فتح {result.target}", kind="success")
            except Exception as exc:
                self.notify(str(exc), kind="error")
            self._schedule_relisten(0.7)
            return

        if action == "crisis_on":
            try:
                self.ctx.crisis_mode.activate(freeze_current_rate=True)
                self.notify("تم تفعيل وضع الطوارئ", kind="warning")
            except Exception as exc:
                self.notify(str(exc), kind="error")
            self._schedule_relisten(0.7)
            return

        if action == "crisis_off":
            try:
                self.ctx.crisis_mode.deactivate()
                self.notify("تم إلغاء وضع الطوارئ", kind="success")
            except Exception as exc:
                self.notify(str(exc), kind="error")
            self._schedule_relisten(0.7)
            return

        if action in ("query", "message"):
            self.notify(result.message or text, kind="info")
            self._schedule_relisten(0.7)
            return

        self.notify(result.message or "لم يُنفَّذ الأمر", kind="warning")
        self._schedule_relisten(0.7)

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass


__all__ = ["VoiceSessionController"]
