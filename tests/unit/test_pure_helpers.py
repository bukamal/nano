"""Unit tests for pure-stdlib helpers: audit hashes, barcode checksum, voice NLU."""
from __future__ import annotations

from nano_offline.core.audit_chain import compute_row_hash
from nano_offline.core.barcode128 import code128b_bars
from nano_offline.core import voice_nlu


def test_row_hash_deterministic_and_sensitive():
    base = dict(
        action="create", entity_type="invoice", entity_id=1, details="x",
        user_id=2, username="admin", created_at="2026-01-01T00:00:00", prev_hash=None,
    )
    assert compute_row_hash(**base) == compute_row_hash(**base)
    tampered = {**base, "details": "y"}
    assert compute_row_hash(**tampered) != compute_row_hash(**base)
    linked = {**base, "prev_hash": "abc"}
    assert compute_row_hash(**linked) != compute_row_hash(**base)
    assert len(compute_row_hash(**base)) == 64


def test_code128_bars_structure():
    bars = code128b_bars("ABC")
    assert bars, "bars generated"
    widths = sum(w for w, _ in bars)
    assert widths > 40  # start + 3 chars + checksum + stop
    assert all(w > 0 for w, _ in bars)
    # alternating bar/space pattern is consistent when serialized back
    seq = "".join("1" * w if bar else "0" * w for w, bar in bars)
    assert seq.startswith("1") and seq.endswith("1")


def test_normalize_ar_folds_dialect():
    assert voice_nlu.normalize_ar("سُكَّر") == "سكر"
    assert voice_nlu.normalize_ar("ماء") == "ما"
    assert voice_nlu.normalize_ar("١٢٣") == "123"
    assert voice_nlu.normalize_ar(None) == ""


def test_match_amount_digits_and_words():
    assert voice_nlu.match_amount("بسعر 800")[0] == 800
    assert voice_nlu.match_amount("بسعر ١٢٥")[0] == 125
    assert voice_nlu.match_amount("سعر خمسمئة")[0] == 500
    assert voice_nlu.match_amount("سعر ثلاث ميه")[0] == 300
    assert voice_nlu.match_amount("لا رقم هنا") is None


def test_parse_qty():
    assert voice_nlu.parse_qty("5") == 5.0
    assert voice_nlu.parse_qty("٢") == 2.0
    assert voice_nlu.parse_qty("اثنين") == 2.0
    assert voice_nlu.parse_qty("لاشيء") is None


def test_strip_trailing_qty_words():
    assert voice_nlu.strip_trailing_qty_words("سكر اثنين", 1) == ("سكر", 2.0)
    assert voice_nlu.strip_trailing_qty_words("حليب", 3) == ("حليب", 3.0)


def test_char_ngrams_basics():
    grams = voice_nlu.char_ngrams("سكر")
    assert grams and all(len(g) in (2, 3) or g.strip() == "" for g in grams)
    assert voice_nlu.char_ngrams("") == {}


def test_analyze_smoke():
    intent, slots, conf = voice_nlu.analyze("ادفع")
    assert intent == "pos_pay"
    assert conf >= 0.55
    # never raises, unknown input degrades gracefully
    intent, slots, conf = voice_nlu.analyze("///###")
    assert isinstance(conf, float)
