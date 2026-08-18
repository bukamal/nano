from __future__ import annotations

from qeid_offline.core.database import Database


class DashboardService:
    def __init__(self, db: Database):
        self.db = db

    def summary(self) -> dict:
        with self.db.connect() as conn:
            sales = float(conn.execute("SELECT COALESCE(SUM(total),0) FROM invoices WHERE type='sale'").fetchone()[0])
            purchases = float(conn.execute("SELECT COALESCE(SUM(total),0) FROM invoices WHERE type='purchase'").fetchone()[0])
            cogs = float(conn.execute("SELECT COALESCE(SUM(cost_amount),0) FROM invoice_lines il JOIN invoices i ON i.id=il.invoice_id WHERE i.type='sale'").fetchone()[0])
            expenses = float(conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses").fetchone()[0])
            receivables = float(conn.execute("SELECT COALESCE(SUM(CASE WHEN balance>0 THEN balance ELSE 0 END),0) FROM customers").fetchone()[0])
            customer_credits = float(conn.execute("SELECT COALESCE(SUM(CASE WHEN balance<0 THEN -balance ELSE 0 END),0) FROM customers").fetchone()[0])
            payables = float(conn.execute("SELECT COALESCE(SUM(CASE WHEN balance>0 THEN balance ELSE 0 END),0) FROM suppliers").fetchone()[0])
            supplier_advances = float(conn.execute("SELECT COALESCE(SUM(CASE WHEN balance<0 THEN -balance ELSE 0 END),0) FROM suppliers").fetchone()[0])
            inventory = float(conn.execute("SELECT COALESCE(SUM(quantity*average_cost),0) FROM items WHERE item_type='مخزون'").fetchone()[0])
            cash = float(conn.execute("SELECT COALESCE(SUM(debit-credit),0) FROM ledger_entries WHERE account_code='CASH'").fetchone()[0])
            return {
                "sales": sales,
                "purchases": purchases,
                "cogs": cogs,
                "expenses": expenses,
                "net_profit": sales - cogs - expenses,
                "receivables": receivables,
                "customer_credits": customer_credits,
                "payables": payables,
                "supplier_advances": supplier_advances,
                "inventory_value": inventory,
                "cash": cash,
            }
