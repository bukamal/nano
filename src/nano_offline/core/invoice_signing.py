from __future__ import annotations

"""Offline, self-verifying invoice signatures.

Every invoice already carries a Code128 barcode of its numeric id (see
``document_service``). This module adds a second, tamper-evident layer on
top: a short HMAC-SHA256 signature over the invoice's core facts (id, date,
total, party), computed with a secret that lives only in this database's
``settings`` table (never in a backup-excluded/device-only place -- it
travels *with* the accounting data, so a restored backup keeps every old
invoice verifiable).

No network, no external crypto library beyond the standard library's
``hmac``/``hashlib`` -- consistent with the rest of the app's fully offline
design. Anyone (with or without this app) who has the printed invoice and
its QR code can have the *current* database recompute the signature and
confirm the invoice numbers on paper haven't been altered after printing.
"""

import hmac
import hashlib
import secrets

from nano_offline.core.database import Database

_SETTINGS_KEY = "invoice_signing_secret"
_TOKEN_PREFIX = "NANO-INV"


def _get_or_create_secret(db: Database) -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_SETTINGS_KEY,)).fetchone()
        if row and row[0]:
            return row[0]
        secret = secrets.token_hex(32)
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (_SETTINGS_KEY, secret),
        )
        conn.commit()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_SETTINGS_KEY,)).fetchone()
        return row[0]


def _canonical(invoice_id: int, invoice_date: str, total: float, party_key: str) -> str:
    return f"{int(invoice_id)}|{invoice_date}|{float(total):.2f}|{party_key}"


def _signature(secret: str, canonical: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:16]  # 64 bits -- plenty to catch tampering on a printed slip


def sign_invoice(db: Database, *, invoice_id: int, invoice_date: str, total: float, party_key: str = "-") -> str:
    """Return the compact QR payload string for this invoice."""
    secret = _get_or_create_secret(db)
    canonical = _canonical(invoice_id, invoice_date, total, party_key)
    sig = _signature(secret, canonical)
    return f"{_TOKEN_PREFIX}|{invoice_id}|{invoice_date}|{float(total):.2f}|{party_key}|{sig}"


def verify_payload(db: Database, payload: str) -> tuple[bool, str]:
    """Recompute the signature for a scanned payload and compare.

    Returns ``(is_valid, reason)`` where ``reason`` is a short human-readable
    Arabic explanation suitable for display in the verification screen.
    """
    parts = (payload or "").split("|")
    if len(parts) != 6 or parts[0] != _TOKEN_PREFIX:
        return False, "الرمز غير صالح أو غير صادر من هذا التطبيق"
    _prefix, inv_id, inv_date, total, party_key, sig = parts
    try:
        canonical = _canonical(int(inv_id), inv_date, float(total), party_key)
    except ValueError:
        return False, "تعذر قراءة بيانات الفاتورة من الرمز"
    secret = _get_or_create_secret(db)
    expected = _signature(secret, canonical)
    if hmac.compare_digest(expected, sig):
        return True, "الفاتورة مطابقة ولم يتم التعديل عليها"
    return False, "تحذير: بيانات الفاتورة لا تطابق التوقيع -- قد تكون معدّلة"


__all__ = ["sign_invoice", "verify_payload"]
