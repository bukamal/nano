"""Unified lightweight Arabic intent+slot analyzer for Nano voice commands.

Pure-stdlib (no third-party deps, fully offline) — recommendation #4+1:

  • ``normalize_ar``  — one shared normalization for every voice layer
    (hamza/alef/ta-marbuta folding, tatweel/diacritics strip, digit fold).
  • ``char_ngrams``   — character 2..3-gram bag, robust to STT typos and
    dialect spellings (سكر→سكرر, حليب→حلب) without any external model.
  • ``IntentClassifier`` — centroid/cosine classifier (a TF-IDF-like
    scheme with IDF weights trained on-device) over a curated seed set of
    Syrian-dialect command phrasings, *plus* phrases the assistant
    successfully learned on this device (``voice_phrase_memory``) *plus*
    recurring unknown phrases promoted from ``voice_unknown_log``.
  • ``slot extraction`` — qty / price / item-name / nav-target extraction
    that tolerates word order (الكمية ٥ خلي == خلي الكمية 5), compound
    «و» lists, written-out Syrian numerals, and trailing quantity words.
  • ``analyze(text)`` returns ``(intent, slots, confidence)`` — the
    *unified* analyzer both the typed command bar and the voice session
    go through (recommendation #4).

Design contract:
  • Confidence is calibrated so >= 0.55 means "act", 0.35..0.55 means
    "probably — allow the legacy regex layer to veto/confirm", < 0.35
    means "unknown".  ``analyze_full`` runs the NLU first and the legacy
    regex second, then merges: regex wins ties because it is exact.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Shared normalization (single source of truth for all voice layers)
# ---------------------------------------------------------------------------

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")  # harakat + tatweel
_NON_WORD = re.compile(r"[^\w\u0600-\u06ff\s]")


def normalize_ar(text: str) -> str:
    """Canonical normalization used by NLU, learning, and matching alike."""
    t = (text or "").strip().casefold()
    t = t.translate(_ARABIC_DIGITS)
    t = _DIACRITICS.sub("", t)
    for a, b in (
        ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"),
        ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي"), ("ء", ""),
    ):
        t = t.replace(a, b)
    t = _NON_WORD.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def char_ngrams(text: str, *, lo: int = 2, hi: int = 3) -> Counter:
    """Character-gram bag over a padded, space-aware string."""
    t = normalize_ar(text)
    if not t:
        return Counter()
    padded = f" {t} "
    grams: Counter = Counter()
    for n in range(lo, hi + 1):
        for i in range(len(padded) - n + 1):
            g = padded[i : i + n]
            if g.strip():  # skip pure-space grams
                grams[g] += 1
    return grams


# ---------------------------------------------------------------------------
# Numerals (digits + written Syrian forms), tolerant to order
# ---------------------------------------------------------------------------

WORD_NUMBERS: dict[str, float] = {
    "واحد": 1, "واحده": 1, "وحده": 1,
    "اثنين": 2, "اثنان": 2, "ثنين": 2, "تنين": 2, "زوج": 2,
    "ثلاثه": 3, "ثلاث": 3, "تلابه": 3, "تلاته": 3, "تلته": 3,
    "اربعه": 4, "اربع": 4,
    "خمسه": 5, "خمس": 5,
    "سته": 6, "ست": 6,
    "سبعه": 7, "سبع": 7,
    "ثمانيه": 8, "ثمانيا": 8,
    "تسعه": 9, "تسع": 9,
    "عشره": 10, "عشر": 10,
    "عشرين": 20, "ثلاثين": 30, "اربعين": 40, "خمسين": 50,
    "ستين": 60, "سبعين": 70, "ثمانين": 80, "تسعين": 90,
    "مية": 100, "ميه": 100, "مئه": 100, "ماية": 100,
    "ميتين": 200,
    "خمسميه": 500, "خمسمية": 500, "خمسماية": 500, "خمسمايه": 500,
    "الف": 1000, "الفين": 2000,
}

_NUM_TOKEN = re.compile(r"\d+(?:[.,]\d+)?")

# ---------------------------------------------------------------------------
# Written-out amounts (Syrian dialect) — «بسعر خمسمئة» == 500
# ---------------------------------------------------------------------------

_AMOUNT_WORDS: dict[str, float] = {
    "ميه": 100, "مية": 100, "مئة": 100, "مئه": 100,
    "ميتين": 200, "مئتين": 200,
    "ثلاثميه": 300, "ثلاثمئة": 300, "ثلاثمئه": 300,
    "اربعميه": 400, "اربعمئة": 400, "اربعمئه": 400,
    "خمسميه": 500, "خمسمئة": 500, "خمسمئه": 500, "خمسمية": 500,
    "ستميه": 600, "ستمئة": 600,
    "سبعميه": 700, "سبعمئة": 700,
    "ثمانميه": 800, "ثمانمئة": 800,
    "تسعميه": 900, "تسعمئة": 900,
    "الف": 1000, "ألف": 1000, "الفين": 2000, "ألفين": 2000,
}
_TENS_MULT: dict[str, float] = {
    "واحد": 1, "اثنين": 2, "تنين": 2, "ثلاث": 3, "ثلاثه": 3,
    "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6,
    "سبع": 7, "سبعه": 7, "ثمان": 8, "ثمانيه": 8, "تسع": 9, "تسعه": 9,
    "عشر": 10, "عشره": 10,
}
_AMOUNT_RE = re.compile(r"(?:بسعر|سعر)\s*(\d+(?:[.,]\d+)?)")
_WRITTEN_AMOUNT_RE = re.compile(r"(?:بسعر|سعر)\s+([^\s]+)(?:\s+([^\s]+))?")

def match_amount(text: str) -> tuple[float, int, int] | None:
    """Find a price span «بسعر/سعر <amount>» → (value, start, end) | None.

    Accepts digits (incl. Arabic-Indic: ٨٠٠) and written Syrian amounts:
    «بسعر خمسمئة» → 500, «بسعر خمس مئة» → 500, «بسعر ألف» → 1000.
    """
    t = text or ""
    m = _AMOUNT_RE.search(t)
    if m:
        try:
            val = float(m.group(1).translate(_ARABIC_DIGITS).replace(",", "."))
        except ValueError:
            val = 0.0
        return (val, m.start(), m.end()) if val > 0 else None
    m2 = _WRITTEN_AMOUNT_RE.search(t)
    if m2:
        toks = [g for g in (m2.group(1), m2.group(2)) if g]
        if len(toks) == 2 and toks[1] in _AMOUNT_WORDS and toks[0] in _TENS_MULT:
            return (_TENS_MULT[toks[0]] * _AMOUNT_WORDS[toks[1]], m2.start(), m2.end())
        if toks and toks[0] in _AMOUNT_WORDS:
            return (_AMOUNT_WORDS[toks[0]], m2.start(), m2.end())
    return None



def parse_qty(raw: str) -> float | None:
    """Digit or written-number → float. None when nothing numeric found."""
    t = normalize_ar(raw)
    if not t:
        return None
    m = _NUM_TOKEN.search(t)
    if m:
        try:
            v = float(m.group(0).replace(",", "."))
            return v if v > 0 else None
        except ValueError:
            return None
    for tok in t.split():
        if tok in WORD_NUMBERS:
            return float(WORD_NUMBERS[tok])
    return None


def strip_trailing_qty_words(name: str, qty: float) -> tuple[str, float]:
    """«سكر اثنين» → (سكر, 2.0). Keeps explicit digit qty untouched."""
    parts = (name or "").strip().split()
    if len(parts) >= 2 and parts[-1] in WORD_NUMBERS:
        return " ".join(parts[:-1]).strip(), float(WORD_NUMBERS[parts[-1]])
    return (name or "").strip(), qty


# ---------------------------------------------------------------------------
# Intent seed phrases — Syrian-dialect aware, normalized at build time
# ---------------------------------------------------------------------------

# intent -> list of example utterances (the more variants, the better the
# centroid separation). These are *seeds*; on-device learning adds more.
SEED_PHRASES: dict[str, list[str]] = {
    "pos_add": [
        "اضف سكر", "أضف سكر", "ضيف سكر", "زيد سكر", "حط سكر", "زود سكر",
        "اضف 3 سكر", "أضف 5 حليب", "ضيف اثنين رز", "زيد رز اثنين",
        "اضف سكر وحليب", "أضف 3 سكر وحليب", "حط كولا ورز",
        "شيل سكر", "منيل سكر", "بدون سكر", "نقي سكر",
        "كمان واحد", "كمان اثنين", "نفس الشي", "زيد بعد",
    ],
    "pos_pay": [
        "ادفع", "ادفع الان", "اتمام الدفع", "حاسب", "حساب", "انهي الفاتوره",
        "خلص", "سدد", "دفع", "كمل الدفع",
    ],
    "pos_clear": [
        "افرغ السله", "أفرغ السلة", "امسح السله", "مسح السلة", "فرغ الكارت",
        "بدء سله جديده", "سله جديده", "الغي السله",
    ],
    "pos_remove_last": [
        "احذف الاخير", "شيل الاخير", "ارجع اخر", "تراجع", ".undo",
        "الغي الاخير", "امسح الاخير",
    ],
    "pos_cart_summary": [
        "شو بالسله", "ملخص السله", "عرض السله", "كم الاجمالي", "محتوى السله",
        "شو بالسلة", "كم صار الحساب",
    ],
    "pos_set_qty": [
        "خلي الكمية 5", "كميه السكر 3", "اجعل الكمية 2", "خلي الاخير 2",
        "خلي كمية الحليب 4", "عدل الكمية",
    ],
    "stock_query": [
        "كم باقي السكر", "رصيد السكر", "كمية الحليب", "شو باقي بالرز",
        "كم باقي", "الرصيد", "كم متبقي",
    ],
    "today_sales": [
        "مبيعات اليوم", "كم بعنا اليوم", "شو مبيعات اليوم", "حركه اليوم",
        "كم الفواتير اليوم", "اليوم كم بعنا",
    ],
    "cash_status": [
        "كم الصندوق", "رصيد الصندوق", "شو بالصندوق", "حاله الصندوق", "كم بالخزنه",
    ],
    "item_create": [
        "انشئ مادة", "أنشئ مادة", "اضف مادة جديدة", "سجل مادة",
        "مادة جديدة", "انشاء مادة", "سجل ماده", "سجل مادة جديده",
        "انشاء ماده جديده", "انشئ ماده عسل بسعر", "سجل ماده عسل",
    ],
    "crisis_on": [
        "تفعيل الطوارئ", "وضع الطوارئ", "ازمه", "أزمة", "شغل الطوارئ",
    ],
    "crisis_off": [
        "الغاء الطوارئ", "إلغاء الطوارئ", "اطفاء الطوارئ", "اطفئ الطوارئ", "الغي الازمة",
    ],
    "tts_mute": [
        "اكتم الصوت", "صمت", "بدون صوت", "اطفي الصوت", "سكت",
    ],
    "tts_unmute": [
        "شغل الصوت", "فعل الصوت", "رجع الصوت", "كلم", "تفعيل النطق",
    ],
    "voice_stop": [
        "ايقاف الصوت", "وقف الاستماع", "انهاء المكالمه", "وقف المكالمه",
        "انتهي", "كفاية", "خلاص وقف", "وقف", "توقف", "ايقاف",
    ],
    "teach": [
        "تعلم ان بيبسي تعني بيبسي كولا", "علم هلال تعني الملاك",
        "علمني", "احفظ هذا الاسم",
    ],
    "memory_stats": [
        "ماذا تعلمت", "شو تعلمت", "ذاكرة الصوت", "كم عبارة حفظت",
    ],
    "help": [
        "مساعدة", "شو بتقدر", "ماذا اقول", "الاوامر", "امثله", "ساعدني",
    ],
    "greet": [
        "مرحبا", "هلا", "السلام عليكم", "صباح الخير", "مساء الخير", "شو الاخبار",
    ],
    "thanks": [
        "شكرا", "مشكور", "تسلم", "يعطيك العافية",
    ],
    "navigate_pos": [
        "بيع سريع", "نقطة بيع", "افتح البيع", "فتح البيع", "روح البيع",
        "وديني البيع", "شاشة البيع", "كاشير", "pos", "البيع السريع",
    ],
    "navigate_stocktake": ["جرد", "افتح الجرد", "روح الجرد", "جرد مستمر", "بدء جرد"],
    "navigate_invoices": ["فواتير", "المبيعات", "سجل الفواتير", "كل الفواتير"],
    "navigate_items": ["مواد", "المخزون", "اصناف", "منتجات", "ادارة المواد", "المواد"],
    "navigate_customers": ["عملاء", "الزبائن", "زبائن", "افتح العملاء", "الحسابات"],
    "navigate_suppliers": ["موردين", "الموردين", "موردون", "الممولين"],
    "navigate_reports": ["تقارير", "تقرير", "شوف التقارير", "ارقام"],
    "navigate_dashboard": ["لوحة", "رئيسية", "الرئيسية", "المنزل", "ارجع للرئيسية"],
    "navigate_admin": ["ادارة", "اعدادات", "الاعدادات", "نسخ احتياطي", "نسخه احتياطيه"],
    "navigate_finance": ["مالية", "صندوق", "سندات", "مصروفات", "مصاريف", "خزنه", "الخزنه", "الماليه", "سجل مصروف"],
    "navigate_notifications": ["اشعارات", "تنبيهات", "الاشعارات"],
    "navigate_security": ["امان", "أمان", "دخول", "الحمايه"],
}


def _nav_target(intent: str) -> str | None:
    if intent.startswith("navigate_"):
        return intent[len("navigate_"):]
    return None


# ---------------------------------------------------------------------------
# Classifier — centroid cosine over IDF-weighted char-ngrams
# ---------------------------------------------------------------------------


class IntentClassifier:
    """Tiny on-device intent model. Train once at startup, re-train when
    the learning service gains new phrases (cheap: a few hundred vectors)."""

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}
        self._centroids: dict[str, Counter] = {}
        self._docs: int = 0
        self._extra: dict[str, list[str]] = {}  # intent -> learned phrases
        self._version: int = 0

    # ---- training -----------------------------------------------------

    def add_learned(self, intent: str, phrase: str) -> None:
        """Inject a phrase the user actually used successfully."""
        self._extra.setdefault(intent, []).append(phrase)
        self._version += 1  # mark stale; trainer decides when to fit

    def fit(self) -> None:
        """(Re)build IDF + centroids from seeds + learned phrases."""
        docs: dict[str, list[Counter]] = {}
        for intent, examples in SEED_PHRASES.items():
            docs.setdefault(intent, []).extend(char_ngrams(x) for x in examples)
        for intent, phrases in self._extra.items():
            docs.setdefault(intent, []).extend(char_ngrams(p) for p in phrases)
        # doc frequency over grams
        df: Counter = Counter()
        total = 0
        for intent, grams_list in docs.items():
            for grams in grams_list:
                total += 1
                df.update(grams.keys())
        self._docs = total
        self._idf = {
            g: math.log((total + 1) / (cnt + 1)) + 1.0 for g, cnt in df.items()
        }
        self._centroids = {}
        for intent, grams_list in docs.items():
            acc: Counter = Counter()
            for grams in grams_list:
                acc.update(self._weight(grams))
            n = len(grams_list) or 1
            centroid = Counter({g: v / n for g, v in acc.items()})
            self._centroids[intent] = self._l2(centroid)
        self._version = 0

    @property
    def stale(self) -> bool:
        return self._version > 0

    def _weight(self, grams: Counter) -> Counter:
        return Counter({g: cnt * self._idf.get(g, 1.0) for g, cnt in grams.items()})

    @staticmethod
    def _l2(c: Counter) -> Counter:
        norm = math.sqrt(sum(v * v for v in c.values())) or 1.0
        return Counter({g: v / norm for g, v in c.items()})

    # ---- inference ------------------------------------------------------

    def classify(self, text: str) -> list[tuple[str, float]]:
        """Ranked [(intent, confidence)] — cosine similarity, descending."""
        if not self._centroids:
            self.fit()
        vec = self._l2(self._weight(char_ngrams(text)))
        scored = [
            (intent, sum(vec[g] * c[g] for g in vec if g in c))
            for intent, c in self._centroids.items()
        ]
        scored.sort(key=lambda x: -x[1])
        return scored


# ---------------------------------------------------------------------------
# Slot extraction — the grammar-light part the classifier cannot do
# ---------------------------------------------------------------------------

_ADD_VERBS = ("اضف", "ضيف", "زيد", "حط", "زود", "شيل", "منيل", "نقي", "بدون", "ازل", "انزل")
_SETQ_VERBS = ("خلي", "اجعل", "عين", "عدل", "خلّي")
_CREATE_VERBS = ("انشئ", "انشاء", "سجل مادة", "اضف مادة", "مادة جديدة")


def _split_conjuncts(text: str) -> list[str]:
    """Split compound «و» lists but protect «و» glued inside item names
    (e.g. «زعتر و نعنع» splits fine; «جبنة» never contains standalone و)."""
    parts = re.split(r"\s+و\s+|[،,]", text)
    return [p.strip(" ؟?.,") for p in parts if p and p.strip(" ؟?.,")]


def _parse_qty_token(tok: str) -> float | None:
    """رقم (مكتوب/هندي/لفظي عامي) → قيمة رقمية، أو None إن لم يكن عدداً."""
    tok = (tok or "").strip(" ،،؟?.")
    v = parse_qty(tok)
    if v is not None:
        return v
    n = normalize_ar(tok)
    return float(WORD_NUMBERS[n]) if n in WORD_NUMBERS else None


def extract_slots(text: str, intent: str) -> dict[str, Any]:
    """Intent-specific slot extraction. Always returns a dict (may be empty).

    Names are taken from the RAW text (only punctuation trimmed) so item
    creation preserves the user's original spelling — normalization is for
    matching, never for stored data.
    """
    raw = (text or "").strip().rstrip("؟?،.").strip()
    t = normalize_ar(text)
    slots: dict[str, Any] = {}

    # verb-prefix matchers that tolerate hamza variants on the raw text
    def _raw_strip_verb(core: str, verbs: tuple[str, ...]) -> str:
        for v in sorted(verbs, key=len, reverse=True):
            m = re.match(rf"^{v}\s+(.+)$", core)
            if m:
                return m.group(1).strip()
        return core

    if intent in ("pos_add", "item_create"):
        # Work on the RAW text for the name; the leading verb is matched in
        # BOTH raw and normalized form («أنشئ» keeps its hamza in the raw
        # name while normalized verbs like «انشئ» still match it).
        core = raw
        for v in sorted(_ADD_VERBS + _CREATE_VERBS, key=len, reverse=True):
            m = re.match(rf"^{v}\s+(.+)$", core)
            if m:
                core = m.group(1).strip()
                break
            # normalized-verb prefix → drop the first raw word (normalize the
            # verb itself too: «أنشئ» → t has «انشي» because ئ→ي in shared norm)
            mv = re.match(rf"^{normalize_ar(v)}\s+(.+)$", t)
            if mv:
                raw_toks = core.split(None, 1)
                core = raw_toks[1].strip() if len(raw_toks) > 1 else ""
                break
            # Remove any price span BEFORE slotting: «أضف شاي بسعر 500» must
            # look up «شاي» in the cart, and «أنشئ مادة شاي بسعر خمسمئة» must
            # capture 500 (digits or written Syrian amount) as the price.
            amt_pre = match_amount(core)
            if amt_pre:
                if intent == "item_create":
                    slots["selling_price"] = amt_pre[0]
                core = (core[: amt_pre[1]] + core[amt_pre[2]:]).strip(" ،，")

        if intent == "item_create":
            qty_m = re.search(r"(?:بكمية|كمية|بكميه|كميه)\s*(\S+)", core)
            if qty_m:
                slots["quantity"] = float(_parse_qty_token(qty_m.group(1)) or 0)
                core = (core[: qty_m.start()] + core[qty_m.end():]).strip(" ،,")
            # drop the redundant leading «مادة/صنف/منتج»
            toks = core.split()
            if len(toks) >= 2 and normalize_ar(toks[0]) in ("ماده", "صنف", "منتج"):
                core = " ".join(toks[1:]).strip()
        if intent == "item_create":
            core = re.sub(r"\s*و\s*$", "", core).strip(" ،،")
        name, qty = strip_trailing_qty_words(core, 1.0)
        # leading digit form «3 سكر»
        lead = re.match(r"^(\d+(?:[.,]\d+)?)\s+(.+)$", name)
        if lead:
            qty = float(lead.group(1).replace(",", "."))
            name = lead.group(2).strip()
        else:
            # leading written form «اثنين حليب»
            toks = name.split(" ")
            if len(toks) >= 2 and toks[0] in WORD_NUMBERS:
                qty = float(WORD_NUMBERS[toks[0]])
                name = " ".join(toks[1:]).strip()
        if intent == "pos_add":
            # compound «أضف 3 سكر وحليب» → items list
            conj = _split_conjuncts(core)
            if len(conj) >= 2:
                items = []
                for part in conj[:6]:
                    pn, pq = strip_trailing_qty_words(part, 1.0)
                    lm = re.match(r"^(\d+(?:[.,]\d+)?)\s+(.+)$", pn)
                    if lm:
                        pq = float(lm.group(1).replace(",", "."))
                        pn = lm.group(2).strip()
                    elif not lm and pq == 1.0:
                        q2 = parse_qty(pn.split(" ")[0]) if " " in pn else None
                        if q2 and pn.split(" ")[0] in WORD_NUMBERS:
                            pn = " ".join(pn.split(" ")[1:])
                            pq = q2
                    if pn:
                        items.append({"name": pn, "qty": pq})
                if items:
                    slots["items"] = items
                    return slots
        if name:
            slots["name"] = name
            slots["qty"] = float(qty or 1)

    elif intent == "pos_set_qty":
        m = re.search(r"(\d+(?:[.,]\d+)?)", t)
        qty = parse_qty(t) or (float(m.group(1).replace(",", ".")) if m else None)
        core = t
        for v in _SETQ_VERBS:
            if core.startswith(v):
                core = core[len(v):].strip()
                break
        core = re.sub(r"(?:الكميه|كميه|كمية)", " ", core).strip()
        if m:
            core = (core[: core.find(m.group(1))] + core[core.find(m.group(1)) + len(m.group(1)):]).strip()
        name = core.strip(" ،,") or ""
        slots["name"] = "" if name in ("الاخير", "الاخير") else name
        if qty is not None:
            slots["qty"] = float(qty)

    elif intent == "stock_query":
        core = t
        for pat in ("كم باقي", "كم متبقي", "كمية", "كميه", "رصيد", "شو باقي بال", "شو باقي"):
            if core.startswith(pat):
                core = core[len(pat):].strip()
                break
        slots["name"] = core.strip(" ؟?") or ""

    elif intent.startswith("navigate_"):
        # remaining words beyond the verb are the target hint
        slots["target"] = _nav_target(intent) or ""

    elif intent == "item_create":
        pass  # handled above

    return slots


# ---------------------------------------------------------------------------
# Public entry point — the unified analyzer
# ---------------------------------------------------------------------------

# Confidence gates
CONF_ACT = 0.55       # >= act directly on NLU result
CONF_SOFT = 0.35      # 0.35..0.55 — let legacy regex confirm or ask
# Below → unknown

_SINGLETON = IntentClassifier()


def get_classifier() -> IntentClassifier:
    return _SINGLETON


def analyze(text: str) -> tuple[str, dict[str, Any], float]:
    """NLU-only pass: (intent, slots, confidence). Never raises."""
    try:
        ranked = _SINGLETON.classify(text)
        if not ranked:
            return "unknown", {}, 0.0
        intent, conf = ranked[0]
        slots = extract_slots(text, intent)
        return intent, slots, float(conf)
    except Exception:
        return "unknown", {}, 0.0


# Intents that change state (money, cart, data) — these need HIGH confidence
# to act on NLU alone. Read-only/conversational intents may act from the
# soft band (regex already had its chance and said unknown).
MUTATING_INTENTS = frozenset({
    "pos_add", "pos_pay", "pos_clear", "pos_remove_last", "pos_set_qty",
    "item_create", "crisis_on", "crisis_off",
})

# Intents handled conversationally elsewhere (voice_session converse/help/
# teach layers) — NLU must never swallow them before those layers run.
CONVERSATIONAL_INTENTS = frozenset({"teach", "memory_stats", "greet", "thanks", "help"})


def legacy_matches_nlu(legacy_action: str, legacy_target: str, nlu_intent: str) -> bool:
    """True when the legacy regex landed on the same intent the NLU chose."""
    if legacy_action == "navigate":
        return nlu_intent == f"navigate_{legacy_target or 'unknown'}"
    return legacy_action == nlu_intent


def analyze_full(text: str, legacy_parse=None, *, stock_handler=None) -> "object":
    """Unified pipeline: NLU first, legacy regex to confirm/override.

    Merge rules (recommendation #4 contract):
      • NLU confident (>= CONF_ACT) + legacy unknown/different → NLU wins,
        EXCEPT conversational intents which the session's earlier layers own.
      • Legacy exact match on the SAME intent → legacy wins (it carries the
        DB-backed result, e.g. stock queries with real numbers).
      • Soft band (CONF_SOFT..CONF_ACT) → regex decides; NLU may only fill
        gaps for NON-mutating intents (never risk money/cart from a guess).
      • Unknown → «لم أفهم» from legacy.
    """
    from nano_offline.services.quick_command_service import CommandResult

    nlu_intent, nlu_slots, nlu_conf = analyze(text)

    legacy = None
    if legacy_parse is not None:
        try:
            legacy = legacy_parse(text)
        except Exception:
            legacy = None

    legacy_usable = legacy is not None and legacy.ok and legacy.action != "unknown"

    if nlu_conf >= CONF_ACT and nlu_intent != "unknown" and nlu_intent not in CONVERSATIONAL_INTENTS:
        # DB-backed legacy result on the SAME intent is strictly better
        if legacy_usable and legacy_matches_nlu(legacy.action, legacy.target or "", nlu_intent):
            # …except item_create: the legacy regex normalizes the item name
            # (ة→ه) before storing it, which would corrupt the catalog
            # spelling. The NLU slot extractor works on the RAW text and
            # preserves the user's original spelling — prefer it here.
            if nlu_intent != "item_create":
                return legacy
        # Exact regex match on a DIFFERENT intent: trust regex (exact beats fuzzy)
        if legacy_usable and nlu_intent == "stock_query" and legacy.action == "query":
            return legacy
        if legacy_usable and not legacy_matches_nlu(legacy.action, legacy.target or "", nlu_intent):
            return legacy
        return materialize(nlu_intent, nlu_slots, nlu_conf)

    # Soft zone: regex decides, NLU fills gaps (read-only intents only)
    if legacy_usable:
        return legacy
    if nlu_conf >= CONF_SOFT and nlu_intent not in MUTATING_INTENTS | CONVERSATIONAL_INTENTS | {"unknown"}:
        if nlu_intent == "stock_query" and stock_handler is not None:
            name = (nlu_slots.get("name") or "").strip()
            if len(name) >= 2:
                return stock_handler(name)
        return materialize(nlu_intent, nlu_slots, nlu_conf)

    return legacy if legacy is not None else CommandResult(
        ok=False,
        action="unknown",
        message="لم أفهم الأمر. جرّب: بيع سريع، جرد، فتح العملاء، كم باقي السكر، تفعيل الطوارئ",
    )


_NAV_AR: dict[str, str] = {
    "pos": "نقطة البيع", "stocktake": "الجرد", "items": "المواد والمخزون",
    "customers": "العملاء", "suppliers": "الموردين", "invoices": "الفواتير",
    "sale": "فاتورة البيع", "purchase": "فاتورة الشراء", "finance": "المالية",
    "reports": "التقارير", "dashboard": "اللوحة الرئيسية", "admin": "الإدارة",
    "notifications": "الإشعارات", "security": "الأمان",
}


def materialize(intent: str, slots: dict[str, Any], conf: float) -> "object":
    """Build a CommandResult-shaped object from the NLU triple.

    Import is lazy to avoid a circular import with quick_command_service.
    """
    from nano_offline.services.quick_command_service import CommandResult
    cls = CommandResult
    """Build a CommandResult from the NLU triple."""
    if intent.startswith("navigate_"):
        target = _nav_target(intent) or "dashboard"
        return cls(ok=True, action="navigate", target=target, message=f"فتح: {target}", data={"conf": conf})
    if intent == "pos_add":
        if slots.get("items"):
            return cls(ok=True, action="pos_add_many", target="pos", message="إضافة عدة مواد", data={"items": slots["items"], "conf": conf})
        return cls(ok=True, action="pos_add", target="pos", message=f"إضافة إلى السلة: {slots.get('name', '')} × {float(slots.get('qty', 1)):g}", data={"name": slots.get("name", ""), "qty": float(slots.get("qty", 1)), "conf": conf})
    if intent == "pos_set_qty":
        return cls(ok=True, action="pos_set_qty", target="pos", message=f"تعيين كمية {slots.get('name') or 'الأخير'} إلى {float(slots.get('qty', 0)):g}", data={"name": slots.get("name", ""), "qty": float(slots.get("qty", 0)), "conf": conf})
    if intent == "stock_query":
        # Name-only marker; QuickCommandService.parse routes this intent to
        # its DB-backed _stock_query before anything consumes this action.
        return cls(ok=True, action="stock_query", target="items", message=slots.get("name", ""), data={"name": slots.get("name", ""), "conf": conf})
    if intent == "item_create":
        return cls(ok=True, action="item_create", target="items", message=f"إنشاء مادة {slots.get('name', '')}", data={"name": slots.get("name", ""), "selling_price": float(slots.get("selling_price", 0) or 0), "quantity": float(slots.get("quantity", 0) or 0), "conf": conf})
    mapping = {
        "pos_pay": "pos_pay", "pos_clear": "pos_clear", "pos_remove_last": "pos_remove_last",
        "pos_cart_summary": "pos_cart_summary", "today_sales": "today_sales",
        "cash_status": "cash_status", "crisis_on": "crisis_on", "crisis_off": "crisis_off",
        "tts_mute": "tts_mute", "tts_unmute": "tts_unmute", "voice_stop": "voice_stop",
    }
    act = mapping.get(intent)
    if act:
        return cls(ok=True, action=act, target="pos" if act.startswith("pos_") else None, message="", data={"conf": conf})
    return cls(ok=False, action="unknown", message="", data={"conf": conf})


def learn_from_phrase(intent: str, phrase: str) -> None:
    """Feed a successfully-executed utterance back into the classifier
    (audit item #1 closed loop — the model improves from real usage).
    Marks the model stale; the next ``parse()`` refits once (cheap).
    """
    try:
        _SINGLETON.add_learned(intent, phrase)
    except Exception:
        pass


def load_learned_memory(learning_service) -> int:
    """Preload the on-device classifier with every phrase the learning
    service recorded on this device (audit item #1 warm start)."""
    n = 0
    try:
        for row in learning_service.list_phrases(500):
            act = str(row.get("action") or "")
            target = str(row.get("target") or "")
            intent = f"navigate_{target}" if act == "navigate" and target else act
            if intent and intent != "message":
                _SINGLETON.add_learned(intent, str(row.get("phrase_raw") or row.get("phrase_norm") or ""))
                n += 1
        _SINGLETON.fit()
    except Exception:
        pass
    return n


__all__ = [
    "normalize_ar", "char_ngrams", "IntentClassifier", "analyze", "analyze_full",
    "materialize", "extract_slots", "parse_qty", "match_amount", "strip_trailing_qty_words",
    "get_classifier", "learn_from_phrase", "load_learned_memory", "legacy_matches_nlu",
    "WORD_NUMBERS", "CONF_ACT", "CONF_SOFT", "MUTATING_INTENTS",
    "CONVERSATIONAL_INTENTS",
]
