from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.core import public_verify
from nano_offline.core.invoice_signing import sign_invoice, verify_payload
from nano_offline.core.qr_gen import qr_svg
from nano_offline.services.invoice_service import InvoiceLineInput

with tempfile.TemporaryDirectory(prefix="nano_phase10_pubqr_") as td:
    root = Path(td)
    ctx = AppContext.create(root / "data" / "nano.db")
    ctx.auth.create_initial_admin("admin", "المدير", "StrongPass1")
    ctx.auth.login("admin", "StrongPass1")

    customer = ctx.customers.create("عميل عام")
    invoice_id = ctx.invoices.create_invoice(
        invoice_type="sale",
        customer_id=customer,
        lines=[InvoiceLineInput(description="سلعة", quantity=2, unit_price=150)],
        paid_amount=0,
    )
    inv = ctx.invoices.get_invoice(invoice_id)
    total = float(inv["total"])
    party_key = str(customer)
    lines = len(inv["lines"])

    # --- 1. signed QR payload over the same facts still verifies ---
    payload = sign_invoice(
        ctx.db, invoice_id=invoice_id, invoice_date=str(inv["invoice_date"]),
        total=total, party_key=party_key,
    )
    assert payload.startswith("NANO-INV|"), payload
    ok, reason = verify_payload(ctx.db, payload)
    assert ok, reason

    # --- 2. public token is 6 unambiguous chars ---
    token = public_verify.public_fingerprint(
        invoice_id=invoice_id, invoice_date=str(inv["invoice_date"]),
        total=total, party_key=party_key, lines=lines,
    )
    assert len(token) == 6 and token.isalnum(), token

    # --- 3. QR fits the offline encoder (<= 274 bytes) and renders SVG ---
    assert len(payload.encode("utf-8")) <= 274, len(payload)
    svg = qr_svg(payload, size=64, level="M", quiet_zone=1)
    assert svg.startswith("<svg") and "</svg>" in svg

    # --- 4. fingerprint is deterministic and fact-sensitive ---
    again = public_verify.public_fingerprint(
        invoice_id=invoice_id, invoice_date=str(inv["invoice_date"]),
        total=total, party_key=party_key, lines=lines,
    )
    assert again == token
    tampered = public_verify.public_fingerprint(
        invoice_id=invoice_id, invoice_date=str(inv["invoice_date"]),
        total=total + 10, party_key=party_key, lines=lines,
    )
    assert tampered != token

    # --- 5. manual path: printed number + token vs stored row ---
    ok, reason, row = public_verify.verify_manual(ctx.db, str(invoice_id), token)
    assert ok and row is not None, reason
    ok2, reason2, _ = public_verify.verify_manual(ctx.db, f"INV-{invoice_id:05d}", token)
    assert ok2, reason2  # display-number style input still resolves
    bad = public_verify.verify_manual(ctx.db, str(invoice_id), "ZZZZZZ")
    assert not bad[0] and "لا يطابق" in bad[1], bad
    missing = public_verify.verify_manual(ctx.db, "999999", token)
    assert not missing[0] and "لا توجد فاتورة" in missing[1], missing

print("phase10_public_qr_verify_smoke_test passed")
