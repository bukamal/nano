from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.services.invoice_service import InvoiceLineInput


with tempfile.TemporaryDirectory(prefix="qeid-phase7-docs-") as td:
    ctx = AppContext.create(Path(td) / "nano.db")
    customer_id = ctx.customers.create("شركة الاختبار", "0999999999", "دمشق")
    service_id = ctx.items.create(name="خدمة تدقيق", item_type="خدمة", purchase_price=25, selling_price=75)
    invoice_id = ctx.invoices.create_invoice(
        invoice_type="sale",
        customer_id=customer_id,
        invoice_date="2026-08-10",
        reference="INV-77",
        notes="ملاحظة عربية",
        paid_amount=25,
        lines=[InvoiceLineInput(item_id=service_id, description="خدمة تدقيق سنوية", quantity=2, unit_price=75)],
    )
    invoice_html = ctx.documents.invoice_html(invoice_id)
    # Amounts are stored as raw USD (150/25/125) but *displayed* converted to
    # the default SYP rate (13500): 150*13500=2,025,000 / 25*13500=337,500 /
    # 125*13500=1,687,500, formatted with thousands separators and 0 decimals.
    for needle in [
        'dir="rtl"',
        "فاتورة بيع",
        "شركة الاختبار",
        "خدمة تدقيق سنوية",
        "2,025,000",
        "337,500",
        "1,687,500",
        "INV-77",
        "ملاحظة عربية",
    ]:
        assert needle in invoice_html, needle

    statement_html = ctx.documents.statement_html("customer", customer_id)
    for needle in ['dir="rtl"', "كشف حساب عميل", "شركة الاختبار", "فاتورة بيع", "1,687,500"]:
        assert needle in statement_html, needle

print("phase7_document_export_smoke_test passed")
