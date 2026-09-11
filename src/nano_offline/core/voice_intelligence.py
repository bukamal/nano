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


# Arabic display labels for every shell section key — the TTS must never
# pronounce the internal English keys («pos», «items», «finance» …).
SECTION_AR: dict[str, str] = {
    "pos": "نقطة البيع", "items": "المواد", "stocktake": "الجرد",
    "finance": "المالية", "customers": "العملاء", "suppliers": "الموردين",
    "invoices": "الفواتير", "reports": "التقارير", "dashboard": "الرئيسية",
    "admin": "الإدارة", "notifications": "الإشعارات", "security": "الأمان",
    "sale": "فاتورة البيع", "purchase": "فاتورة الشراء",
}


def ar_section_label(key: str | None) -> str | None:
    """English shell key → Arabic spoken label; unknown text passes through."""
    if not key:
        return None
    k = str(key).strip().lower()
    return SECTION_AR.get(k) or key


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
    """Natural Arabic reply — longer, conversational, cashier-friendly."""
    q = f"{qty:g}" if qty is not None else ""
    pool: list[str]
    if intent == "greet":
        pool = [
            f"{hour_greeting()}. أنا مساعدك في نانو، معك الآن في مكالمة مستمرة. قل أمرك بشكل طبيعي: بيع سريع، إضافة مواد، الاستعلام عن الرصيد، أو أي قسم تريده.",
            f"{hour_greeting()}. جاهز أساعدك خطوة بخطوة. يمكنك القول مثلاً: أضف سكر للسلة، كم باقي الأرز، مبيعات اليوم، أو افتح الجرد.",
        ]
    elif intent == "pos_add" and ok:
        pool = [
            f"حاضر. أضفت «{name}»" + (f" بكمية {q}" if q else "") + " إلى سلة نقطة البيع. يمكنك إضافة مادة أخرى، أو قول كمان واحد، أو ادفع لإتمام البيع.",
            f"تم بنجاح. «{name}»" + (f" × {q}" if q else "") + " صارت في الكارت. إذا حابب تعدّل الكمية قل: خلي الكمية ثم الرقم، أو اسأل شو بالسلة.",
        ]
    elif intent == "pos_add" and not ok:
        pool = [
            f"عذراً، لم أجد في المخزون مادة تطابق «{name}». جرّب اسماً أقرب، أو أنشئ المادة بقول: أنشئ مادة {name} بسعر ثم الرقم.",
            f"ما قدرت أطابق «{name}» مع المواد الحالية. تأكد من الاسم، أو افتح المواد وراجع التسمية.",
        ]
    elif intent == "pos_pay":
        pool = [
            "فتحت شاشة الدفع في نقطة البيع. راجع الإجمالي ثم أكمل التحصيل من الشاشة.",
            "تم. شاشة إتمام الدفع جاهزة أمامك الآن.",
        ]
    elif intent == "pos_clear_ask":
        pool = [
            "هل تريد تفريغ سلة المبيعات بالكامل؟ هذا سيحذف كل البنود. قل نعم للتأكيد أو لا للإلغاء.",
        ]
    elif intent == "pos_clear_done":
        pool = [
            "تم تفريغ السلة بالكامل. السلة فارغة الآن ويمكنك البدء ببيع جديد.",
        ]
    elif intent == "cancelled":
        pool = [
            "حسناً، ألغيت الأمر ولم أنفّذ أي تغيير.",
            "تم الإلغاء. المكالمة ما زالت مستمرة إذا احتجت أمراً آخر.",
        ]
    elif intent == "navigate":
        label = ar_section_label(extra) or "القسم"
        pool = [
            f"تم. فتحت {label} من أجلك. يمكنك متابعة الأوامر الصوتية مباشرة.",
            f"روّحت إلى {label}. قل لي ماذا تريد أن نفعل هنا.",
        ]
    elif intent == "stock":
        pool = [extra or "هذا ملخص رصيد المادة من المخزون."]
    elif intent == "pulse":
        pool = [extra or "هذا ملخص سريع لوضع المحل."]
    elif intent == "crisis_ask":
        pool = [
            "طلبت تفعيل وضع الطوارئ، وسيتم تجميد سعر الصرف. هل تؤكد؟ قل نعم أو لا.",
        ]
    elif intent == "crisis_on":
        pool = [
            "تم تفعيل وضع الطوارئ. سعر الصرف مجمّد حالياً حتى تلغي الوضع بقول: إلغاء الطوارئ.",
        ]
    elif intent == "crisis_off":
        pool = [
            "أُلغي وضع الطوارئ وعاد التعامل مع سعر الصرف كالمعتاد.",
        ]
    elif intent == "help":
        pool = [extra or (
            "يمكنك القول: بيع سريع، جرد، مواد، عملاء، مالية، تقارير. "
            "في الكاشير: أضف اسم المادة، كمان واحد، شو بالسلة، ادفع، احذف الأخير. "
            "استعلام: كم باقي مع الاسم، مبيعات اليوم، كم الصندوق، ملخص. "
            "وللإنهاء: إيقاف."
        )]
    elif intent == "unknown":
        pool = [
            "لم أفهم الطلب بوضوح. يمكنك إعادة صياغته، أو قول مساعدة لعرض أمثلة الأوامر المتاحة.",
            "عذراً، الصياغة غير واضحة لي. جرّب أمراً أقصر مثل: بيع سريع، أو أضف ثم اسم المادة.",
        ]
    elif intent == "stop":
        pool = [
            "حسناً، أنهي المكالمة الصوتية الآن. يمكنك بدؤها لاحقاً من الزر في الأعلى.",
        ]
    elif intent == "message":
        pool = [extra or "تم."]
    else:
        pool = [extra or "تم تنفيذ الطلب."]

    text = random.choice(pool)
    if extra and intent in ("stock", "pulse", "help", "message") and extra not in text:
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
            return "عندما تنتهي قل ادفع لإتمام العملية."
        return "يمكنك إضافة مادة أخرى الآن أو مراجعة السلة."
    if intent == "navigate" and (section or "") == "pos":
        return "قل اسم المادة مباشرة لإضافتها إلى السلة."
    if intent == "stock" and name:
        return "إذا رغبت بالبيع قل بيع سريع ثم اسم المادة."
    if intent == "unknown" and (section or "") == "pos":
        return "في نقطة البيع يكفي أن تقول اسم المادة."
    return ""


def resolve_item_name(db_or_repo, query: str, *, limit: int = 8) -> list[dict]:
    """Rank catalog rows by simple Arabic-aware similarity.

    Tolerates the definite article («السكر» → «سكر ناعم») by scoring against
    both the raw query and its article-stripped form, keeping the best.
    """
    q = _norm(query)
    if not q:
        return []
    # candidate query forms: as-spoken + article-stripped (and vice-versa:
    # a catalog name may carry «ال» the spoken form lacks)
    q_forms = [q]
    if q.startswith("ال") and len(q) > 3:
        q_forms.append(q[2:])
    else:
        q_forms.append("ال" + q)
    rows: list[dict] = []
    # Definite-article tolerance: «السكر» must find «سكر ناعم» — try the
    # as-spoken form first, then the article-stripped one.
    q_stripped = q[2:] if q.startswith("ال") and len(q) > 3 else q
    search_forms: list[str] = []
    for f in (query.strip(), q_stripped):
        f = (f or "").strip()
        if f and f not in search_forms:
            search_forms.append(f)
    try:
        if hasattr(db_or_repo, "list"):
            for sf in search_forms:
                rows = db_or_repo.list(search=sf, limit=limit * 2) or []
                if rows:
                    break
        elif hasattr(db_or_repo, "connect"):
            with db_or_repo.connect() as conn:
                for sf in search_forms:
                    cur = conn.execute(
                        "SELECT id, name, quantity, selling_price FROM items "
                        "WHERE item_type='مخزون' AND name LIKE ? ORDER BY name LIMIT ?",
                        (f"%{sf}%", limit * 2),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                    if rows:
                        break
    except Exception:
        return []

    scored: list[tuple[float, dict]] = []
    for r in rows:
        name = _norm(str(r.get("name") or ""))
        if not name:
            continue
        # best score across query forms and name with/without article
        name_forms = [name]
        if name.startswith("ال") and len(name) > 3:
            name_forms.append(name[2:])
        score = 0.0
        for qf in q_forms:
            for nf in name_forms:
                if nf == qf:
                    s = 100
                elif nf.startswith(qf) or qf.startswith(nf):
                    s = 80
                elif qf in nf:
                    s = 60 + max(0, 20 - abs(len(nf) - len(qf)))
                else:
                    qt, nt = set(qf.split()), set(nf.split())
                    s = 40 + 10 * len(qt & nt) if qt & nt else 0
                if s > score:
                    score = s
        if score <= 0:
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
    "ar_section_label",
]


# قاموس عبارات حديث عام → نية مبسطة (للردود والتحويل الخفيف)
CONVERSE_DICT: list[tuple[tuple[str, ...], str]] = [
    (("مرحبا", "هلا", "السلام", "سلام", "صباح", "مساء"), "greet"),
    (("شكرا", "مشكور", "تسلم", "يعطيك العافية"), "thanks"),
    (("كيفك", "كيف حالك", "شو اخبارك"), "howto"),
    (("ماذا تستطيع", "وش تقدر", "شو بتقدر", "امثله", "أمثلة"), "help"),
    (("كرر", "عيد", "نفس الأمر", "كمان مرة"), "repeat"),
    (("تراجع", "الغاء الاخير", "إلغاء الأخير"), "undo"),
]


def match_converse(text: str) -> str | None:
    t = _norm(text)
    for keys, intent in CONVERSE_DICT:
        if any(k in t for k in keys):
            return intent
    return None


def reply_converse(intent: str) -> str:
    if intent == "greet":
        return reply_for("greet")
    if intent == "thanks":
        return "العفو، موجود لأي أمر تاني في المحل."
    if intent == "howto":
        return "الحمد لله. خلّينا نكمل شغل المحل — قل أمرك."
    if intent == "help":
        return reply_for("help")
    if intent == "repeat":
        return "تمام، سأعيد آخر إجراء إن أمكن."
    if intent == "undo":
        return "حسناً، سأتراجع عن آخر إضافة في السلة إن وُجدت."
    return ""
