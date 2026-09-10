"""In-app continuous voice session — modern «مكالمة ذكية» while Nano is open.

Foreground only (not an OS background service). Features:
  • Glass-style call card with live status + last transcript chips
  • Context-aware routing (current section from shell)
  • Short multi-turn memory hooks
  • Soft help and fuzzy POS item add when already in POS
  • Continuous listen loop until hang-up / «إيقاف»
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import flet as ft

from nano_offline.core import voice_command as voice_cmd
from nano_offline.core.theme import Colors, Shadow
from nano_offline.core.toast import toast


@dataclass
class Turn:
    role: str  # user | nano
    text: str
    at: float = field(default_factory=time.time)


class VoiceSessionController:
    def __init__(
        self,
        page: ft.Page,
        ctx,
        *,
        navigate: Callable[[str], None],
        notify: Callable[..., None] | None = None,
        get_section: Callable[[], str] | None = None,
        native_files=None,
        tts_enabled: bool = True,
    ) -> None:
        self.page = page
        self.ctx = ctx
        self.navigate = navigate
        self.notify = notify or (lambda text, **kw: toast(page, text, **kw))
        self.get_section = get_section or (lambda: "dashboard")
        self.native_files = native_files
        self.tts_enabled = tts_enabled

        self.active = False
        self.listening = False
        self.turns: list[Turn] = []
        self._pending_followup: dict[str, Any] | None = None
        self._pending_confirm: dict[str, Any] | None = None
        self._last_command: str = ""

        self._status = ft.Text("مكالمة ذكية", size=13, weight=ft.FontWeight.BOLD, color=Colors.WHITE)
        self._hint = ft.Text("قل «مساعدة» لعرض الأوامر", size=11, color=Colors.WHITE, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self._section_chip = ft.Text("", size=10, color=Colors.WHITE)
        self._wave = ft.Icon(ft.Icons.AUTO_AWESOME, size=22, color=Colors.WHITE)
        self._chip_row = ft.Row(spacing=6, wrap=True, tight=True)

        hang = ft.Container(
            ft.Icon(ft.Icons.CALL_END_ROUNDED, size=20, color=Colors.WHITE),
            width=40, height=40, alignment=ft.alignment.center,
            bgcolor="#991B1B", border_radius=20,
            on_click=lambda e: self.stop(reason="ended"), ink=True, tooltip="إنهاء المكالمة",
        )
        help_btn = ft.Container(
            ft.Icon(ft.Icons.HELP_OUTLINE_ROUNDED, size=18, color=Colors.WHITE),
            width=36, height=36, alignment=ft.alignment.center,
            bgcolor="#FFFFFF22", border_radius=18,
            on_click=lambda e: self._show_help(), ink=True, tooltip="الأوامر المتاحة",
        )

        self.banner = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._wave,
                            ft.Column(
                                [ft.Row([self._status, self._section_chip], spacing=8, tight=True), self._hint],
                                spacing=2, expand=True,
                            ),
                            help_btn,
                            hang,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._chip_row,
                ],
                spacing=8,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            gradient=ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=["#0B63F6", "#1AD8D1"],
            ),
            border_radius=20,
            visible=False,
            animate_opacity=180,
            shadow=ft.BoxShadow(blur_radius=18, color="#40000000", offset=ft.Offset(0, 6)),
        )

        self.fab = ft.FloatingActionButton(
            icon=ft.Icons.AUTO_AWESOME,
            bgcolor=Colors.PRIMARY,
            foreground_color=Colors.WHITE,
            tooltip="مكالمة أوامر ذكية",
            on_click=self.toggle,
            visible=True,
        )

    def toggle(self, _e=None) -> None:
        if self.active:
            self.stop(reason="toggle")
        else:
            self.start()

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        self._pending_followup = None
        self.banner.visible = True
        self._set_listening_visual(False)
        self._status.value = "مكالمة ذكية نشطة"
        self._refresh_section_chip()
        self._hint.value = self._greeting()
        self.fab.icon = ft.Icons.CALL_END_ROUNDED
        self.fab.bgcolor = Colors.DANGER
        self.fab.tooltip = "إنهاء المكالمة"
        self._push_turn("nano", self._hint.value)
        self._safe_update()
        self.notify(self._hint.value, kind="info")
        self._listen()

    def stop(self, reason: str = "stop") -> None:
        self.active = False
        self.listening = False
        self._pending_followup = None
        try:
            voice_cmd.cancel()
        except Exception:
            pass
        self.banner.visible = False
        self.fab.icon = ft.Icons.AUTO_AWESOME
        self.fab.bgcolor = Colors.PRIMARY
        self.fab.tooltip = "مكالمة أوامر ذكية"
        self._safe_update()
        if reason not in ("silent",):
            self.notify("انتهت المكالمة الذكية", kind="info")

    def _listen(self) -> None:
        if not self.active or self.listening:
            return
        self.listening = True
        self._refresh_section_chip()
        self._set_listening_visual(True)
        self._hint.value = "يستمع…"
        self._safe_update()
        # Stop any TTS so the mic does not hear Nano talking
        if self.native_files is not None:
            async def _hush():
                try:
                    await self.native_files.speech_stop_speak()
                except Exception:
                    pass
            try:
                if hasattr(self.page, "run_task"):
                    self.page.run_task(_hush)
            except Exception:
                pass

        def on_final(text: str):
            self.listening = False
            self._set_listening_visual(False)
            text = (text or "").strip()
            if not text:
                self._schedule_relisten(0.45)
                return
            self._last_command = text
            self._push_turn("user", text)
            self._hint.value = f"«{text}»"
            self._safe_update()
            self._execute(text)

        def on_error(msg: str):
            self.listening = False
            self._set_listening_visual(False)
            soft = any(
                x in (msg or "")
                for x in ("لم يُلتقط", "لم يُفهم", "انتهى وقت", "NO_MATCH", "SPEECH_TIMEOUT", "timeout", "permission")
            )
            self._hint.value = (msg or "…")[:70]
            self._safe_update()
            if not self.active:
                return
            if "permission" in (msg or "").lower() or "إذن" in (msg or ""):
                self.stop(reason="permission")
                return
            self._schedule_relisten(0.85 if soft else 1.1)

        def on_partial(text: str):
            if text:
                self._hint.value = text[:48]
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

        threading.Timer(max(0.25, delay), _go).start()

    def _execute(self, text: str) -> None:
        section = (self.get_section() or "dashboard").lower()

        # Pending confirmation (clear cart / crisis)
        if self._pending_confirm:
            if self._is_yes(text):
                pending = self._pending_confirm
                self._pending_confirm = None
                self._run_confirmed(pending)
                self._schedule_relisten(0.8)
                return
            if self._is_no(text):
                self._pending_confirm = None
                self._reply("تم الإلغاء", kind="info")
                self._schedule_relisten(0.6)
                return
            self._reply("قل نعم أو لا", kind="warning")
            self._schedule_relisten(0.6)
            return

        if self._pending_followup and self._pending_followup.get("kind") == "qty":
            qty = self._parse_qty_utterance(text)
            if qty is not None:
                name = self._pending_followup.get("name") or ""
                self._pending_followup = None
                self._do_pos_add(name, qty)
                self._schedule_relisten(0.75)
                return
            self._pending_followup = None

        if self._is_help(text):
            self._show_help()
            self._schedule_relisten(0.8)
            return

        # Natural «كم السعر» / summary while on dashboard
        if any(k in text for k in ("ملخص", "كيف الشغل", "كيف الحال", "وضع اليوم", "نبض")):
            try:
                pulse = self.ctx.owner_pulse.generate()
                self._reply(f"{pulse.headline}: {pulse.body}", kind="info")
            except Exception:
                self._reply("تعذر جلب الملخص الآن", kind="warning")
            self._schedule_relisten(0.9)
            return

        try:
            result = self.ctx.quick_commands.parse(text)
        except Exception as exc:
            self._reply(str(exc), kind="error")
            self._schedule_relisten(0.7)
            return

        action = result.action

        if action == "voice_stop":
            self.stop(reason="voice")
            return

        if action in ("pos_add", "pos_pay", "pos_clear"):
            if action == "pos_add":
                data = result.data or {}
                name = (data.get("name") or "").strip()
                qty = float(data.get("qty") or 1)
                # Ask for qty when user said only «أضف سكر» without number — optional smart prompt
                if qty == 1.0 and not any(ch.isdigit() for ch in text) and not any(
                    w in text for w in ("واحد", "اثنين", "ثلاث", "اربعة", "أربعة", "خمس")
                ):
                    # still add 1 immediately (faster cashier UX); no forced follow-up
                    pass
                self._do_pos_add(name, qty)
            elif action == "pos_clear":
                self._pending_confirm = {"kind": "pos_clear", "result": result, "section": section}
                self._reply("تأكيد تفريغ السلة؟ قل نعم أو لا", kind="warning")
                self._schedule_relisten(0.7)
                return
            else:
                self._queue_and_go_pos(result)
                self._reply("فتح الدفع", kind="success")
            self._schedule_relisten(0.9)
            return

        if action == "navigate" and result.target:
            try:
                self.navigate(result.target)
                self._reply(result.message or "تم فتح القسم", kind="success")
            except Exception as exc:
                self._reply(str(exc), kind="error")
            self._schedule_relisten(0.7)
            return

        if action == "crisis_on":
            self._pending_confirm = {"kind": "crisis_on"}
            self._reply("تأكيد تفعيل وضع الطوارئ؟ قل نعم أو لا", kind="warning")
            self._schedule_relisten(0.7)
            return

        if action == "crisis_off":
            try:
                self.ctx.crisis_mode.deactivate()
                self._reply("أُلغي وضع الطوارئ", kind="success")
            except Exception as exc:
                self._reply(str(exc), kind="error")
            self._schedule_relisten(0.7)
            return

        if action in ("query", "message"):
            self._reply(result.message or text, kind="info")
            self._schedule_relisten(0.75)
            return

        if section == "pos" and len(text) >= 2 and self._try_fuzzy_pos_add(text):
            self._schedule_relisten(0.85)
            return

        self._reply(result.message or "لم أفهم — قل «مساعدة»", kind="warning")
        self._schedule_relisten(0.75)

    def _do_pos_add(self, name: str, qty: float) -> None:
        section = (self.get_section() or "").lower()
        result = type(
            "R",
            (),
            {
                "action": "pos_add",
                "data": {"name": name, "qty": qty},
                "message": f"إضافة {name} × {qty:g}",
                "target": "pos",
                "ok": True,
            },
        )()
        if section == "pos":
            self._apply_pos(result)
        else:
            self._queue_and_go_pos(result)
        self._reply(f"أُضيف {name} × {qty:g}" if name else "تمت الإضافة", kind="success")

    def _try_fuzzy_pos_add(self, text: str) -> bool:
        try:
            rows = self.ctx.items.list(search=text.strip(), limit=5)
        except Exception:
            return False
        if not rows:
            return False
        name = str(rows[0].get("name") or "")
        self._do_pos_add(name, 1.0)
        return True

    def _queue_and_go_pos(self, result) -> None:
        try:
            setattr(self.ctx, "_pending_voice_command", result)
        except Exception:
            pass
        try:
            self.navigate("pos")
        except Exception as exc:
            self._reply(str(exc), kind="error")

    def _apply_pos(self, result) -> None:
        apply = getattr(self.ctx, "_pos_apply_voice", None)
        if callable(apply):
            try:
                apply(result)
                return
            except Exception:
                pass
        try:
            setattr(self.ctx, "_pending_voice_command", result)
        except Exception:
            pass

    def _greeting(self) -> str:
        section = (self.get_section() or "dashboard").lower()
        hints = {
            "pos": "في نقطة البيع: «أضف سكر»، أو اسم المادة مباشرة، «ادفع»",
            "stocktake": "في الجرد — قل «بيع سريع» أو «المواد»",
            "items": "قل «جرد» أو «أضف …» للبيع",
            "dashboard": "جرّب: بيع سريع، جرد، ملخص، كم باقي الأرز",
        }
        return hints.get(section, "قل أمراً… أو «مساعدة»")

    def _refresh_section_chip(self) -> None:
        labels = {
            "dashboard": "لوحة التحكم", "pos": "نقطة البيع", "stocktake": "الجرد",
            "items": "المواد", "invoices": "الفواتير", "customers": "العملاء",
            "suppliers": "الموردون", "finance": "المالية", "reports": "التقارير", "admin": "الإدارة",
        }
        sec = (self.get_section() or "dashboard").lower()
        self._section_chip.value = f"· {labels.get(sec, sec)}"

    def _set_listening_visual(self, active: bool) -> None:
        if active:
            self.banner.gradient = ft.LinearGradient(
                begin=ft.alignment.center_left, end=ft.alignment.center_right,
                colors=["#DC2626", "#F97316"],
            )
            self._wave.name = ft.Icons.MIC_ROUNDED
        else:
            self.banner.gradient = ft.LinearGradient(
                begin=ft.alignment.center_left, end=ft.alignment.center_right,
                colors=["#0B63F6", "#1AD8D1"],
            )
            self._wave.name = ft.Icons.AUTO_AWESOME

    def _push_turn(self, role: str, text: str) -> None:
        self.turns.append(Turn(role=role, text=text))
        self.turns = self.turns[-6:]
        chips = []
        for t in self.turns[-3:]:
            bg = "#FFFFFF33" if t.role == "user" else "#00000022"
            prefix = "أنت: " if t.role == "user" else "نانو: "
            chips.append(
                ft.Container(
                    ft.Text((prefix + t.text)[:36], size=10, color=Colors.WHITE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=bg, border_radius=10,
                )
            )
        self._chip_row.controls = chips

    def _reply(self, text: str, *, kind: str = "info") -> None:
        self._hint.value = text
        self._push_turn("nano", text)
        self._safe_update()
        try:
            self.notify(text, kind=kind)
        except Exception:
            pass
        self._speak(text)

    def _show_help(self) -> None:
        section = (self.get_section() or "dashboard").lower()
        parts = [
            "بيع سريع · جرد · مواد · فواتير",
            "كم باقي + اسم · ملخص",
            "أضف [كمية] اسم · ادفع · أفرغ السلة",
            "طوارئ / إيقاف",
        ]
        if section == "pos":
            parts.insert(0, "أنت في الكاشير — يكفي اسم المادة")
        self._reply(" · ".join(parts[:3]), kind="info")

    def _is_help(self, text: str) -> bool:
        t = (text or "").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        return any(k in t for k in ("مساعده", "مساعدة", "الاوامر", "الأوامر", "help", "ماذا اقول", "وش اقول"))

    @staticmethod
    def _parse_qty_utterance(text: str) -> float | None:
        from nano_offline.services.quick_command_service import QuickCommandService

        t = (text or "").strip()
        if not t:
            return None
        try:
            arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
            return float(t.translate(arabic_digits).replace(",", "."))
        except ValueError:
            pass
        word_qty = {
            "واحد": 1, "اثنين": 2, "اثنان": 2, "ثلاثه": 3, "ثلاثة": 3,
            "اربعه": 4, "أربعة": 4, "خمسه": 5, "خمسة": 5,
        }
        key = t.replace("أ", "ا").replace("إ", "ا")
        if key in word_qty:
            return float(word_qty[key])
        _, qty = QuickCommandService._strip_trailing_qty_words(f"x {t}", 1.0)
        return float(qty) if qty != 1.0 else None


    def _run_confirmed(self, pending: dict) -> None:
        kind = pending.get("kind")
        if kind == "pos_clear":
            result = pending.get("result")
            section = pending.get("section") or ""
            if section != "pos":
                self._queue_and_go_pos(result)
            else:
                self._apply_pos(result)
            self._reply("تم تفريغ السلة", kind="info")
        elif kind == "crisis_on":
            try:
                self.ctx.crisis_mode.activate(freeze_current_rate=True)
                self._reply("وضع الطوارئ مفعّل", kind="warning")
            except Exception as exc:
                self._reply(str(exc), kind="error")

    @staticmethod
    def _is_yes(text: str) -> bool:
        t = (text or "").strip().replace("أ", "ا").replace("إ", "ا")
        return t in ("نعم", "اي", "أي", "ايه", "موافق", "تمام", "أكد", "اكد", "yes", "y") or t.startswith("نعم")

    @staticmethod
    def _is_no(text: str) -> bool:
        t = (text or "").strip().replace("أ", "ا").replace("إ", "ا")
        return t in ("لا", "لاء", "الغاء", "إلغاء", "كانسل", "no", "n") or t.startswith("لا")

    def _speak(self, text: str) -> None:
        if not self.tts_enabled or not self.native_files or not text:
            return
        # Keep spoken replies short
        spoken = (text or "").strip()
        if len(spoken) > 120:
            spoken = spoken[:117] + "…"

        async def _go():
            try:
                await self.native_files.speech_stop_speak()
            except Exception:
                pass
            try:
                await self.native_files.speech_speak(spoken, language="ar")
            except Exception:
                pass

        try:
            if hasattr(self.page, "run_task"):
                self.page.run_task(_go)
        except Exception:
            pass

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass


__all__ = ["VoiceSessionController"]
