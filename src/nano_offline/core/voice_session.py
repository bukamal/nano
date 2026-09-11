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
from nano_offline.core.voice_intelligence import (
    VoiceMemory, reply_for, resolve_item_name, extract_again_reference,
    is_yes, is_no, match_converse, reply_converse,
)
from nano_offline.core.voice_guide import match_guide, guide_for_section


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
        # Silent by default: continuous AI-call feel without chimes/TTS.
        self._raw_notify = notify
        self.get_section = get_section or (lambda: "dashboard")
        self.native_files = native_files
        self.tts_enabled = tts_enabled
        self.silent = True  # no toast tones during the call
        self._speaking = False
        self._pending_relisten = False
        self._pending_relisten_delay = 0.4

        self.active = False
        self.listening = False
        self.turns: list[Turn] = []
        self._pending_followup: dict[str, Any] | None = None
        self._pending_confirm: dict[str, Any] | None = None
        self._last_command: str = ""
        self.memory = VoiceMemory()

        # ---- Option 2: small floating draggable bubble (not a top banner) ----
        self._bubble_icon = ft.Icon(ft.Icons.GRAPHIC_EQ_ROUNDED, size=22, color=Colors.WHITE)
        self._bubble_tip = ft.Text("", size=9, color=Colors.WHITE, text_align=ft.TextAlign.CENTER, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, visible=False)

        self._pos_left = 16.0
        self._pos_bottom = 96.0  # above mobile bottom bar

        def _on_pan(e: ft.DragUpdateEvent):
            # Drag in screen space; clamp lightly
            try:
                self._pos_left = max(8.0, float(self._pos_left) + float(e.delta_x))
                self._pos_bottom = max(72.0, float(self._pos_bottom) - float(e.delta_y))
                self.banner.left = self._pos_left
                self.banner.bottom = self._pos_bottom
                self.banner.right = None
                self.banner.top = None
                self.banner.update()
            except Exception:
                pass

        bubble_body = ft.Container(
            content=ft.Column(
                [self._bubble_icon, self._bubble_tip],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=52,
            height=52,
            alignment=ft.alignment.center,
            bgcolor=Colors.PRIMARY,
            border_radius=26,
            shadow=ft.BoxShadow(blur_radius=14, color="#50000000", offset=ft.Offset(0, 4)),
            ink=True,
            tooltip="اضغط مطولاً للسحب · نقرة لإنهاء المكالمة",
            on_click=lambda e: self.stop(reason="ended"),
        )

        self.banner = ft.GestureDetector(
            content=bubble_body,
            on_pan_update=_on_pan,
            drag_interval=16,
        )
        # Positioned host used by main overlay
        self.banner = ft.Container(
            content=ft.GestureDetector(
                content=bubble_body,
                on_pan_update=_on_pan,
                drag_interval=16,
            ),
            left=self._pos_left,
            bottom=self._pos_bottom,
            visible=False,
            animate_opacity=150,
        )
        # aliases for legacy field updates
        self._status = ft.Text("")  # unused
        self._hint = ft.Text("")
        self._section_chip = ft.Text("")
        self._wave = self._bubble_icon
        self._chip_row = ft.Row(visible=False, controls=[])

        self.fab = ft.FloatingActionButton(
            icon=ft.Icons.AUTO_AWESOME,
            bgcolor=Colors.PRIMARY,
            foreground_color=Colors.WHITE,
            tooltip="مكالمة أوامر ذكية",
            on_click=self.toggle,
            visible=False,
            mini=True,
        )

        self._header_icon = ft.Icon(ft.Icons.AUTO_AWESOME, color=Colors.PRIMARY, size=20)
        self.header_btn = ft.Container(
            self._header_icon,
            width=42,
            height=42,
            alignment=ft.alignment.center,
            border=ft.border.all(1, Colors.BORDER),
            border_radius=14,
            bgcolor=Colors.WHITE,
            shadow=Shadow.SM if hasattr(Shadow, "SM") else None,
            ink=True,
            tooltip="مكالمة أوامر ذكية",
            on_click=self.toggle,
        )


    def _notify_quiet(self, text: str, *, kind: str = "info") -> None:
        """Visual feedback only — no success/error chimes during the call."""
        if self._raw_notify is not None:
            try:
                self._raw_notify(text, kind=kind)
                return
            except TypeError:
                pass
            except Exception:
                pass
        try:
            # sound_kind="" is not enough; toast always plays kind tone.
            # Use toast with a no-op by temporarily skipping sound via empty overlay message only:
            toast(self.page, text, kind=kind, duration=1800, sound_kind="__silent__")
        except Exception:
            try:
                toast(self.page, text, kind=kind, duration=1800)
            except Exception:
                pass

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
        self.memory = VoiceMemory()
        self.memory.last_section = self.get_section() or "dashboard"
        greet = reply_for("greet", section=(self.get_section() or "dashboard"))
        self.fab.icon = ft.Icons.CALL_END_ROUNDED
        self.fab.bgcolor = Colors.DANGER
        self.fab.tooltip = "إنهاء المكالمة"
        try:
            self._header_icon.name = ft.Icons.CALL_END_ROUNDED
            self._header_icon.color = Colors.WHITE
            self.header_btn.bgcolor = Colors.DANGER
            self.header_btn.border = ft.border.all(1, Colors.DANGER)
            self.header_btn.tooltip = "إنهاء المكالمة"
        except Exception:
            pass
        self._push_turn("nano", greet)
        self._safe_update()
        self._notify_quiet(greet, kind="info")
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
        try:
            self._header_icon.name = ft.Icons.AUTO_AWESOME
            self._header_icon.color = Colors.PRIMARY
            self.header_btn.bgcolor = Colors.WHITE
            self.header_btn.border = ft.border.all(1, Colors.BORDER)
            self.header_btn.tooltip = "مكالمة أوامر ذكية"
        except Exception:
            pass
        self._safe_update()
        if reason not in ("silent",):
            self._notify_quiet("انتهت المكالمة", kind="info")

    def _listen(self) -> None:
        if not self.active or self.listening:
            return
        self.listening = True
        self._refresh_section_chip()
        self._set_listening_visual(True)
        self._hint.value = "يستمع…"
        self._safe_update()
        # Do not cut an active reply; listen is only scheduled after TTS ends.
        if self._speaking:
            self._pending_relisten = True
            return

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
                for x in ("لم يُلتقط", "لم يُفهم", "انتهى وقت", "NO_MATCH", "SPEECH_TIMEOUT", "timeout", "permission", "أُلغي")
            )
            try:
                self._bubble_tip.value = ""
                self._bubble_tip.visible = False
            except Exception:
                pass
            self._safe_update()
            if not self.active:
                return
            if "permission" in (msg or "").lower() or "إذن" in (msg or ""):
                self._notify_quiet("يلزم إذن الميكروفون", kind="warning")
                self.stop(reason="permission")
                return
            # Soft miss: stay in the call silently, listen again (AI-call style)
            self._schedule_relisten(0.4 if soft else 0.7)

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
        """Restart mic after reply — never while TTS is still speaking."""
        if not self.active:
            return
        if self.tts_enabled and self._speaking:
            self._pending_relisten = True
            self._pending_relisten_delay = max(0.3, delay)
            return
        wait = max(0.3, delay)

        def _go():
            if self.active and not self.listening and not self._speaking:
                self._listen()

        threading.Timer(wait, _go).start()

    def _execute(self, text: str) -> None:
        section = (self.get_section() or "dashboard").lower()

        # Pending confirmation (clear cart / crisis)
        if self._pending_confirm:
            if is_yes(text):
                pending = self._pending_confirm
                self._pending_confirm = None
                self._run_confirmed(pending)
                self._schedule_relisten(0.8)
                return
            if is_no(text):
                self._pending_confirm = None
                self._reply(reply_for("cancelled", memory=self.memory), kind="info")
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

        conv = match_converse(text)
        if conv == "repeat" and self.memory.last_action == "pos_add" and self.memory.last_item_name:
            self._do_pos_add(self.memory.last_item_name, float(self.memory.last_qty or 1))
            self._schedule_relisten(0.5)
            return
        if conv == "undo":
            fake = type("R", (), {"action": "pos_remove_last", "data": {}, "ok": True, "target": "pos", "message": ""})()
            if (self.get_section() or "").lower() == "pos":
                self._apply_pos(fake)
            else:
                self._queue_and_go_pos(fake)
            self._reply(reply_converse("undo"), kind="info")
            self._schedule_relisten(0.5)
            return
        if conv in ("greet", "thanks", "howto", "help"):
            self._reply(reply_converse(conv), kind="info")
            self._schedule_relisten(0.5)
            return

        if self._is_help(text):
            self._show_help()
            self._schedule_relisten(0.8)
            return

        # Natural «كم السعر» / summary while on dashboard
        if any(k in text for k in ("ملخص", "كيف الشغل", "كيف الحال", "وضع اليوم", "نبض")):
            try:
                pulse = self.ctx.owner_pulse.generate()
                body = f"{pulse.headline}. {pulse.body}"
                self._reply(reply_for("pulse", extra=body, memory=self.memory, section=section), kind="info")
            except Exception:
                self._reply("تعذر جلب الملخص الآن", kind="warning")
            self._schedule_relisten(0.9)
            return

        # Explicit teaching: «تعلم أن بيبسي تعني بيبسي كولا» / «علّم أضف سكر»
        teach = self._try_teach(text)
        if teach:
            self._schedule_relisten(0.5)
            return

        # Self-learned phrases (this device)
        try:
            learn = getattr(self.ctx, "voice_learning", None)
            if learn is not None:
                hit = learn.lookup_phrase(text)
                if hit and hit.get("action"):
                    action = hit["action"]
                    target = hit.get("target")
                    data = hit.get("data") or {}
                    if action == "pos_add":
                        self._do_pos_add(data.get("name") or text, float(data.get("qty") or 1))
                        self._schedule_relisten(0.5)
                        return
                    if action == "navigate" and target:
                        self.navigate(target)
                        self._reply(reply_for("navigate", extra=target, memory=self.memory, section=target), kind="success")
                        self._schedule_relisten(0.5)
                        return
                    if action in ("pos_pay", "pos_clear", "pos_remove_last", "pos_cart_summary"):
                        result = type("R", (), {"action": action, "data": data, "target": target or "pos", "ok": True, "message": ""})()
                        if action == "pos_clear":
                            self._pending_confirm = {"kind": "pos_clear", "result": result, "section": section}
                            self._reply(reply_for("pos_clear_ask", memory=self.memory, section=section), kind="warning")
                        else:
                            if section != "pos" and target == "pos":
                                self._queue_and_go_pos(result)
                            else:
                                self._apply_pos(result)
                            self._reply(reply_for(action if action != "pos_remove_last" else "message", extra="تم.", memory=self.memory, section=section), kind="info")
                        self._schedule_relisten(0.5)
                        return
        except Exception:
            pass

        # Full usage guide / how-to / where-is (offline knowledge base)
        guided = match_guide(text, section=section)
        if guided:
            answer, target = guided
            if target:
                try:
                    self.navigate(target)
                except Exception:
                    pass
            self._reply(answer, kind="info")
            self._schedule_relisten(0.6)
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
                self._reply(reply_for("pos_clear_ask", memory=self.memory, section=section), kind="warning")
                self._schedule_relisten(0.7)
                return
            else:
                self._queue_and_go_pos(result)
                self.memory.note(last_action="pos_pay")
                self._reply(reply_for("pos_pay", memory=self.memory, section=section), kind="success")
            self._schedule_relisten(0.9)
            return

        if action == "pos_remove_last":
            section = (self.get_section() or "").lower()
            if section != "pos":
                self._queue_and_go_pos(result)
            else:
                self._apply_pos(result)
            self.memory.note(last_action="pos_remove_last")
            self._reply("حذفت آخر مادة من السلة." if section == "pos" else "فتح نقطة البيع وحذف الأخير…", kind="info")
            self._schedule_relisten(0.8)
            return

        if action == "pos_cart_summary":
            section = (self.get_section() or "").lower()
            snap = None
            getter = getattr(self.ctx, "_pos_cart_snapshot", None)
            if callable(getter):
                try:
                    snap = getter()
                except Exception:
                    snap = None
            if snap is None and section != "pos":
                self.navigate("pos")
                self._schedule_relisten(1.0)
                self._reply("افتح نقطة البيع ثم أعد: ملخص السلة", kind="info")
                return
            if not snap or not snap.get("count"):
                self._reply("السلة فارغة حالياً.", kind="info")
            else:
                total = snap.get("total") or 0
                try:
                    from nano_offline.core import currency
                    total_txt = currency.format_amount(total, self.ctx.settings)
                except Exception:
                    total_txt = f"{total:,.0f}"
                names = "، ".join(
                    f"{ln.get('name')}×{float(ln.get('qty') or 0):g}" for ln in (snap.get("lines") or [])[:4]
                )
                more = "" if snap["count"] <= 4 else f" وغيرها {snap['count']-4}"
                self._reply(f"بالسلة {snap['count']} بند: {names}{more}. الإجمالي {total_txt}.", kind="info")
            self._schedule_relisten(0.9)
            return

        if action == "pos_add_many":
            data = result.data or {}
            items = data.get("items") or []
            # resolve each name for better matching
            from nano_offline.core.voice_intelligence import resolve_item_name
            resolved = []
            for it in items:
                nm = (it.get("name") or "").strip()
                q = float(it.get("qty") or 1)
                matches = resolve_item_name(self.ctx.items, nm, limit=3)
                if matches:
                    resolved.append({
                        "name": matches[0].get("name"),
                        "qty": q,
                        "item_id": int(matches[0].get("id") or 0) or None,
                    })
                    self.memory.note(last_item_name=matches[0].get("name"), last_qty=q, last_action="pos_add")
                    self.memory.cart_adds += 1
            payload = type("R", (), {"action": "pos_add_many", "data": {"items": resolved}, "ok": True, "target": "pos", "message": ""})()
            section = (self.get_section() or "").lower()
            if section == "pos":
                self._apply_pos(payload)
            else:
                self._queue_and_go_pos(payload)
            if resolved:
                names = " و ".join(f"{r['name']}×{r['qty']:g}" for r in resolved[:4])
                self._reply(f"أضفت: {names}.", kind="success")
            else:
                self._reply("ما قدرت أطابق المواد المطلوبة.", kind="warning")
            self._schedule_relisten(0.9)
            return

        if action == "tts_mute":
            self.tts_enabled = False
            self._reply("تمام، رح أرد كتابة فقط بدون صوت.", kind="info")
            self._schedule_relisten(0.6)
            return

        if action == "tts_unmute":
            self.tts_enabled = True
            self._reply("رجّعت الرد الصوتي.", kind="success")
            self._schedule_relisten(0.6)
            return

        if action == "item_create":
            data = result.data or {}
            name = (data.get("name") or "").strip()
            price = float(data.get("selling_price") or 0)
            qty = float(data.get("quantity") or 0)
            if not name:
                self._reply("حدّد اسم المادة لإنشائها.", kind="warning")
                self._schedule_relisten(0.6)
                return
            # avoid duplicates
            from nano_offline.core.voice_intelligence import resolve_item_name
            existing = resolve_item_name(self.ctx.items, name, limit=3)
            if existing and str(existing[0].get("name") or "").strip() == name:
                self._reply(f"المادة «{name}» موجودة مسبقاً.", kind="warning")
                self._schedule_relisten(0.7)
                return
            try:
                item_id = self.ctx.items.create(
                    name=name,
                    selling_price=price,
                    purchase_price=0,
                    quantity=qty,
                    item_type="مخزون",
                )
                self.memory.note(last_item_name=name, last_item_id=item_id, last_action="item_create")
                price_txt = f" بسعر {price:g}" if price else ""
                self._reply(f"أنشأت المادة «{name}»{price_txt}. تقدر تضيفها للسلة الآن.", kind="success")
            except Exception as exc:
                self._reply(str(exc), kind="error")
            self._schedule_relisten(0.85)
            return

        if action == "pos_set_qty":
            data = result.data or {}
            section = (self.get_section() or "").lower()
            if section != "pos":
                self._queue_and_go_pos(result)
                self._reply("فتح نقطة البيع لتعديل الكمية…", kind="info")
            else:
                self._apply_pos(result)
                setter = getattr(self.ctx, "_pos_apply_voice", None)
                # message from toast already; craft reply
                name = data.get("name") or "الأخير"
                self._reply(f"تم ضبط كمية {name} إلى {float(data.get('qty') or 0):g}.", kind="success")
            self._schedule_relisten(0.8)
            return

        if action == "cash_status":
            try:
                s = self.ctx.dashboard.summary()
                cash = float(s.get("cash") or 0)
                try:
                    from nano_offline.core import currency
                    cash_txt = currency.format_amount(cash, self.ctx.settings)
                except Exception:
                    cash_txt = f"{cash:,.0f}"
                self._reply(f"رصيد الصندوق تقريباً {cash_txt}.", kind="info")
            except Exception as exc:
                self._reply(str(exc), kind="error")
            self._schedule_relisten(0.85)
            return

        if action == "today_sales":
            try:
                s = self.ctx.dashboard.today_summary()
                count = int(s.get("count") or 0)
                total = float(s.get("total") or 0)
                try:
                    from nano_offline.core import currency
                    total_txt = currency.format_amount(total, self.ctx.settings)
                except Exception:
                    total_txt = f"{total:,.0f}"
                if count == 0:
                    self._reply("اليوم ما في فواتير بيع بعد.", kind="info")
                else:
                    self._reply(f"اليوم {count} فاتورة بيع بإجمالي {total_txt}.", kind="info")
            except Exception as exc:
                self._reply(str(exc), kind="error")
            self._schedule_relisten(0.85)
            return

        if action == "navigate" and result.target:
            try:
                self.navigate(result.target)
                self.memory.note(last_section=result.target, last_action="navigate")
                label = result.message or result.target or "القسم"
                try:
                    learn = getattr(self.ctx, "voice_learning", None)
                    if learn is not None:
                        learn.remember_phrase(text, action="navigate", target=result.target)
                except Exception:
                    pass
                self._reply(reply_for("navigate", extra=label, memory=self.memory, section=result.target or section), kind="success")
            except Exception as exc:
                self._reply(str(exc), kind="error")
            self._schedule_relisten(0.7)
            return

        if action == "crisis_on":
            self._pending_confirm = {"kind": "crisis_on"}
            self._reply(reply_for("crisis_ask", memory=self.memory, section=section), kind="warning")
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
            msg = result.message or text
            self.memory.note(last_action=action)
            self._reply(reply_for("stock" if action == "query" else "message", extra=msg, memory=self.memory, section=section), kind="info")
            self._schedule_relisten(0.75)
            return

        if section == "pos" and len(text) >= 2 and self._try_fuzzy_pos_add(text):
            self._schedule_relisten(0.85)
            return

        try:
            learn = getattr(self.ctx, "voice_learning", None)
            if learn is not None:
                learn.remember_unknown(text, section=section)
                st = learn.stats()
                extra_u = result.message or ""
                if st.get("phrases"):
                    extra_u = (extra_u + f" · ذاكرتي المحلية: {st['phrases']} عبارة و {st['item_aliases']} اسماً للممواد.").strip(" ·")
                self._reply(reply_for("unknown", extra=extra_u, memory=self.memory, section=section), kind="warning")
            else:
                self._reply(reply_for("unknown", extra=result.message or "", memory=self.memory, section=section), kind="warning")
        except Exception:
            self._reply(reply_for("unknown", extra=result.message or "", memory=self.memory, section=section), kind="warning")
        self._schedule_relisten(0.75)

    def _do_pos_add(self, name: str, qty: float) -> None:
        section = (self.get_section() or "").lower()
        # Learned nicknames first
        try:
            learn = getattr(self.ctx, "voice_learning", None)
            if learn is not None:
                alias = learn.resolve_item_alias(name)
                if alias and alias.get("item_name"):
                    name = alias["item_name"]
        except Exception:
            pass
        matches = resolve_item_name(self.ctx.items, name, limit=8)
        if not matches:
            # second chance: raw list search
            try:
                matches = list(self.ctx.items.list(search=name.strip(), limit=8) or [])
            except Exception:
                matches = []
        if not matches:
            self._reply(reply_for("pos_add", ok=False, name=name, memory=self.memory, section=section), kind="warning")
            return
        chosen = matches[0]
        resolved = str(chosen.get("name") or name)
        try:
            item_id = int(chosen.get("id") or 0) or None
        except Exception:
            item_id = None
        result = type(
            "R",
            (),
            {
                "action": "pos_add",
                "data": {"name": resolved, "qty": float(qty or 1), "item_id": item_id},
                "message": f"إضافة {resolved} × {float(qty or 1):g}",
                "target": "pos",
                "ok": True,
            },
        )()
        applied = False
        if section == "pos":
            applied = self._apply_pos(result)
            if not applied and item_id is not None:
                # Direct fallback if hook missing mid-rebuild
                try:
                    setattr(self.ctx, "_pending_voice_command", result)
                except Exception:
                    pass
        else:
            self._queue_and_go_pos(result)
            applied = True
        self.memory.note(last_item_name=resolved, last_item_id=item_id, last_qty=float(qty or 1), last_action="pos_add")
        self.memory.cart_adds += 1
        try:
            learn = getattr(self.ctx, "voice_learning", None)
            if learn is not None and item_id and name:
                learn.remember_item_alias(name, item_id=int(item_id), item_name=resolved)
                learn.remember_phrase(
                    f"أضف {name}",
                    action="pos_add",
                    target="pos",
                    data={"name": resolved, "qty": float(qty or 1), "item_id": item_id},
                )
        except Exception:
            pass
        self._reply(
            reply_for("pos_add", ok=True, name=resolved, qty=float(qty or 1), memory=self.memory, section=section),
            kind="success",
        )


    def _try_fuzzy_pos_add(self, text: str) -> bool:
        rows = resolve_item_name(self.ctx.items, text.strip(), limit=5)
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

    def _apply_pos(self, result) -> bool:
        apply = getattr(self.ctx, "_pos_apply_voice", None)
        if callable(apply):
            try:
                apply(result)
                return True
            except Exception:
                pass
        try:
            setattr(self.ctx, "_pending_voice_command", result)
        except Exception:
            pass
        return False


    def _try_teach(self, text: str) -> bool:
        """User teaches the assistant: تعلم أن X تعني Y / علّم هذه."""
        import re
        t = (text or "").strip()
        m = re.search(
            r"(?:تعلم|تعلّم|علم|علّم)\s+(?:ان|أن)?\s*(?P<a>.+?)\s+(?:تعني|يعني|اسمها|هي)\s+(?P<b>.+)$",
            t,
        )
        learn = getattr(self.ctx, "voice_learning", None)
        if not learn:
            return False
        if m:
            spoken = m.group("a").strip()
            official = m.group("b").strip()
            # try as item alias
            try:
                rows = self.ctx.items.list(search=official, limit=5) or []
            except Exception:
                rows = []
            if rows:
                item = rows[0]
                learn.remember_item_alias(spoken, item_id=int(item["id"]), item_name=str(item.get("name") or official))
                self._reply(
                    f"تعلمت أن «{spoken}» تشير إلى المادة «{item.get('name')}». سأستخدمها في المرات القادمة.",
                    kind="success",
                )
                return True
            learn.remember_phrase(spoken, action="navigate", target=None, data={"note": official})
            self._reply(f"حفظت العبارة «{spoken}» في ذاكرتي المحلية وسأحاول الاستفادة منها لاحقاً.", kind="info")
            return True
        # stats
        if any(k in t for k in ("ماذا تعلمت", "شو تعلمت", "ذاكرة الصوت", "كم عبارة")):
            st = learn.stats()
            self._reply(
                f"ذاكرتي على هذا الجهاز: {st.get('phrases', 0)} عبارة أوامر، "
                f"{st.get('item_aliases', 0)} اسماً بديلاً للمواد، و{st.get('unknowns', 0)} عبارة غير مفهومة سأحاول التعلم منها.",
                kind="info",
            )
            return True
        return False

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
        return

    def _set_listening_visual(self, active: bool) -> None:
        body = self.banner.content.content if hasattr(self.banner, "content") else None
        # banner -> GestureDetector -> Container(bubble_body)
        try:
            bubble = self.banner.content.content  # type: ignore
        except Exception:
            bubble = None
        if active:
            self._bubble_icon.name = ft.Icons.MIC_ROUNDED
            if bubble is not None:
                bubble.bgcolor = Colors.DANGER
        else:
            self._bubble_icon.name = ft.Icons.GRAPHIC_EQ_ROUNDED
            if bubble is not None:
                bubble.bgcolor = Colors.PRIMARY


    def _push_turn(self, role: str, text: str) -> None:
        self.turns.append(Turn(role=role, text=text))
        self.turns = self.turns[-8:]


    def _reply(self, text: str, *, kind: str = "info") -> None:
        self._push_turn("nano", text)
        try:
            self._bubble_tip.value = (text or "")[:22]
            self._bubble_tip.visible = bool(text)
        except Exception:
            pass
        self._safe_update()
        try:
            self._notify_quiet(text, kind=kind)
        except Exception:
            pass
        if self.tts_enabled and text:
            # Any schedule_relisten while speaking will wait until TTS finishes
            self._pending_relisten = True
            self._pending_relisten_delay = 0.45
            self._speak(text)

    def _show_help(self) -> None:
        section = (self.get_section() or "dashboard").lower()
        if section == "pos":
            msg = guide_for_section("pos")
        else:
            msg = (
                guide_for_section(section)
                + " أيضاً: كيف أبيع، كيف أضيف مادة، كيف أجرد، اشرح الشاشة، مساعدة، إيقاف."
            )
        self._reply(reply_for("help", extra=msg, memory=self.memory, section=section), kind="info")

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
            self._reply(reply_for("pos_clear_done", memory=self.memory), kind="info")
        elif kind == "crisis_on":
            try:
                self.ctx.crisis_mode.activate(freeze_current_rate=True)
                self._reply(reply_for("crisis_on", memory=self.memory), kind="warning")
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
        spoken = (text or "").strip()
        # Allow long full replies; native layer waits until utterance ends
        self._last_spoken = spoken
        self._speaking = True

        async def _go():
            try:
                try:
                    await self.native_files.speech_stop_speak()
                except Exception:
                    pass
                await self.native_files.speech_speak(spoken, language="ar")
            except Exception:
                pass
            finally:
                self._speaking = False
                self._last_spoken = ""
                if self._pending_relisten and self.active:
                    self._pending_relisten = False
                    delay = self._pending_relisten_delay
                    self._schedule_relisten(delay)

        try:
            if hasattr(self.page, "run_task"):
                self.page.run_task(_go)
        except Exception:
            self._speaking = False


    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass


__all__ = ["VoiceSessionController"]
