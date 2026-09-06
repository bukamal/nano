"""Public (secret-free) invoice verification -- phase 10 wave 2.

The QR printed on every invoice carries an HMAC payload (see
``core.invoice_signing``). Verifying that payload requires the app's own
database (the signing secret lives in ``settings``), so it answers the
question "was this slip tampered with since it left *this* device?".

The public path answers a related question for *anyone* -- including a
merchant or customer checking an invoice printed by a different Nano
install: "do the numbers printed on this paper match the invoice's own
recorded data?" Every printed slip shows its core facts as plain Arabic
text (number, date, total, party). We derive a short non-secret checksum
token from exactly those facts; anyone can recompute it from the printed
numbers using the formula below. Token mismatch => the paper was altered
after printing (or the number on it belongs to a different invoice).

This is tamper *evidence*, not issuer authentication (that would need a
public-key scheme plus verifiable key distribution, out of scope for a
fully-offline device). It only ever runs locally: no network, no
third-party library, no schema change (SCHEMA_VERSION stays 13).
"""

from __future__ import annotations

import hashlib

__all__ = ["public_fingerprint", "verify_manual"]

# Unambiguous base32 subset: no 0/O, 1/I/L, or lowercase that confuse
# hand-copying from a printed slip.
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def public_fingerprint(
    *,
    invoice_id: int,
    invoice_date: str,
    total: float,
    party_key: str = "-",
    lines: int = 0,
) -> str:
    """6-character secret-free checksum over the invoice's printed facts.

    Deterministic: any two parties computing it from the same printed
    numbers arrive at the same token.
    """
    canonical = f"{int(invoice_id)}|{invoice_date}|{float(total):.2f}|{party_key}|{int(lines)}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    value = int(digest[:8], 16)  # 32 bits -> 6 base32 chars (~30 bits)
    out: list[str] = []
    for _ in range(6):
        out.append(_ALPHABET[value % len(_ALPHABET)])
        value //= len(_ALPHABET)
    return "".join(out)


def verify_manual(db, invoice_number: str, token: str) -> tuple[bool, str, dict | None]:
    """Check a handwritten/printed token against the stored invoice.

    ``invoice_number`` accepts a plain id ("12") or a display number that
    embeds the id ("INV-00012" or "#12"). Returns ``(is_valid, reason,
    invoice_row_or_None)`` with an Arabic ``reason`` ready for the
    verification dialog.
    """
    token = (token or "").strip().upper()
    raw = (invoice_number or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return False, "أدخل رقم الفاتورة المطبوع", None
    invoice_id = int(digits)
    with db.connect() as conn:
        row = conn.execute(
            """SELECT i.id, i.invoice_date, i.total, i.customer_id, i.supplier_id,
                      c.name AS customer_name, s.name AS supplier_name,
                      (SELECT COUNT(*) FROM invoice_lines il WHERE il.invoice_id = i.id) AS lines
               FROM invoices i
               LEFT JOIN customers c ON c.id = i.customer_id
               LEFT JOIN suppliers s ON s.id = i.supplier_id
               WHERE i.id = ?""",
            (invoice_id,),
        ).fetchone()
    if row is None:
        return False, "لا توجد فاتورة بهذا الرقم في السجل", None
    party_key = str(
        row["customer_id"] or row["supplier_id"] or row["customer_name"] or row["supplier_name"] or "-"
    )
    expected = public_fingerprint(
        invoice_id=int(row["id"]),
        invoice_date=str(row["invoice_date"]),
        total=float(row["total"]),
        party_key=party_key,
        lines=int(row["lines"] or 0),
    )
    invoice = dict(row)
    if token and token == expected:
        return True, "الفاتورة أصلية والبيانات مطابقة للسجل", invoice
    return False, "الرمز لا يطابق بيانات الفاتورة المسجلة — قد يكون الرقم أو المبلغ معدّلًا", invoice
