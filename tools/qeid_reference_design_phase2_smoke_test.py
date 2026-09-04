from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from nano_offline.app_context import AppContext
from nano_offline.services.invoice_service import InvoiceLineInput

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
finance = (ROOT / "src/nano_offline/views/finance_view.py").read_text(encoding="utf-8")
items_repo = (ROOT / "src/nano_offline/repositories/item_repository.py").read_text(encoding="utf-8")
party_repo = (ROOT / "src/nano_offline/repositories/party_repository.py").read_text(encoding="utf-8")
items_view = (ROOT / "src/nano_offline/views/items_view.py").read_text(encoding="utf-8")
parties_view = (ROOT / "src/nano_offline/views/parties_view.py").read_text(encoding="utf-8")
dashboard_view = (ROOT / "src/nano_offline/views/dashboard_view.py").read_text(encoding="utf-8")

# These items/parties/dashboard detail strings moved out of main.py into their
# respective Center classes as part of the 2026-08 refactor that split
# main.py's view closures out of the shell file; same functional guarantee,
# new locations.
for token in ['"مخزون منخفض"', '"آخر حركات المخزون"', '"كمية مباعة"']:
    assert token in items_view, token
assert '"إجمالي الفواتير"' in parties_view
assert '"آخر الفواتير"' in dashboard_view

for token in [
    '"سند مصروف"',
    '"إجمالي القبض"',
    '"إجمالي الدفع"',
    '"طباعة 80mm"',
    '"تكرار"',
    'show_voucher_detail',
]:
    assert token in finance, token

assert "def activity_summary" in items_repo
assert "def movements" in items_repo
assert "def activity_summary" in party_repo

with TemporaryDirectory() as td:
    ctx = AppContext.create(Path(td) / "nano.db")
    unit_id = ctx.definitions.create_unit("قطعة", "ق")
    item_id = ctx.items.create(name="مادة اختبار", purchase_price=5, selling_price=10, quantity=0, base_unit_id=unit_id)
    supplier_id = ctx.suppliers.create("مورد اختبار")
    customer_id = ctx.customers.create("عميل اختبار")

    ctx.invoices.create_invoice(
        invoice_type="purchase",
        supplier_id=supplier_id,
        paid_amount=50,
        lines=[InvoiceLineInput(description="شراء مادة اختبار", item_id=item_id, unit_id=unit_id, quantity=10, unit_price=5)],
    )
    ctx.invoices.create_invoice(
        invoice_type="sale",
        customer_id=customer_id,
        paid_amount=0,
        lines=[InvoiceLineInput(description="بيع مادة اختبار", item_id=item_id, unit_id=unit_id, quantity=3, unit_price=10)],
    )

    stats = ctx.items.activity_summary(item_id)
    assert abs(float(stats["quantity"]) - 7) < 1e-9, stats
    assert abs(float(stats["sold_qty"]) - 3) < 1e-9, stats
    assert abs(float(stats["purchased_qty"]) - 10) < 1e-9, stats
    assert int(stats["sale_count"]) == 1 and int(stats["purchase_count"]) == 1, stats
    assert len(ctx.items.movements(item_id)) >= 2

    customer = ctx.customers.activity_summary(customer_id)
    assert int(customer["invoice_count"]) == 1, customer
    assert abs(float(customer["outstanding_total"]) - 30) < 1e-9, customer
    assert len(customer["recent_invoices"]) == 1

print("qeid_reference_design_phase2_smoke_test passed")
