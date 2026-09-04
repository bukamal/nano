from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.core.database import Database, SCHEMA_VERSION
from nano_offline.services.invoice_service import InvoiceLineInput


def approx(a, b, eps=1e-7):
    assert abs(float(a) - float(b)) <= eps, (a, b)


with tempfile.TemporaryDirectory(prefix="qeid-phase7-service-cost-") as td:
    db_path = Path(td) / "nano.db"
    ctx = AppContext.create(db_path)
    customer_id = ctx.customers.create("عميل خدمة")
    service_id = ctx.items.create(
        name="استشارة محاسبية",
        item_type="خدمة",
        purchase_price=30,
        selling_price=100,
    )
    inv1 = ctx.invoices.create_invoice(
        invoice_type="sale",
        customer_id=customer_id,
        invoice_date="2026-08-01",
        paid_amount=200,
        lines=[InvoiceLineInput(item_id=service_id, description="", quantity=2, unit_price=100)],
    )
    inv1_data = ctx.invoices.get_invoice(inv1)
    approx(inv1_data["lines"][0]["unit_cost"], 30)
    approx(inv1_data["lines"][0]["cost_amount"], 60)
    profit1 = next(x for x in ctx.reports.invoice_profitability() if int(x["id"]) == inv1)
    approx(profit1["cogs"], 60)
    approx(profit1["gross_profit"], 140)

    # Changing the configured service cost must not rewrite historical invoices.
    ctx.items.update(
        service_id,
        name="استشارة محاسبية",
        item_type="خدمة",
        purchase_price=50,
        selling_price=100,
    )
    ctx.invoices.rebuild_derived_state()
    inv1_after = ctx.invoices.get_invoice(inv1)
    approx(inv1_after["lines"][0]["unit_cost"], 30)
    approx(inv1_after["lines"][0]["cost_amount"], 60)

    inv2 = ctx.invoices.create_invoice(
        invoice_type="sale",
        customer_id=customer_id,
        invoice_date="2026-08-02",
        paid_amount=100,
        lines=[InvoiceLineInput(item_id=service_id, description="", quantity=1, unit_price=100)],
    )
    inv2_data = ctx.invoices.get_invoice(inv2)
    approx(inv2_data["lines"][0]["unit_cost"], 50)
    approx(inv2_data["lines"][0]["cost_amount"], 50)
    with ctx.db.connect() as conn:
        movement_count = conn.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE item_id=? AND invoice_id IN (?,?)",
            (service_id, inv1, inv2),
        ).fetchone()[0]
    assert movement_count == 0

    # Simulate a phase-6 database: schema marker 4 + old zero-cost service line.
    with ctx.db.transaction() as conn:
        conn.execute("UPDATE schema_meta SET value='4' WHERE key='schema_version'")
        conn.execute("UPDATE invoice_lines SET unit_cost=0,cost_amount=0 WHERE invoice_id=?", (inv1,))
        conn.execute("UPDATE items SET purchase_price=40 WHERE id=?", (service_id,))
    migrated = Database(db_path)
    migrated.initialize()
    assert SCHEMA_VERSION == 9
    with migrated.connect() as conn:
        schema = int(conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0])
        line = conn.execute("SELECT unit_cost,cost_amount FROM invoice_lines WHERE invoice_id=?", (inv1,)).fetchone()
    assert schema == SCHEMA_VERSION
    approx(line["unit_cost"], 40)
    approx(line["cost_amount"], 80)

print("phase7_service_cost_smoke_test passed")
