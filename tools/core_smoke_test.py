from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qeid_offline.app_context import AppContext
from qeid_offline.services.invoice_service import InvoiceLineInput


def main():
    with tempfile.TemporaryDirectory(prefix="qeid-offline-") as td:
        ctx = AppContext.create(Path(td) / "qeid.db")
        unit_id = ctx.definitions.create_unit("قطعة", "قط")
        customer_id = ctx.customers.create("عميل تجريبي", "0900000000")
        supplier_id = ctx.suppliers.create("مورد تجريبي")
        item_id = ctx.items.create(name="مادة A", item_type="مخزون", purchase_price=10, selling_price=15, quantity=10, base_unit_id=unit_id)

        purchase_id = ctx.invoices.create_invoice(
            invoice_type="purchase", supplier_id=supplier_id, paid_amount=20,
            lines=[InvoiceLineInput(description="مادة A", item_id=item_id, quantity=5, unit_price=12, unit_id=unit_id)],
        )
        item = ctx.items.get(item_id)
        assert round(item["quantity"], 6) == 15
        assert round(item["average_cost"], 6) == round((10*10 + 5*12)/15, 6)
        supplier = ctx.suppliers.get(supplier_id)
        assert round(supplier["balance"], 6) == 40

        sale_id = ctx.invoices.create_invoice(
            invoice_type="sale", customer_id=customer_id, paid_amount=10,
            lines=[InvoiceLineInput(description="مادة A", item_id=item_id, quantity=3, unit_price=20, unit_id=unit_id)],
        )
        item = ctx.items.get(item_id)
        assert round(item["quantity"], 6) == 12
        customer = ctx.customers.get(customer_id)
        assert round(customer["balance"], 6) == 50

        s = ctx.dashboard.summary()
        assert round(s["sales"], 6) == 60
        assert round(s["purchases"], 6) == 60
        assert round(s["cash"], 6) == -10
        assert s["cogs"] > 0
        assert ctx.db.integrity_check() == "ok"
        print("core_smoke_test passed")
        print(f"purchase={purchase_id} sale={sale_id} customer_balance={customer['balance']} supplier_balance={supplier['balance']} stock={item['quantity']}")


if __name__ == "__main__":
    main()
