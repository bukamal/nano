from __future__ import annotations

"""Offline, self-verifying item cards.

A QR code that carries one item's full definition (name, barcode, prices,
unit, category) so a *second* device can add the exact same item by
scanning it, instead of retyping it. Same offline, no-network, standard-
library-only design as ``invoice_signing.py`` -- and the same honest
tradeoff that module documents: the HMAC secret lives in *this* database's
``settings`` table, so a card only verifies as "trusted" against a device
that shares that secret. In practice that means another device restored
from the same shop's backup lineage -- the secret "travels with the
accounting data" exactly like the invoice-signing secret does.

A card scanned on an independent install (a different shop, a supplier's
own device) will not verify against the scanning device's own secret, and
that's expected, not a failure or an attack: ``verify_item_card`` reports
it as ``"external"`` rather than ``"invalid"``, and the UI shows it plainly
as unverified data to review, never as a trusted import. There is no
separate weaker "checksum-only" layer for that case -- the same signature
check already tells the two situations apart correctly on its own.
"""

import hashlib
import hmac
import secrets

from nano_offline.core.database import Database

_SETTINGS_KEY = "item_card_signing_secret"
_TOKEN_PREFIX = "NANO-ITM"

# Headroom under qr_gen's ~274-byte ceiling (version 10, lowest error
# correction) -- see build_item_card()'s field-dropping fallback below,
# same "shorten the payload" approach qr_gen.py itself documents.
_MAX_PAYLOAD_BYTES = 220


def _get_or_create_secret(db: Database) -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_SETTINGS_KEY,)).fetchone()
        if row and row[0]:
            return row[0]
        secret = secrets.token_hex(32)
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (_SETTINGS_KEY, secret))
        conn.commit()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_SETTINGS_KEY,)).fetchone()
        return row[0]


def _esc(value: str | None) -> str:
    # '|' is the field separator and the payload is single-line -- strip
    # both out of free-text fields so a stray '|' or newline in an item
    # name can never shift the columns for whoever parses it.
    return (value or "").replace("|", "-").replace("\n", " ").strip()


def _fields(name, barcode, purchase, selling, unit, category) -> list[str]:
    return [
        _esc(name),
        _esc(barcode),
        f"{purchase:.2f}" if purchase is not None else "",
        f"{selling:.2f}" if selling is not None else "",
        _esc(unit),
        _esc(category),
    ]


def _signature(secret: str, canonical: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:16]  # 64 bits -- plenty to catch tampering/corruption on a scanned code


def build_item_card(
    db: Database,
    *,
    name: str,
    barcode: str | None,
    purchase_price: float | None,
    selling_price: float | None,
    unit: str | None,
    category: str | None,
) -> str:
    """Return the compact, signed QR payload for one item.

    Drops optional fields -- category, then unit, then purchase price, in
    that order -- if the result would exceed the QR's safe byte budget,
    before ever falling back to truncating the name itself.
    """
    secret = _get_or_create_secret(db)
    candidates = [
        (unit, category, purchase_price),
        (unit, None, purchase_price),
        (None, None, purchase_price),
        (None, None, None),
    ]
    for cand_unit, cand_category, cand_purchase in candidates:
        fields = _fields(name, barcode, cand_purchase, selling_price, cand_unit, cand_category)
        canonical = "|".join(fields)
        payload = f"{_TOKEN_PREFIX}|{canonical}|{_signature(secret, canonical)}"
        if len(payload.encode("utf-8")) <= _MAX_PAYLOAD_BYTES:
            return payload
    # Even the bare-minimum fields didn't fit (an unusually long name) --
    # trim the name itself as a last resort rather than refusing to issue
    # a card at all.
    fields = _fields(_esc(name)[:40], barcode, None, selling_price, None, None)
    canonical = "|".join(fields)
    return f"{_TOKEN_PREFIX}|{canonical}|{_signature(secret, canonical)}"


def parse_item_card(payload: str) -> dict | None:
    """Split a scanned payload into its raw fields, without checking the
    signature. Returns ``None`` if it isn't a well-formed item card."""
    parts = (payload or "").strip().split("|")
    if len(parts) != 8 or parts[0] != _TOKEN_PREFIX:
        return None
    _prefix, name, barcode, purchase, selling, unit, category, sig = parts
    try:
        return {
            "name": name,
            "barcode": barcode or None,
            "purchase_price": float(purchase) if purchase else None,
            "selling_price": float(selling) if selling else None,
            "unit": unit or None,
            "category": category or None,
            "_sig": sig,
            "_canonical": "|".join(parts[1:-1]),
        }
    except ValueError:
        return None


def verify_item_card(db: Database, payload: str) -> tuple[str, dict | None, str]:
    """Recompute the signature for a scanned card against THIS device's own
    secret. Returns ``(status, fields, reason)``:

    - ``"trusted"``  -- signature matches this device's secret (same shop,
      another of its own devices)
    - ``"external"`` -- well-formed, but signed with a different secret (a
      different shop or an independent device) -- shown as unverified data
      to review, not as an error
    - ``"invalid"``  -- not a recognizable item card at all
    """
    parsed = parse_item_card(payload)
    if parsed is None:
        return "invalid", None, "هذا الرمز ليس بطاقة مادة صالحة"
    secret = _get_or_create_secret(db)
    expected = _signature(secret, parsed["_canonical"])
    if hmac.compare_digest(expected, parsed["_sig"]):
        return "trusted", parsed, "موقّعة ومطابقة — من هذا الجهاز أو من نفس منشأتك"
    return "external", parsed, "من مصدر خارجي — راجع البيانات قبل الحفظ"


__all__ = ["build_item_card", "parse_item_card", "verify_item_card"]
