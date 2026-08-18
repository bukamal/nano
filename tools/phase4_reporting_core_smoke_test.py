from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qeid_offline.app_context import AppContext
from qeid_offline.services.invoice_service import InvoiceLineInput


def close(actual, expected, eps=1e-6):
    assert abs(float(actual) - float(expected)) <= eps, (actual, expected)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qeid-phase4-reporting-") as td:
        ctx = AppContext.create(Path(td) / "qeid.db")
        customer = ctx.customers.create("عميل التقارير")
        supplier = ctx.suppliers.create("مورد التقارير")
        unit = ctx.definitions.create_unit("قطعة", "pc")
        stock = ctx.items.create(
            name="مادة تقرير", item_type="مخزون", purchase_price=10,
            selling_price=20, quantity=10, base_unit_id=unit,
        )
        service = ctx.items.create(name="خدمة تقرير", item_type="خدمة", selling_price=50)

        purchase = ctx.invoices.create_invoice(
            invoice_type="purchase", supplier_id=supplier, invoice_date="2026-01-02",
            paid_amount=10,
            lines=[InvoiceLineInput(description="توريد", item_id=stock, unit_id=unit, quantity=5, unit_price=12)],
        )
        sale1 = ctx.invoices.create_invoice(
            invoice_type="sale", customer_id=customer, invoice_date="2026-01-03",
            paid_amount=20,
            lines=[InvoiceLineInput(description="بيع مادة", item_id=stock, unit_id=unit, quantity=6, unit_price=20)],
        )
        sale2 = ctx.invoices.create_invoice(
            invoice_type="sale", customer_id=customer, invoice_date="2026-01-03",
            paid_amount=0,
            lines=[InvoiceLineInput(description="خدمة", item_id=service, quantity=1, unit_price=50)],
        )
        cat = ctx.expenses.create_category("تشغيل")
        ctx.expenses.create_expense(
            amount=15, description="مصروف تشغيلي", expense_date="2026-01-04", category_id=cat,
        )
        ctx.payments.create_voucher(
            voucher_type="receipt", customer_id=customer, amount=30,
            voucher_date="2026-01-05", allocation_mode="oldest",
        )
        ctx.payments.create_voucher(
            voucher_type="payment", supplier_id=supplier, amount=20,
            voucher_date="2026-01-05", allocation_mode="oldest",
        )

        pnl = ctx.reports.income_statement(date_from="2026-01-01", date_to="2026-01-31")
        close(pnl["sales"], 170)
        close(pnl["purchases"], 60)
        close(pnl["cogs"], 64)
        close(pnl["gross_profit"], 106)
        close(pnl["expenses"], 15)
        close(pnl["net_profit"], 91)
        assert pnl["expense_breakdown"][0]["category"] == "تشغيل"
        close(pnl["expense_breakdown"][0]["amount"], 15)

        invoices = ctx.reports.invoice_profitability(date_from="2026-01-03", date_to="2026-01-03")
        assert len(invoices) == 2
        inv_by_id = {int(r["id"]): r for r in invoices}
        close(inv_by_id[sale1]["cogs"], 64)
        close(inv_by_id[sale1]["gross_profit"], 56)
        close(inv_by_id[sale2]["cogs"], 0)
        close(inv_by_id[sale2]["gross_profit"], 50)

        items = ctx.reports.item_profitability(date_from="2026-01-01", date_to="2026-01-31")
        by_name = {r["item_name"]: r for r in items}
        close(by_name["مادة تقرير"]["quantity_in_base"], 6)
        close(by_name["مادة تقرير"]["revenue"], 120)
        close(by_name["مادة تقرير"]["cogs"], 64)
        close(by_name["مادة تقرير"]["gross_profit"], 56)
        close(by_name["خدمة تقرير"]["gross_profit"], 50)
        assert ctx.reports.top_selling_items(order_by="revenue")[0]["item_name"] == "مادة تقرير"

        inventory = ctx.reports.inventory_report(date_from="2026-01-01", date_to="2026-01-31")
        stock_row = next(r for r in inventory if r["name"] == "مادة تقرير")
        close(stock_row["opening_quantity_period"], 10)
        close(stock_row["opening_value"], 100)
        close(stock_row["purchases_quantity"], 5)
        close(stock_row["purchases_value"], 60)
        close(stock_row["sales_quantity"], 6)
        close(stock_row["cogs_value"], 64)
        close(stock_row["closing_quantity"], 9)
        close(stock_row["closing_value"], 96)
        close(stock_row["closing_unit_cost"], 96 / 9)
        valuation = ctx.reports.inventory_valuation(as_of="2026-01-31")
        close(valuation["total_value"], 96)

        cust = ctx.reports.party_balances("customer", as_of="2026-01-03")
        close(cust["positive_total"], 150)  # 170 invoices - 20 initial paid
        cust_current = ctx.reports.party_balances("customer", as_of="2026-01-31")
        close(cust_current["positive_total"], 120)
        supplier_bal = ctx.reports.party_balances("supplier", as_of="2026-01-31")
        close(supplier_bal["positive_total"], 30)

        open_before_receipt = ctx.reports.outstanding_invoices("customer", as_of="2026-01-03")
        close(sum(r["remaining_amount"] for r in open_before_receipt), 150)
        open_current = ctx.reports.outstanding_invoices("customer", as_of="2026-01-31")
        close(sum(r["remaining_amount"] for r in open_current), 120)
        assert {int(r["id"]) for r in open_current} == {sale1, sale2}

        cash = ctx.reports.cash_movement(date_from="2026-01-01", date_to="2026-01-31")
        close(cash["receipts"], 50)
        close(cash["payments"], 45)
        close(cash["closing_balance"], 5)

        january_3 = ctx.reports.income_statement(date_from="2026-01-03", date_to="2026-01-03")
        close(january_3["sales"], 170)
        close(january_3["expenses"], 0)
        try:
            ctx.reports.income_statement(date_from="2026-02-01", date_to="2026-01-01")
        except ValueError as exc:
            assert "البداية" in str(exc)
        else:
            raise AssertionError("invalid date range should fail")

        assert ctx.db.integrity_check() == "ok"
        print("phase4_reporting_core_smoke_test passed")
        print("pnl=91 inventory=96 receivables=120 payables=30 cash=5 historical-as-of=ok")


if __name__ == "__main__":
    main()
