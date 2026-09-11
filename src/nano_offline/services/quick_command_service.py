"""Quick Command parser — typed Arabic commands (foundation for future voice).

Examples the owner can type (or later speak):
  • بيع سريع
  • جرد
  • نسخ احتياطي
  • كم باقي السكر
  • فتح العملاء
  • تفعيل الطوارئ
  • إلغاء الطوارئ

Returns a structured CommandResult the shell can execute (navigate / action).
Fully offline, no NLP model — keyword + simple patterns only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nano_offline.core.voice_nlu import (
    normalize_ar,
    WORD_NUMBERS,
    analyze_full,
    learn_from_phrase,
    match_amount,
    parse_qty as _nlu_parse_qty,
    strip_trailing_qty_words as _nlu_strip_qty,
)
from nano_offline.core.voice_intelligence import (
    ar_section_label,
    resolve_item_name,
)

if TYPE_CHECKING:
    from nano_offline.core.database import Database
    from nano_offline.repositories.item_repository import ItemRepository


@dataclass(slots=True, frozen=True)
class CommandResult:
    ok: bool
    action: str  # navigate | query | crisis_on | crisis_off | message | unknown
    target: str | None = None
    message: str | None = None
    data: dict | None = None


# Arabic display names for internal section keys — the parser's message
# and the voice reply must read human names («نقطة البيع»), never the
# internal English key («pos»).
_NAV_AR: dict[str, str] = {
    "pos": "نقطة البيع", "stocktake": "الجرد", "items": "المواد والمخزون",
    "customers": "العملاء", "suppliers": "الموردين", "invoices": "الفواتير",
    "sale": "فاتورة البيع", "purchase": "فاتورة الشراء", "finance": "المالية",
    "reports": "التقارير", "dashboard": "اللوحة الرئيسية", "admin": "الإدارة",
    "notifications": "الإشعارات", "security": "الأمان",
}


# (keywords that must ALL appear or any of the alternatives, action, target)
_NAV_PATTERNS: list[tuple[list[str], str, str]] = [
    # POS / sales
    (["نقطة", "بيع"], "navigate", "pos"),
    (["بيع", "سريع"], "navigate", "pos"),
    (["افتح", "البيع"], "navigate", "pos"),
    (["فتح", "البيع"], "navigate", "pos"),
    (["افتح", "نقطة"], "navigate", "pos"),
    (["روح", "البيع"], "navigate", "pos"),
    (["وديني", "البيع"], "navigate", "pos"),
    (["شاشة", "البيع"], "navigate", "pos"),
    (["pos"], "navigate", "pos"),
    (["كاشير"], "navigate", "pos"),
    (["كاش"], "navigate", "pos"),
    # Stocktake
    (["جرد"], "navigate", "stocktake"),
    (["افتح", "الجرد"], "navigate", "stocktake"),
    (["فتح", "الجرد"], "navigate", "stocktake"),
    (["جرد", "مستمر"], "navigate", "stocktake"),
    (["روح", "الجرد"], "navigate", "stocktake"),
    # Sale / purchase invoices
    (["فاتورة", "بيع"], "navigate", "sale"),
    (["فاتوره", "بيع"], "navigate", "sale"),
    (["فاتورة", "شراء"], "navigate", "purchase"),
    (["فاتوره", "شراء"], "navigate", "purchase"),
    (["فواتير"], "navigate", "invoices"),
    (["المبيعات"], "navigate", "invoices"),
    (["مشتريات"], "navigate", "purchase"),
    # Catalog / parties
    (["مواد"], "navigate", "items"),
    (["المخزون"], "navigate", "items"),
    (["مخزون"], "navigate", "items"),
    (["اصناف"], "navigate", "items"),
    (["أصناف"], "navigate", "items"),
    (["منتجات"], "navigate", "items"),
    (["عملاء"], "navigate", "customers"),
    (["الزبائن"], "navigate", "customers"),
    (["زبائن"], "navigate", "customers"),
    (["موردين"], "navigate", "suppliers"),
    (["موردون"], "navigate", "suppliers"),
    (["الموردين"], "navigate", "suppliers"),
    # Finance / reports / admin
    (["تقارير"], "navigate", "reports"),
    (["تقرير"], "navigate", "reports"),
    (["شوف", "التقارير"], "navigate", "reports"),
    (["لوحة"], "navigate", "dashboard"),
    (["رئيسية"], "navigate", "dashboard"),
    (["الرئيسية"], "navigate", "dashboard"),
    (["المنزل"], "navigate", "dashboard"),
    (["إدارة"], "navigate", "admin"),
    (["اعدادات"], "navigate", "admin"),
    (["إعدادات"], "navigate", "admin"),
    (["نسخ", "احتياط"], "navigate", "admin"),
    (["نسخه", "احتياطيه"], "navigate", "admin"),
    (["مالية"], "navigate", "finance"),
    (["صندوق"], "navigate", "finance"),
    (["سندات"], "navigate", "finance"),
    (["مصروفات"], "navigate", "finance"),
    (["مصاريف"], "navigate", "finance"),
    (["خزنه"], "navigate", "finance"),
    (["خزنة"], "navigate", "finance"),
    (["الماليه"], "navigate", "finance"),
    (["إشعارات"], "navigate", "notifications"),
    (["تنبيهات"], "navigate", "notifications"),
    (["اشعارات"], "navigate", "notifications"),
    (["امان"], "navigate", "security"),
    (["أمان"], "navigate", "security"),
    (["دخول"], "navigate", "security"),
    (["عرض", "العملاء"], "navigate", "customers"),
]


class QuickCommandService:
    def __init__(self, db: "Database", *, items: "ItemRepository | None" = None) -> None:
        self.db = db
        self.items = items
        # Wired by AppContext.create() after both services exist; enables
        # the quality-metrics loop (success rate per parse). Optional so
        # standalone construction (tests, tooling) never crashes.
        self.voice_learning = None

    def parse(self, text: str) -> CommandResult:
        """Unified analyzer entry point (recommendation #4).

        NLU (char-ngram classifier + slot extraction) first, legacy regex
        as confirm/override — see ``voice_nlu.analyze_full`` for the merge
        rules. Every caller (typed command bar, POS mic, voice session)
        goes through here, so all three share ONE intent contract.
        """
        from nano_offline.core import voice_nlu
        if voice_nlu.get_classifier().stale:
            voice_nlu.get_classifier().fit()
        result = analyze_full(text, legacy_parse=self._parse_legacy, stock_handler=self._stock_query)
        # NLU materializes stock_query with a name slot only — resolve it
        # against the DB here so EVERY caller gets the same rich result.
        if result.ok and result.action == "stock_query":
            name = ((result.data or {}).get("name") or result.message or "").strip()
            if name:
                result = self._stock_query(name)
        # Quality metrics (audit item #8): every parse outcome is recorded
        # so the admin panel can show the real success rate over time.
        try:
            if self.voice_learning is not None:
                conf = (result.data or {}).get("conf") if isinstance(result.data, dict) else None
                self.voice_learning.log_command(
                    ok=bool(result.ok and result.action != "unknown"),
                    action=result.action,
                    source="command",
                    confidence=float(conf) if conf is not None else None,
                )
        except Exception:
            pass
        # Feedback loop (recommendation #1): successful parses train the
        # on-device classifier; unknowns are already logged by the session.
        if result.ok and result.action not in ("unknown", "message"):
            try:
                learn_from_phrase(result.action, text or "")
            except Exception:
                pass
        return result

    def _parse_legacy(self, text: str) -> CommandResult:
        """Original regex keyword parser — kept intact as the exact-match
        layer the unified analyzer confirms/falls back to."""
        raw = (text or "").strip()
        if not raw:
            return CommandResult(ok=False, action="unknown", message="اكتب أمراً مثل: بيع سريع، جرد، كم باقي السكر")

        normalized = raw.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
        lower = normalized.lower()

        # End continuous voice session
        stop_phrases = (
            "ايقاف الصوت", "إيقاف الصوت", "وقف الاستماع", "انهاء المكالمه", "إنهاء المكالمة",
            "وقف المكالمه", "انهاء الجلسه", "إنهاء الجلسة", "وقف الجلسه", "إيقاف الجلسة",
            "كفاية", "خلاص وقف",
        )
        if any(k in lower for k in stop_phrases) or lower.strip() in ("ايقاف", "إيقاف", "وقف", "توقف"):
            if "طوارئ" not in lower and "ازم" not in lower:
                return CommandResult(ok=True, action="voice_stop", message="تم إيقاف الجلسة الصوتية")

        # Crisis toggles
        if any(k in lower for k in ("تفعيل الطوارئ", "وضع الطوارئ", "ازمه", "أزمة", "ازمة")):
            if any(k in lower for k in ("الغاء", "إلغاء", "اطفئ", "ايقاف", "إيقاف", "وقف")):
                return CommandResult(ok=True, action="crisis_off", message="إلغاء وضع الطوارئ الاقتصادي")
            return CommandResult(ok=True, action="crisis_on", message="تفعيل وضع الطوارئ الاقتصادي")

        if any(k in lower for k in ("الغاء الطوارئ", "إلغاء الطوارئ", "اطفاء الطوارئ")):
            return CommandResult(ok=True, action="crisis_off", message="إلغاء وضع الطوارئ الاقتصادي")


        # Create item: أنشئ مادة X / أضف مادة X بسعر 500
        create_m = re.search(
            r"(?:انشئ|أنشئ|انشاء|إنشاء|اضف مادة|أضف مادة|اضف ماده|أضف ماده|سجل مادة|سجّل مادة|سجل ماده|مادة جديدة|ماده جديده)\s+(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if create_m:
            rest = create_m.group(1).strip(" ؟?،,")
            price = 0.0
            amt = match_amount(rest)
            if amt:
                price = amt[0]
                rest = (rest[: amt[1]] + rest[amt[2]:]).strip(" ،،")
            rest = re.sub(r"\s*(?:بسعر|سعر)\s*$", "", rest).strip()
            # optional qty opening
            oq = 0.0
            qm = re.search(r"(?:بكمية|كمية)\s*(\S+)", rest)
            if qm:
                oq = float(_nlu_parse_qty(qm.group(1)) if _nlu_parse_qty(qm.group(1)) is not None else WORD_NUMBERS.get(normalize_ar(qm.group(1)), 0) or 0)
                rest = (rest[:qm.start()] + rest[qm.end():]).strip(" ،,")
            name = rest.strip()
            # «انشاء مادة لبنة» — drop the redundant leading «مادة»
            name_toks = name.split()
            if len(name_toks) >= 2 and name_toks[0] in ("مادة", "ماده", "صنف", "منتج"):
                name = " ".join(name_toks[1:]).strip()
            if name:
                return CommandResult(
                    ok=True,
                    action="item_create",
                    target="items",
                    message=f"إنشاء مادة {name}",
                    data={"name": name, "selling_price": price, "quantity": oq},
                )

        # Set cart qty: خلي الكمية 5 / كمية السكر 3 / خلّي الأخير 2
        setq = re.search(
            r"(?:خلي|خلّي|اجعل|خلّ|عيّن|عين)\s+(?:الكمية\s+)?(?:(?P<name>.+?)\s+)?(?P<qty>[\d٠-٩]+(?:[.,]\d+)?)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if not setq:
            setq = re.search(
                r"كمية\s+(?P<name>.+?)\s+(?P<qty>[\d٠-٩]+(?:[.,]\d+)?)$",
                normalized,
                flags=re.IGNORECASE,
            )
        if setq:
            qty = self._parse_qty(setq.group("qty"))
            name = (setq.groupdict().get("name") or "").strip()
            if name in ("الاخير", "الأخير", "الاخير", ""):
                name = ""
            return CommandResult(
                ok=True,
                action="pos_set_qty",
                target="pos",
                message=f"تعيين كمية {name or 'الأخير'} إلى {qty:g}",
                data={"name": name, "qty": qty},
            )

        if any(k in lower for k in (
            "مبيعات اليوم", "بيع اليوم", "كم بعنا اليوم", "كم مبيعات اليوم",
            "شو مبيعات اليوم", "حركة اليوم", "كم الفواتير اليوم",
        )):
            return CommandResult(ok=True, action="today_sales", message="مبيعات اليوم")

        # Expense / cash phrases (navigate finance)
        if any(k in lower for k in ("سجل مصروف", "اضف مصروف", "أضف مصروف", "مصروف جديد")):
            return CommandResult(ok=True, action="navigate", target="finance", message="فتح المالية لتسجيل مصروف")

        if any(k in lower for k in ("سند قبض", "قبض من عميل", "استلام من عميل")):
            return CommandResult(ok=True, action="navigate", target="finance", message="فتح المالية — سند قبض")

        if any(k in lower for k in ("سند دفع", "دفع لمورد", "سداد مورد")):
            return CommandResult(ok=True, action="navigate", target="finance", message="فتح المالية — سند دفع")

        if any(k in lower for k in ("نسخه احتياطيه", "نسخة احتياطية", "اعمل نسخ", "خذ نسخ", "backup")):
            return CommandResult(ok=True, action="navigate", target="admin", message="فتح الإدارة للنسخ الاحتياطي")

        if any(k in lower for k in ("من هو المدين", "اكبر دين", "أكبر دين", "ديون العملاء", "الذمم")):
            return CommandResult(ok=True, action="navigate", target="customers", message="فتح العملاء لمراجعة الذمم")

        if any(k in lower for k in ("كم الصندوق", "رصيد الصندوق", "كم بالصندوق", "حالة الصندوق")):
            return CommandResult(ok=True, action="cash_status", message="حالة الصندوق")



        # POS: أضف X / زيد X / حط X [عدد]
        # Examples: أضف سكر، أضف 3 سكر، زيد رز اثنين، حط حليب
        pos_add = re.search(
            r"(?:اضف|أضف|زيد|زود|حط|ضيف)\s+(?:(?P<qty>[\d٠-٩]+(?:[.,]\d+)?)\s+)?(?P<name>.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if pos_add:
            name = (pos_add.group("name") or "").strip(" ؟?،,")
            # Defer to multi-item parser when conjunctions present — including
            # the NORMAL Arabic glued form «سكر وحليب» (و attached to the
            # next word, no space after it).
            if re.search(r"\s+و|،|,", name):
                pass  # fall through
            else:
                qty_raw = pos_add.group("qty")
                qty = 1.0
                if qty_raw:
                    qty = self._parse_qty(qty_raw)
                name2, qty2 = self._strip_trailing_qty_words(name, qty)
                # leading written form «ضيف اثنين حليب» (numeral first)
                toks = name2.split()
                if len(toks) >= 2 and toks[0] in WORD_NUMBERS and qty2 == qty:
                    name2 = " ".join(toks[1:]).strip()
                    qty2 = float(WORD_NUMBERS[toks[0]])
                amt2 = match_amount(name2)
                if amt2:
                    name2 = (name2[: amt2[1]] + name2[amt2[2]:]).strip(" ،،")
                if name2:
                    return CommandResult(
                        ok=True,
                        action="pos_add",
                        target="pos",
                        message=f"إضافة إلى السلة: {name2} × {qty2:g}",
                        data={"name": name2, "qty": qty2},
                    )

        if any(k in lower for k in ("اتمام الدفع", "إتمام الدفع", "ادفع", "ادفع الان", "ادفع الآن", "حاسب", "تحصيل", "دفع")):
            return CommandResult(ok=True, action="pos_pay", target="pos", message="فتح الدفع")

        if any(k in lower for k in ("افرغ السله", "أفرغ السلة", "امسح السله", "مسح السلة", "فرغ الكارت", "افرغ الكارت")):
            return CommandResult(ok=True, action="pos_clear", target="pos", message="تفريغ سلة نقطة البيع")

        if any(k in lower for k in ("احذف الاخير", "احذف الأخير", "شيل الاخير", "شيل الأخير", "ارجع اخر", "تراجع", "undo")):
            return CommandResult(ok=True, action="pos_remove_last", target="pos", message="حذف آخر مادة من السلة")

        if any(k in lower for k in ("شو بالسله", "شو بالسلة", "محتوى السله", "محتوى السلة", "كم الاجمالي", "كم الإجمالي", "ملخص السله", "ملخص السلة", "عرض السله", "عرض السلة")):
            return CommandResult(ok=True, action="pos_cart_summary", target="pos", message="ملخص السلة")

        if any(k in lower for k in ("اكتم الصوت", "اكتم الرد", "صمت", "بدون صوت", "كتم النطق", "اطفي الصوت", "اطفئ الصوت")):
            return CommandResult(ok=True, action="tts_mute", message="كتم الردود الصوتية")

        if any(k in lower for k in ("شغل الصوت", "فعّل الصوت", "فعل الصوت", "رجّع الصوت", "رجع الصوت", "تفعيل النطق")):
            return CommandResult(ok=True, action="tts_unmute", message="تفعيل الردود الصوتية")

        # Multi-item: أضف سكر وحليب / أضف سكر و رز
        multi = re.search(
            r"(?:اضف|أضف|حط|ضيف)\s+(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if multi and (" و" in multi.group(1) or "،" in multi.group(1)):
            raw_list = multi.group(1)
            # Split on «و» as a conjunction: standalone, glued («وحليب»),
            # or spaced — but never inside a word (عنوان، جواز).
            parts = re.split(r"\s+و(?=\S)|\s+و\s+|[،,]", raw_list)
            parts = [p.strip(" ؟?،,") for p in parts if p.strip(" ؟?،,")]
            if len(parts) >= 2:
                items = []
                for part in parts[:6]:
                    # optional leading qty (digit or written form «اثنين رز»)
                    m2 = re.match(r"^(?P<qty>[\d٠-٩]+(?:[.,]\d+)?)\s+(?P<name>.+)$", part)
                    if m2:
                        items.append({"name": m2.group("name").strip(), "qty": self._parse_qty(m2.group("qty"))})
                    else:
                        toks = part.split()
                        if len(toks) >= 2 and toks[0] in WORD_NUMBERS:
                            items.append({"name": " ".join(toks[1:]).strip(), "qty": float(WORD_NUMBERS[toks[0]])})
                            continue
                        name2, qty2 = self._strip_trailing_qty_words(part, 1.0)
                        amt3 = match_amount(name2)
                        if amt3:
                            name2 = (name2[: amt3[1]] + name2[amt3[2]:]).strip(" ،،")
                        items.append({"name": name2, "qty": qty2})
                if items:
                    return CommandResult(
                        ok=True,
                        action="pos_add_many",
                        target="pos",
                        message="إضافة عدة مواد",
                        data={"items": items},
                    )

        # Stock query: كم باقي X / رصيد X / كمية X
        stock_match = re.search(
            r"(?:كم\s*باقي|رصيد|كميه|كمية|كمية\s*المتبقية)\s+(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if stock_match:
            query = stock_match.group(1).strip(" ؟?،,")
            return self._stock_query(query)

        # Backup
        if any(k in lower for k in ("نسخه احتياط", "نسخة احتياط", "باك اب", "backup", "نسخ احتياط")):
            return CommandResult(ok=True, action="navigate", target="admin", message="فتح النسخ الاحتياطي")

        # Navigation
        for keys, action, target in _NAV_PATTERNS:
            nkeys = [k.replace("ة", "ه") for k in keys]
            if all(k in lower for k in nkeys) or (len(nkeys) == 1 and nkeys[0] in lower):
                return CommandResult(ok=True, action=action, target=target, message=f"فتح: {_NAV_AR.get(target, target)}")

        # Single-token shortcuts
        shortcuts = {
            "بيع": ("navigate", "pos"),
            "كاشير": ("navigate", "pos"),
            "كاش": ("navigate", "pos"),
            "جرد": ("navigate", "stocktake"),
            "عملاء": ("navigate", "customers"),
            "زبائن": ("navigate", "customers"),
            "موردين": ("navigate", "suppliers"),
            "تقارير": ("navigate", "reports"),
            "مواد": ("navigate", "items"),
            "مخزون": ("navigate", "items"),
            "فواتير": ("navigate", "invoices"),
            "مالية": ("navigate", "finance"),
            "صندوق": ("navigate", "finance"),
            "مصاريف": ("navigate", "finance"),
            "إدارة": ("navigate", "admin"),
            "اعدادات": ("navigate", "admin"),
            "إعدادات": ("navigate", "admin"),
            "رئيسية": ("navigate", "dashboard"),
            "اشعارات": ("navigate", "notifications"),
            "إشعارات": ("navigate", "notifications"),
        }
        token = lower.strip()
        if token in shortcuts:
            a, t = shortcuts[token]
            return CommandResult(ok=True, action=a, target=t, message=f"فتح: {ar_section_label(t)}")

        return CommandResult(
            ok=False,
            action="unknown",
            message="لم أفهم الأمر. جرّب: بيع سريع، جرد، فتح العملاء، كم باقي السكر، تفعيل الطوارئ",
        )


    # Canonical implementations now live in core.voice_nlu (single source
    # of truth shared with the classifier); these thin wrappers preserve
    # the historical public API used by voice_session and views.
    @staticmethod
    def _parse_qty(raw: str) -> float:
        v = _nlu_parse_qty(raw)
        return float(v) if v is not None else 1.0

    _strip_trailing_qty_words = staticmethod(_nlu_strip_qty)

    def _stock_query(self, name_query: str) -> CommandResult:
        name_query = name_query.strip()
        if not name_query:
            return CommandResult(ok=False, action="unknown", message="حدد اسم المادة")
        rows = resolve_item_name(self.db if self.items is None else self.items, name_query, limit=5)
        if not rows:
            # fallback raw SQL via db
            try:
                with self.db.connect() as conn:
                    raw = conn.execute(
                        """SELECT id, name, quantity, selling_price FROM items
                           WHERE item_type='مخزون' AND name LIKE ? ORDER BY name LIMIT 5""",
                        (f"%{name_query}%",),
                    ).fetchall()
                    rows = [dict(r) for r in raw]
            except Exception as exc:
                return CommandResult(ok=False, action="message", message=str(exc))
        if not rows:
            return CommandResult(ok=True, action="message", message=f"ما في مادة تطابق «{name_query}»")
        if len(rows) == 1:
            d = rows[0]
            qty = float(d.get("quantity") or 0)
            return CommandResult(
                ok=True,
                action="query",
                target="items",
                message=f"«{d.get('name')}» باقي منه {qty:g}",
                data={"item_id": int(d["id"]), "quantity": qty, "name": d.get("name")},
            )
        lines = [f"• {r.get('name')}: {float(r.get('quantity') or 0):g}" for r in rows]
        return CommandResult(
            ok=True,
            action="query",
            target="items",
            message="أكثر من نتيجة:\n" + "\n".join(lines),
            data={"matches": rows},
        )


__all__ = ["QuickCommandService", "CommandResult"]
