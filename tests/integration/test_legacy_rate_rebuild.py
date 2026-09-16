"""Regression: rebuild must tolerate legacy rate-derived raw amounts.

Real-world incident (nano_backup_20260910_205607.nanobackup): invoices
created during the dual-currency rollout stored totals derived from
SYP/USD rates -- raw repeating floats like 51000/13500 = 3.7760000000000002
-- i.e. *before* the cent-quantization write discipline existed. The
rebuilder quantized only ``initial_paid_amount`` and compared it against
the raw total, so 39/88 fully-paid invoices failed every rebuild with
"الدفعة الأولى غير صالحة للفاتورة #1", and restore-then-cold-start
(AppContext.create runs the rebuild) died with a white screen after
restore.

The guard: the initial-payment comparison must be raw-vs-raw, and the
allocation validations must compare quantized-vs-quantized; a
quantization step may never turn an equal pair into a "greater" one.
"""
from __future__ import annotations

import pytest

from nano_offline.app_context import AppContext
from nano_offline.services.accounting_rebuilder import AccountingRebuilder
from nano_offline.services.invoice_service import InvoiceLineInput


def _legacy_db(tmp_path):
    """An AppContext with one fully-paid purchase whose stored total/initial
    are raw repeating floats (what the old currency-conversion editor saved)."""
    ctx = AppContext.create(tmp_path / "nano.db")
    unit_id = ctx.definitions.create_unit("قطعة", "ق")
    supplier_id = ctx.suppliers.create("مورد")
    item_id = ctx.items.create(name="مادة", purchase_price=5, selling_price=10, quantity=0, base_unit_id=unit_id)
    inv_id = ctx.invoices.create_invoice(
        invoice_type="purchase", supplier_id=supplier_id,
        paid_amount=51000 / 13500,  # 3.7760000000000002 raw, like the legacy rows
        lines=[InvoiceLineInput(description="بند", item_id=item_id, quantity=1, unit_price=51000 / 13500, unit_id=unit_id)],
    )
    with ctx.db.connect() as conn:
        conn.execute("UPDATE invoices SET total=3.7760000000000002, initial_paid_amount=3.7760000000000002 WHERE id=?", (inv_id,))
        conn.execute("UPDATE invoice_lines SET total=3.7760000000000002 WHERE invoice_id=?", (inv_id,))
    return ctx, inv_id


def test_rebuild_accepts_raw_equal_initial(tmp_path):
    ctx, inv_id = _legacy_db(tmp_path)
    # Must not raise: initial (raw) == total (raw).
    with ctx.db.transaction() as conn:
        AccountingRebuilder.rebuild_financials(conn)
    row = ctx.invoices.get_invoice(inv_id)
    assert row is not None
    assert abs(row["paid_amount"] - row["total"]) < 1e-9
    assert row["payment_status"] == "paid"


def test_cold_start_after_legacy_raw_rows(tmp_path):
    ctx, _ = _legacy_db(tmp_path)
    # Simulate process restart: AppContext.create rebuilds derived state.
    fresh = AppContext.create(ctx.db.path)
    assert fresh.db.integrity_check() == "ok"


def test_allocation_validation_is_quantization_symmetric(tmp_path):
    """A *stored* (voucher-sourced) payment raw at 3.7760000000000002 with a
    cent-quantized allocation of 3.78 is the same legacy pattern; the
    payment-level over-allocation guard compares quantized-vs-quantized so
    it must not flag it."""
    ctx = AppContext.create(tmp_path / "nano.db")
    supplier_id = ctx.suppliers.create("مورد")
    inv_id = ctx.invoices.create_invoice(
        invoice_type="purchase", supplier_id=supplier_id, paid_amount=0,
        lines=[InvoiceLineInput(description="بند", quantity=1, unit_price=3.78)],
    )
    with ctx.db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO payments(supplier_id,direction,amount,payment_date,notes,source_type)"
            " VALUES(?,?,?,?, 'سند صرف', 'voucher')",
            (supplier_id, "out", 3.7760000000000002, "2026-09-10"),
        )
        conn.execute(
            "INSERT INTO payment_allocations(payment_id,invoice_id,amount) VALUES(?,?,?)",
            (int(cur.lastrowid), inv_id, 3.78),
        )
    with ctx.db.transaction() as conn:
        AccountingRebuilder.rebuild_financials(conn)  # 3.78 == quantized(3.7760000000000002)


def test_genuinely_invalid_initial_still_raises(tmp_path):
    ctx, inv_id = _legacy_db(tmp_path)
    with ctx.db.connect() as conn:
        conn.execute("UPDATE invoices SET initial_paid_amount=99.0 WHERE id=?", (inv_id,))
    with pytest.raises(ValueError, match="الدفعة الأولى غير صالحة"):
        with ctx.db.transaction() as conn:
            AccountingRebuilder.rebuild_financials(conn)
