from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.app_context import AppContext
from nano_offline.services.invoice_service import InvoiceLineInput


def close(a: float, b: float, eps: float = 1e-6) -> None:
    assert abs(float(a) - float(b)) <= eps, (a, b)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qeid-phase2-") as td:
        ctx = AppContext.create(Path(td) / "nano.db")
        piece = ctx.definitions.create_unit("قطعة", "قط")
        box = ctx.definitions.create_unit("كرتون", "ك")
        customer = ctx.customers.create("عميل المرحلة 2")
        supplier = ctx.suppliers.create("مورد المرحلة 2")
        stock_item = ctx.items.create(
            name="مادة متعددة الوحدات",
            item_type="مخزون",
            purchase_price=10,
            selling_price=20,
            quantity=10,
            base_unit_id=piece,
            item_units=[{"unit_id": box, "conversion_factor": 5}],
        )
        service_item = ctx.items.create(
            name="خدمة تركيب",
            item_type="خدمة",
            purchase_price=0,
            selling_price=30,
        )

        units = ctx.items.units(stock_item)
        assert [(u["name"], float(u["conversion_factor"])) for u in units] == [("قطعة", 1.0), ("كرتون", 5.0)]

        purchase_id = ctx.invoices.create_invoice(
            invoice_type="purchase",
            supplier_id=supplier,
            invoice_date="2026-01-01",
            paid_amount=20,
            lines=[
                InvoiceLineInput(
                    description="شراء كرتون",
                    item_id=stock_item,
                    unit_id=box,
                    conversion_factor=999,  # must be ignored; DB unit contract is authoritative
                    quantity=2,
                    unit_price=60,
                )
            ],
        )
        item = ctx.items.get(stock_item)
        close(item["quantity"], 20)
        close(item["average_cost"], 11)
        close(ctx.suppliers.get(supplier)["balance"], 100)

        sale_id = ctx.invoices.create_invoice(
            invoice_type="sale",
            customer_id=customer,
            invoice_date="2026-01-02",
            paid_amount=30,
            reference="S-001",
            lines=[
                InvoiceLineInput(
                    description="بيع كرتون",
                    item_id=stock_item,
                    unit_id=box,
                    quantity=1,
                    unit_price=100,
                ),
                InvoiceLineInput(
                    description="خدمة تركيب",
                    item_id=service_item,
                    quantity=1,
                    unit_price=30,
                ),
            ],
        )
        sale = ctx.invoices.get_invoice(sale_id)
        assert sale and len(sale["lines"]) == 2
        close(sale["total"], 130)
        close(sale["remaining_amount"], 100)
        assert sale["payment_status"] == "partial"
        close(ctx.customers.get(customer)["balance"], 100)
        item = ctx.items.get(stock_item)
        close(item["quantity"], 15)
        stock_line = next(line for line in sale["lines"] if line["item_id"] == stock_item)
        close(stock_line["quantity_in_base"], 5)
        close(stock_line["unit_cost"], 11)
        close(stock_line["cost_amount"], 55)

        # Edit a historical purchase. Later sale COGS and current average cost must be recalculated.
        ctx.invoices.update_invoice(
            purchase_id,
            invoice_type="purchase",
            supplier_id=supplier,
            invoice_date="2026-01-01",
            paid_amount=20,
            lines=[
                InvoiceLineInput(
                    description="شراء كرتون معدل",
                    item_id=stock_item,
                    unit_id=box,
                    quantity=1,
                    unit_price=50,
                )
            ],
        )
        item = ctx.items.get(stock_item)
        close(item["quantity"], 10)  # opening 10 + purchase 5 - sale 5
        close(item["average_cost"], 10)
        close(ctx.suppliers.get(supplier)["balance"], 30)
        sale = ctx.invoices.get_invoice(sale_id)
        stock_line = next(line for line in sale["lines"] if line["item_id"] == stock_item)
        close(stock_line["unit_cost"], 10)
        close(stock_line["cost_amount"], 50)

        # Invalid edit must roll back completely.
        try:
            ctx.invoices.update_invoice(
                sale_id,
                invoice_type="sale",
                customer_id=customer,
                invoice_date="2026-01-02",
                paid_amount=30,
                lines=[
                    InvoiceLineInput(
                        description="كمية غير متاحة",
                        item_id=stock_item,
                        unit_id=box,
                        quantity=4,
                        unit_price=100,
                    )
                ],
            )
        except ValueError as exc:
            assert "المخزون غير كافٍ" in str(exc)
        else:
            raise AssertionError("insufficient-stock edit should fail")
        sale = ctx.invoices.get_invoice(sale_id)
        close(sale["total"], 130)
        assert len(sale["lines"]) == 2
        close(ctx.customers.get(customer)["balance"], 100)
        close(ctx.items.get(stock_item)["quantity"], 10)

        # Removing the historical purchase is valid because opening stock still covers the sale.
        ctx.invoices.delete_invoice(purchase_id)
        close(ctx.suppliers.get(supplier)["balance"], 0)
        item = ctx.items.get(stock_item)
        close(item["quantity"], 5)
        close(item["average_cost"], 10)
        sale = ctx.invoices.get_invoice(sale_id)
        stock_line = next(line for line in sale["lines"] if line["item_id"] == stock_item)
        close(stock_line["cost_amount"], 50)

        # Delete sale: stock, customer balance, ledger and dashboard return to opening-only state.
        ctx.invoices.delete_invoice(sale_id)
        close(ctx.customers.get(customer)["balance"], 0)
        close(ctx.items.get(stock_item)["quantity"], 10)
        summary = ctx.dashboard.summary()
        close(summary["sales"], 0)
        close(summary["purchases"], 0)
        close(summary["cash"], 0)
        assert ctx.invoices.list_invoices() == []
        assert ctx.db.integrity_check() == "ok"

        print("phase2_invoice_editor_core_smoke_test passed")
        print("multi-line=ok unit-factor=5 historical-edit=ok rollback=ok hard-delete-rebuild=ok")


if __name__ == "__main__":
    main()
