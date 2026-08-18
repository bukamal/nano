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
    with tempfile.TemporaryDirectory(prefix="qeid-phase3-") as td:
        ctx = AppContext.create(Path(td) / "qeid.db")
        customer = ctx.customers.create("عميل ذمم")
        supplier = ctx.suppliers.create("مورد ذمم")
        service = ctx.items.create(name="خدمة محاسبية", item_type="خدمة", selling_price=100, purchase_price=80)

        sale1 = ctx.invoices.create_invoice(
            invoice_type="sale",
            customer_id=customer,
            invoice_date="2026-01-01",
            paid_amount=20,
            lines=[InvoiceLineInput(description="خدمة 1", item_id=service, quantity=1, unit_price=100)],
        )
        close(ctx.invoices.get_invoice(sale1)["paid_amount"], 20)
        close(ctx.customers.get(customer)["balance"], 80)

        receipt1 = ctx.payments.create_voucher(
            voucher_type="receipt",
            customer_id=customer,
            amount=50,
            voucher_date="2026-01-02",
            allocation_mode="oldest",
        )
        inv = ctx.invoices.get_invoice(sale1)
        close(inv["paid_amount"], 70)
        close(inv["remaining_amount"], 30)
        close(ctx.customers.get(customer)["balance"], 30)

        sale2 = ctx.invoices.create_invoice(
            invoice_type="sale",
            customer_id=customer,
            invoice_date="2026-01-03",
            paid_amount=0,
            lines=[InvoiceLineInput(description="خدمة 2", item_id=service, quantity=1, unit_price=40)],
        )
        close(ctx.customers.get(customer)["balance"], 70)

        receipt2 = ctx.payments.create_voucher(
            voucher_type="receipt",
            customer_id=customer,
            amount=100,
            voucher_date="2026-01-04",
            allocation_mode="oldest",
        )
        close(ctx.invoices.get_invoice(sale1)["paid_amount"], 100)
        close(ctx.invoices.get_invoice(sale2)["paid_amount"], 40)
        close(ctx.customers.get(customer)["balance"], -30)
        summary_credit = ctx.dashboard.summary()
        close(summary_credit["receivables"], 0)
        close(summary_credit["customer_credits"], 30)
        v2 = ctx.payments.get_voucher(receipt2)
        close(v2["allocated_amount"], 70)
        close(v2["unallocated_amount"], 30)

        st = ctx.statements.party_statement("customer", customer)
        close(st["current_balance"], -30)
        close(st["closing_balance"], -30)
        assert st["open_invoices"] == []
        assert len(st["rows"]) >= 5

        # Deleting an overpayment voucher restores its allocations and account balance.
        ctx.payments.delete_voucher(receipt2)
        close(ctx.invoices.get_invoice(sale1)["paid_amount"], 70)
        close(ctx.invoices.get_invoice(sale2)["paid_amount"], 0)
        close(ctx.customers.get(customer)["balance"], 70)

        # Manual allocation can target multiple invoices while leaving unapplied credit.
        receipt3 = ctx.payments.create_voucher(
            voucher_type="receipt",
            customer_id=customer,
            amount=60,
            voucher_date="2026-01-05",
            allocation_mode="manual",
            allocations={sale1: 20, sale2: 25},
        )
        close(ctx.invoices.get_invoice(sale1)["paid_amount"], 90)
        close(ctx.invoices.get_invoice(sale2)["paid_amount"], 25)
        close(ctx.payments.get_voucher(receipt3)["unallocated_amount"], 15)
        close(ctx.customers.get(customer)["balance"], 10)  # invoices 140 - payments 130

        # Invoice-specific later payment uses a voucher and exact allocation.
        later = ctx.payments.register_invoice_payment(sale1, 10, payment_date="2026-01-06")
        close(ctx.invoices.get_invoice(sale1)["paid_amount"], 100)
        close(ctx.customers.get(customer)["balance"], 0)
        assert ctx.payments.get_voucher(later)["allocated_amount"] == 10

        # Purchase/payable direction mirrors receipts and supports supplier credit.
        purchase = ctx.invoices.create_invoice(
            invoice_type="purchase",
            supplier_id=supplier,
            invoice_date="2026-02-01",
            paid_amount=20,
            lines=[InvoiceLineInput(description="خدمة مورد", item_id=service, quantity=1, unit_price=120)],
        )
        close(ctx.suppliers.get(supplier)["balance"], 100)
        outgoing = ctx.payments.create_voucher(
            voucher_type="payment",
            supplier_id=supplier,
            amount=150,
            voucher_date="2026-02-02",
            allocation_mode="oldest",
        )
        close(ctx.invoices.get_invoice(purchase)["paid_amount"], 120)
        close(ctx.suppliers.get(supplier)["balance"], -50)
        summary_supplier_credit = ctx.dashboard.summary()
        close(summary_supplier_credit["payables"], 0)
        close(summary_supplier_credit["supplier_advances"], 50)
        close(ctx.payments.get_voucher(outgoing)["unallocated_amount"], 50)
        supplier_statement = ctx.statements.party_statement("supplier", supplier)
        close(supplier_statement["closing_balance"], -50)

        # Expense affects P&L and cash ledger, and can be edited/deleted safely.
        meals = ctx.expenses.create_category("ضيافة")
        expense_id = ctx.expenses.create_expense(
            amount=25,
            description="ضيافة مكتب",
            expense_date="2026-02-03",
            category_id=meals,
        )
        close(ctx.dashboard.summary()["expenses"], 25)
        ctx.expenses.update_expense(
            expense_id,
            amount=30,
            description="ضيافة مكتب معدلة",
            expense_date="2026-02-03",
            category_id=meals,
        )
        close(ctx.dashboard.summary()["expenses"], 30)
        ctx.expenses.delete_expense(expense_id)
        close(ctx.dashboard.summary()["expenses"], 0)

        # Reducing an invoice below already allocated voucher payments must rollback.
        before = ctx.invoices.get_invoice(sale2)
        try:
            ctx.invoices.update_invoice(
                sale2,
                invoice_type="sale",
                customer_id=customer,
                invoice_date="2026-01-03",
                paid_amount=0,
                lines=[InvoiceLineInput(description="أقل من التوزيع", item_id=service, quantity=1, unit_price=20)],
            )
        except ValueError as exc:
            assert "الدفعات الموزعة" in str(exc)
        else:
            raise AssertionError("allocated invoice reduction should fail")
        after = ctx.invoices.get_invoice(sale2)
        close(after["total"], before["total"])
        close(after["paid_amount"], before["paid_amount"])

        assert ctx.db.integrity_check() == "ok"
        print("phase3_financial_workflow_smoke_test passed")
        print("receipts=ok allocations=oldest+manual credit-balance=ok supplier-payments=ok expenses=ok statements=ok rollback=ok")


if __name__ == "__main__":
    main()
