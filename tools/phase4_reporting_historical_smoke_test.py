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
    with tempfile.TemporaryDirectory(prefix="qeid-phase4-historical-") as td:
        ctx = AppContext.create(Path(td) / "qeid.db")
        customer = ctx.customers.create("عميل تاريخي")
        item = ctx.items.create(name="خدمة زمنية", item_type="خدمة", selling_price=100)
        invoice = ctx.invoices.create_invoice(
            invoice_type="sale", customer_id=customer, invoice_date="2026-03-01", paid_amount=10,
            lines=[InvoiceLineInput(description="خدمة", item_id=item, quantity=1, unit_price=100)],
        )
        voucher = ctx.payments.create_voucher(
            voucher_type="receipt", customer_id=customer, amount=30,
            voucher_date="2026-03-10", allocation_mode="oldest",
        )
        close(ctx.reports.party_balances("customer", as_of="2026-03-05")["positive_total"], 90)
        close(sum(r["remaining_amount"] for r in ctx.reports.outstanding_invoices("customer", as_of="2026-03-05")), 90)
        close(ctx.reports.cash_movement(date_to="2026-03-05")["closing_balance"], 10)
        close(ctx.reports.party_balances("customer", as_of="2026-03-31")["positive_total"], 60)
        close(ctx.reports.cash_movement(date_to="2026-03-31")["closing_balance"], 40)

        # Changing a later payment must not alter the earlier as-of report.
        ctx.payments.update_voucher(
            voucher, voucher_type="receipt", customer_id=customer, supplier_id=None,
            amount=50, voucher_date="2026-03-10", allocation_mode="oldest",
        )
        close(ctx.reports.party_balances("customer", as_of="2026-03-05")["positive_total"], 90)
        close(ctx.reports.party_balances("customer", as_of="2026-03-31")["positive_total"], 40)
        close(ctx.reports.outstanding_invoices("customer", as_of="2026-03-31")[0]["remaining_amount"], 40)
        assert ctx.db.integrity_check() == "ok"
        print("phase4_reporting_historical_smoke_test passed")
        print(f"invoice={invoice} earlier-as-of=90 later-as-of=40 cash-history=ok")


if __name__ == "__main__":
    main()
