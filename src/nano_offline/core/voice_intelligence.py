"""Smarter Arabic voice replies, memory, and light intent helpers.

Keeps the continuous call feeling natural without an external LLM:
  • varied reply templates by intent + outcome
  • short-term session memory (last item, last section, last qty)
  • contextual next-step suggestions
  • fuzzy item resolution shared by POS + stock queries
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class VoiceMemory:
    last_item_name: str | None = None
    last_item_id: int | None = None
    last_qty: float | None = None
    last_action: str | None = None
    last_section: str | None = None
    turn_count: int = 0
    cart_adds: int = 0

    def note(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)
        self.turn_count += 1


_YES = {"نعم", "اي", "أي", "ايه", "موافق", "تمام", "أكد", "اكد", "yes", "يقطع", "ايوه", "أيوه"}
_NO = {"لا", "لاء", "الغاء", "إلغاء", "كانسل", "no", "بطل", "ما بدي"}


def is_yes(text: str) -> bool:
    t = _norm(text)
    return t in _YES or t.startswith("نعم") or t.startswith("ايوه")


def is_no(text: str) -> bool:
    t = _norm(text)
    return t in _NO or t.startswith("لا ")


def _norm(text: str) -> str:
    t = (text or "").strip()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        t = t.replace(a, b)
    return t


def hour_greeting() -> str:
    h = datetime.now().hour
    if 5 <= h < 12:
        return "صباح الخير"
    if 12 <= h < 17:
        return "نهارك سعيد"
    if 17 <= h < 22:
        return "مساء الخير"
    return "مرحبا"


def reply_for(
    intent: str,
    *,
    ok: bool = True,
    name: str = "",
    qty: float | None = None,
    extra: str = "",
    memory: VoiceMemory | None = None,
    section: str = "",
) -> str:
    """Pick a short natural Arabic reply; optionally append a smart hint."""
    q = f"{qty:g}" if qty is not None else ""
    pool: list[str]
    if intent == "greet":
        pool = [
            f"{hour_greeting()}. أنا معك — قل أمرك.",
            f"{hour_greeting()}. جاهز للأوامر الصوتية.",
            f"{hour_greeting()}. قل «مساعدة» إن احتجت.",
        ]
    elif intent == "pos_add" and ok:
        pool = [
            f"تم. أضفت {name}" + (f" × {q}" if q else "") + ".",
            f"حاضر. {name}" + (f" كمية {q}" if q else "") + " في السلة.",
            f"تمام، {name} صارت في الكارت" + (f" ({q})" if q else "") + ".",
        ]
    elif intent == "pos_add" and not ok:
        pool = [
            f"ما لقيت مادة باسم «{name}». جرّب اسماً أقرب.",
            f"ما في تطابق لـ «{name}» بالمخزون.",
        ]
    elif intent == "pos_pay":
        pool = ["فتحت شاشة الدفع.", "يلا على الدفع.", "شاشة التحصيل جاهزة."]
    elif intent == "pos_clear_ask":
        pool = ["متأكد تفرّغ السلة؟ قل نعم أو لا.", "تأكيد مسح السلة؟ نعم أو لا."]
    elif intent == "pos_clear_done":
        pool = ["اتفرّغت السلة.", "السلة فاضية الآن."]
    elif intent == "cancelled":
        pool = ["تم الإلغاء.", "ماشي، ما نفّذت شيء.", "أُلغي الأمر."]
    elif intent == "navigate":
        pool = [
            f"فتحت {extra or 'القسم'}.",
            f"تم — {extra or 'القسم'}.",
            f"روحنا على {extra or 'القسم'}.",
        ]
    elif intent == "stock":
        pool = [extra or "هذا رصيد المادة."]
    elif intent == "pulse":
        pool = [extra or "هذا ملخص سريع."]
    elif intent == "crisis_ask":
        pool = ["تأكيد تفعيل وضع الطوارئ؟ نعم أو لا."]
    elif intent == "crisis_on":
        pool = ["وضع الطوارئ شغال وسعر الصرف مجمّد."]
    elif intent == "crisis_off":
        pool = ["أُلغي وضع الطوارئ."]
    elif intent == "help":
        pool = [extra or "قل بيع سريع، جرد، أضف سكر، كم باقي الأرز، ملخص، أو إيقاف."]
    elif intent == "unknown":
        pool = [
            "ما فهمت تمام. قل «مساعدة» أو أعد الصياغة.",
            "ممكن تعيد الأمر؟ أو قل مساعدة.",
            "الأمر غير واضح لي بعد.",
        ]
    elif intent == "stop":
        pool = ["مع السلامة. انتهت المكالمة.", "تم إنهاء الجلسة الصوتية."]
    else:
        pool = [extra or "تم."]

    text = random.choice(pool)
    if extra and intent in ("stock", "pulse", "help") and extra not in text:
        text = extra

    hint = _next_hint(intent, ok=ok, memory=memory, section=section, name=name)
    if hint and hint not in text:
        text = f"{text} {hint}"
    return text.strip()


def _next_hint(
    intent: str,
    *,
    ok: bool,
    memory: VoiceMemory | None,
    section: str,
    name: str,
) -> str:
    if intent == "pos_add" and ok:
        if memory and memory.cart_adds >= 2:
            return "تقدر تقول ادفع متى ما خلصت."
        return "زيد مادة ثانية أو قل ادفع."
    if intent == "navigate" and section == "pos":
        return "قل اسم المادة لإضافتها."
    if intent == "stock" and name:
        return "بدك تفتح البيع السريع؟"
    if intent == "unknown" and section == "pos":
        return "جرّب اسم المادة مباشرة."
    return ""


def resolve_item_name(db_or_repo, query: str, *, limit: int = 8) -> list[dict]:
    """Rank catalog rows by simple Arabic-aware similarity."""
    q = _norm(query)
    if not q:
        return []
    rows: list[dict] = []
    try:
        if hasattr(db_or_repo, "list"):
            rows = db_or_repo.list(search=query.strip(), limit=limit * 2) or []
        elif hasattr(db_or_repo, "connect"):
            with db_or_repo.connect() as conn:
                cur = conn.execute(
                    "SELECT id, name, quantity, selling_price FROM items "
                    "WHERE item_type='مخزون' AND name LIKE ? ORDER BY name LIMIT ?",
                    (f"%{query.strip()}%", limit * 2),
                )
                rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        return []

    scored: list[tuple[float, dict]] = []
    for r in rows:
        name = _norm(str(r.get("name") or ""))
        if not name:
            continue
        score = 0.0
        if name == q:
            score = 100
        elif name.startswith(q) or q.startswith(name):
            score = 80
        elif q in name:
            score = 60 + max(0, 20 - abs(len(name) - len(q)))
        else:
            # token overlap
            qt, nt = set(q.split()), set(name.split())
            if qt & nt:
                score = 40 + 10 * len(qt & nt)
            else:
                continue
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]


def extract_again_reference(text: str, memory: VoiceMemory) -> tuple[str, float] | None:
    """«كمان واحد» / «نفس الشيء» / «زيد بعد» using last item."""
    t = _norm(text)
    if not memory.last_item_name:
        return None
    again = any(k in t for k in ("كمان", "نفس", "برضو", "بعد", "زيد غير", "واحدة كمان", "واحد كمان"))
    if not again:
        return None
    qty = memory.last_qty or 1.0
    m = re.search(r"(\\d+[\\d.,]*)", t)
    if m:
        try:
            qty = float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    for w, n in (("واحد", 1), ("اثنين", 2), ("ثلاث", 3), ("اربعة", 4), ("أربعة", 4)):
        if w in t:
            qty = float(n)
    return memory.last_item_name, qty


__all__ = [
    "VoiceMemory",
    "reply_for",
    "resolve_item_name",
    "extract_again_reference",
    "is_yes",
    "is_no",
    "hour_greeting",
]
