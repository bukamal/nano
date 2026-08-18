from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qeid_offline.app_context import AppContext
from qeid_offline.services.invoice_service import InvoiceLineInput


def close(a, b, eps=1e-6):
    assert abs(float(a) - float(b)) <= eps, (a, b)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qeid-phase3-edge-") as td:
        ctx = AppContext.create(Path(td) / "qeid.db")
        c1 = ctx.customers.create("عميل أ")
        c2 = ctx.customers.create("عميل ب")
        service = ctx.items.create(name="خدمة edge", item_type="خدمة", selling_price=100)
        inv = ctx.invoices.create_invoice(
            invoice_type="sale",
            customer_id=c1,
            invoice_date="2026-03-01",
            lines=[InvoiceLineInput(description="خدمة", item_id=service, quantity=1, unit_price=100)],
        )
        voucher = ctx.payments.create_voucher(
            voucher_type="receipt",
            customer_id=c1,
            amount=100,
            voucher_date="2026-03-02",
            allocation_mode="oldest",
        )
        v = ctx.payments.get_voucher(voucher)
        close(v["allocated_amount"], 100)
        allocatable = ctx.payments.allocatable_invoices("customer", c1, exclude_payment_id=int(v["payment_id"]))
        assert len(allocatable) == 1 and int(allocatable[0]["id"]) == inv
        close(allocatable[0]["allocatable_amount"], 100)

        # Editing to a partial voucher recreates exact allocations and balances.
        ctx.payments.update_voucher(
            voucher,
            voucher_type="receipt",
            customer_id=c1,
            amount=60,
            voucher_date="2026-03-02",
            allocation_mode="oldest",
        )
        close(ctx.invoices.get_invoice(inv)["paid_amount"], 60)
        close(ctx.customers.get(c1)["balance"], 40)

        # Moving an unallocated voucher between customers moves the account credit.
        credit = ctx.payments.create_voucher(
            voucher_type="receipt",
            customer_id=c1,
            amount=25,
            voucher_date="2026-03-03",
            allocation_mode="none",
        )
        close(ctx.customers.get(c1)["balance"], 15)
        ctx.payments.update_voucher(
            credit,
            voucher_type="receipt",
            customer_id=c2,
            amount=25,
            voucher_date="2026-03-03",
            allocation_mode="none",
        )
        close(ctx.customers.get(c1)["balance"], 40)
        close(ctx.customers.get(c2)["balance"], -25)

        # Deleting an invoice never deletes an independent voucher. Allocation
        # disappears and the receipt becomes credit on the customer's account.
        ctx.invoices.delete_invoice(inv)
        v = ctx.payments.get_voucher(voucher)
        assert v is not None
        close(v["allocated_amount"], 0)
        close(v["unallocated_amount"], 60)
        close(ctx.customers.get(c1)["balance"], -60)

        ctx.payments.delete_voucher(voucher)
        close(ctx.customers.get(c1)["balance"], 0)
        assert ctx.db.integrity_check() == "ok"
        print("phase3_allocation_edge_cases_smoke_test passed")
        print("voucher-edit=ok move-credit=ok invoice-delete-preserves-voucher=ok")


if __name__ == "__main__":
    main()
