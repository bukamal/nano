from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.services.invoice_service import InvoiceLineInput

ROOT = Path(__file__).resolve().parents[1]

# Core accounting invariant: anonymous sale/purchase is settled in full as cash.
with tempfile.TemporaryDirectory(prefix="nano-cash-default-") as td:
    ctx = AppContext.create(Path(td) / "nano.db")

    sale_id = ctx.invoices.create_invoice(
        invoice_type="sale",
        lines=[InvoiceLineInput(description="بيع نقدي", quantity=2, unit_price=25)],
        paid_amount=0,
    )
    sale = ctx.invoices.get_invoice(sale_id)
    assert sale is not None
    assert sale["customer_id"] is None
    assert float(sale["total"]) == 50.0
    assert float(sale["initial_paid_amount"]) == 50.0
    assert float(sale["paid_amount"]) == 50.0
    assert abs(float(sale["remaining_amount"])) < 1e-9

    purchase_id = ctx.invoices.create_invoice(
        invoice_type="purchase",
        lines=[InvoiceLineInput(description="شراء نقدي", quantity=3, unit_price=10)],
        paid_amount=0,
    )
    purchase = ctx.invoices.get_invoice(purchase_id)
    assert purchase is not None
    assert purchase["supplier_id"] is None
    assert float(purchase["total"]) == 30.0
    assert float(purchase["initial_paid_amount"]) == 30.0
    assert float(purchase["paid_amount"]) == 30.0
    assert abs(float(purchase["remaining_amount"])) < 1e-9

    customer = ctx.customers.create("عميل آجل")
    credit_id = ctx.invoices.create_invoice(
        invoice_type="sale",
        customer_id=customer,
        lines=[InvoiceLineInput(description="بيع آجل", quantity=1, unit_price=40)],
        paid_amount=0,
    )
    credit = ctx.invoices.get_invoice(credit_id)
    assert credit is not None
    assert float(credit["paid_amount"]) == 0.0
    assert float(credit["remaining_amount"]) == 40.0

native_py = (ROOT / "extensions/flet_native_files/src/flet_native_files/native_files.py").read_text(encoding="utf-8")
native_dart = (ROOT / "extensions/flet_native_files/src/flutter/flet_native_files/lib/src/native_files.dart").read_text(encoding="utf-8")
admin = (ROOT / "src/nano_offline/views/admin_view.py").read_text(encoding="utf-8")
invoice_ui = (ROOT / "src/nano_offline/views/invoice_view.py").read_text(encoding="utf-8")

# PDF must be materialized, then shared through the same share_file/shareXFiles path as backups.
for needle in ["async def create_pdf", 'invoke_method_async("create_pdf"', "return await self.share_file", 'mime_type="application/pdf"']:
    assert needle in native_py, needle
for needle in ["Future<File> createPdfFile", "case 'create_pdf'", "Share.shareXFiles", "mimeType: 'application/pdf'"]:
    assert needle in native_dart, needle
assert "Printing.sharePdf" not in native_dart

# Android backup import opens FileType.any (extensions=None) then validates and persists locally.
for needle in ["extensions=None", "validate_backup, source", "shutil.copy2", "validate_backup, target", "إنشاء ومشاركة نسخة"]:
    assert needle in admin, needle
assert "FileType.any" in native_dart

# UI mirrors the core cash invariant and makes the auto-paid state explicit.
for needle in ["مدفوع نقدًا (تلقائي)", "cash_without_party", "بدون عميل/مورد = فاتورة نقدية"]:
    assert needle in invoice_ui, needle

print("cash_backup_pdf_android_smoke_test passed")
