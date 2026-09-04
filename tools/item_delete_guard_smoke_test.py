from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.app_context import AppContext
from nano_offline.services.invoice_service import InvoiceLineInput

with tempfile.TemporaryDirectory(prefix="qeid-item-delete-") as td:
    ctx = AppContext.create(Path(td) / "nano.db")
    unit_id = ctx.definitions.create_unit("قطعة", "ق")

    # A service item never invoiced is deletable — services never create an
    # inventory_movements row regardless of opening quantity.
    svc_id = ctx.items.create(name="خدمة تركيب", item_type="خدمة", purchase_price=0, selling_price=20, quantity=0, base_unit_id=unit_id)
    ctx.items.delete(svc_id)
    assert ctx.items.get(svc_id) is None

    # A stock item created with a zero opening quantity, never used, is
    # deletable — it never generated an 'adjustment' movement at creation.
    stock_id = ctx.items.create(name="مادة تجريبية", item_type="مخزون", purchase_price=5, selling_price=10, quantity=0, base_unit_id=unit_id)
    ctx.items.delete(stock_id)
    assert ctx.items.get(stock_id) is None

    # A stock item created WITH a non-zero opening quantity gets an
    # inventory_movements row at creation time — must be blocked even
    # before any invoice ever touches it.
    stock_id2 = ctx.items.create(name="مادة برصيد", item_type="مخزون", purchase_price=5, selling_price=10, quantity=10, base_unit_id=unit_id)
    try:
        ctx.items.delete(stock_id2)
        raise AssertionError("delete should have raised for an item with an opening-quantity movement")
    except ValueError as exc:
        assert "مرتبط" in str(exc)

    # An item referenced by an invoice line must be blocked.
    stock_id3 = ctx.items.create(name="مادة للبيع", item_type="مخزون", purchase_price=5, selling_price=10, quantity=0, base_unit_id=unit_id)
    supplier_id = ctx.suppliers.create("مورد")
    ctx.invoices.create_invoice(
        invoice_type="purchase", supplier_id=supplier_id, paid_amount=0,
        lines=[InvoiceLineInput(description="شراء", item_id=stock_id3, unit_id=unit_id, quantity=5, unit_price=5)],
    )
    try:
        ctx.items.delete(stock_id3)
        raise AssertionError("delete should have raised for an invoiced item")
    except ValueError as exc:
        assert "مرتبط" in str(exc)

print("item_delete_guard_smoke_test passed")
