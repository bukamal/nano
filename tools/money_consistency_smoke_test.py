from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.app_context import AppContext  # noqa: E402
from nano_offline.core import money  # noqa: E402
from nano_offline.core import money_consistency  # noqa: E402
from nano_offline.services.invoice_service import InvoiceLineInput  # noqa: E402


def main() -> None:
    # --- money module basics: the classical 0.1+0.2 and 0.1*3 traps --------
    assert money.quantized(0.1 + 0.2) == 0.3
    assert money.quantized(0.1 * 3) == 0.3
    assert money.to_cents(0.3) == 30 and money.to_cents(money.from_cents(30)) == 30
    assert float(money.quantize_sum([0.1, 0.2, 0.4])) == 0.7
    assert float(money.quantize("1.005")) == 1.01  # round-half-up

    with tempfile.TemporaryDirectory(prefix="nano-money-consist-") as td:
        ctx = AppContext.create(Path(td) / "nano.db")
        unit_id = ctx.definitions.create_unit("قطعة", "قط")
        customer_id = ctx.customers.create("عميل تجريبي", "0900000000")
        supplier_id = ctx.suppliers.create("مورد تجريبي")
        item_id = ctx.items.create(
            name="مادة X", item_type="مخزون",
            purchase_price=0.10, selling_price=0.10, quantity=0, base_unit_id=unit_id,
        )
        service_id = ctx.items.create(
            name="خدمة Y", item_type="خدمة",
            purchase_price=0.20, selling_price=0.20, quantity=0, base_unit_id=unit_id,
        )

        # Purchase 3 x 0.10 (naive float => 0.30000000000000004).
        purchase_id = ctx.invoices.create_invoice(
            invoice_type="purchase", supplier_id=supplier_id, paid_amount=0.3,
            lines=[
                InvoiceLineInput(description="مادة X", item_id=item_id, quantity=3, unit_price=0.10, unit_id=unit_id),
            ],
        )
        # Cash sale to a customer, fully paid, same float-trap prices.
        sale_stock = ctx.invoices.create_invoice(
            invoice_type="sale", customer_id=customer_id, paid_amount=0.30,
            lines=[
                InvoiceLineInput(description="مادة X", item_id=item_id, quantity=3, unit_price=0.10, unit_id=unit_id),
            ],
        )
        # Service sale: exercises the unit_cost/cost_amount snapshot path and
        # 3 x 0.20 (naive float => 0.6000000000000001).
        sale_service = ctx.invoices.create_invoice(
            invoice_type="sale", customer_id=customer_id, paid_amount=0.6,
            lines=[
                InvoiceLineInput(description="خدمة Y", item_id=service_id, quantity=3, unit_price=0.20, unit_id=unit_id),
            ],
        )
        assert sale_stock and sale_service and purchase_id

        # Expense through the _validate funnel (0.1+0.2 => 0.3 pushed in).
        cat_id = ctx.expenses.create_category("تشغيل")
        ctx.expenses.create_expense(amount=0.1 + 0.2, description="كهرباء", category_id=cat_id)

        # Sanity: stored values must already be clean cents even for the
        # float-prone amounts the services received.
        with ctx.db.connect() as conn:
            assert money.to_cents(float(conn.execute("SELECT total FROM invoices WHERE id=?", (sale_stock,)).fetchone()[0])) == 30
            assert money.to_cents(float(conn.execute("SELECT total FROM invoices WHERE id=?", (sale_service,)).fetchone()[0])) == 60
            line_total = conn.execute(
                "SELECT total FROM invoice_lines WHERE invoice_id=?", (sale_stock,)
            ).fetchone()[0]
            assert money.to_cents(float(line_total)) == 30

        # 1) A database written through the services must be fully consistent.
        issues = money_consistency.run_checks(ctx.db.connect())
        assert not issues, money_consistency.summarize(issues)

        # 2) Injecting sub-cent noise must be caught immediately.
        with ctx.db.transaction() as conn:
            conn.execute(
                "UPDATE invoice_lines SET total=total+0.034 WHERE invoice_id=?",
                (sale_stock,),
            )
        issues = money_consistency.run_checks(ctx.db.connect())
        kinds = {i["kind"] for i in issues}
        assert {"storage_clean", "invoice_line_total", "invoice_total"} <= kinds, kinds
        assert any(i["subject"].startswith("invoice_lines.total") for i in issues)


if __name__ == "__main__":
    main()
    print("money_consistency_smoke_test: OK")