from __future__ import annotations

from datetime import date, timedelta

from nano_offline.core.database import Database


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

    def today_summary(self) -> dict:
        """Invoice count and total for *today's* sale invoices only.

        Distinct from :meth:`summary` (all-time KPIs) and :meth:`sales_trend`
        (multi-day totals with no invoice count) -- built for the POS
        quick-sale screen, which wants a single at-a-glance "how's today
        going" figure without pulling the full dashboard.
        """
        today = date.today().isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(total),0) AS total FROM invoices WHERE type='sale' AND invoice_date=?",
                (today,),
            ).fetchone()
        return {"count": int(row["cnt"]), "total": float(row["total"])}

    def sales_trend(self, days: int = 14) -> list[dict]:
        """Daily sales totals for the last ``days`` days, oldest first.

        Always anchored on *today* regardless of any period the dashboard's
        KPI cards happen to be filtered to -- this is a short-range trend
        strip, not a period report, so it stays a stable reference line the
        person can glance at no matter which period tab is selected.
        """
        days = max(1, int(days))
        today = date.today()
        start = (today - timedelta(days=days - 1)).isoformat()
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT invoice_date, COALESCE(SUM(total),0) AS total
                   FROM invoices WHERE type='sale' AND invoice_date>=?
                   GROUP BY invoice_date""",
                (start,),
            ).fetchall()
        by_date = {r["invoice_date"]: float(r["total"]) for r in rows}
        return [
            {
                "date": (today - timedelta(days=i)).isoformat(),
                "total": by_date.get((today - timedelta(days=i)).isoformat(), 0.0),
            }
            for i in range(days - 1, -1, -1)
        ]

    def restock_predictions(
        self, *, window_days: int = 30, horizon_days: int = 14, limit: int = 5
    ) -> list[dict]:
        """Stocked items projected to run out within ``horizon_days``.

        Estimated from each item's own recent sale velocity (quantity sold
        over the last ``window_days``, from ``inventory_movements``) rather
        than the static ``quantity <= threshold`` rule the low-stock alert
        elsewhere uses -- a slow mover sitting at quantity 4 is not urgent
        the way an item burning through 4 units a day is. Items with no
        sales in the window (velocity unknown) or already out of stock
        (covered by the low-stock alert instead) are excluded rather than
        guessed at.
        """
        window_days = max(1, int(window_days))
        start = (date.today() - timedelta(days=window_days)).isoformat()
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT it.id AS item_id, it.name, it.quantity,
                       it.purchase_price, it.average_cost,
                       COALESCE(SUM(CASE WHEN im.quantity_delta<0 THEN -im.quantity_delta ELSE 0 END),0) AS sold_qty
                FROM items it
                LEFT JOIN inventory_movements im
                       ON im.item_id=it.id AND im.movement_type='sale' AND im.movement_date>=?
                WHERE it.item_type='مخزون'
                GROUP BY it.id, it.name, it.quantity, it.purchase_price, it.average_cost
                """,
                (start,),
            ).fetchall()
        predictions: list[dict] = []
        for row in rows:
            quantity = float(row["quantity"] or 0)
            sold = float(row["sold_qty"] or 0)
            if quantity <= 0 or sold <= 0:
                continue
            velocity = sold / window_days
            days_left = quantity / velocity
            if days_left <= horizon_days:
                # Order enough to cover another full horizon after restock.
                suggested = max(velocity * horizon_days - quantity, velocity * 7, 1.0)
                predictions.append(
                    {
                        "item_id": row["item_id"],
                        "name": row["name"],
                        "quantity": quantity,
                        "daily_velocity": velocity,
                        "days_left": days_left,
                        "suggested_qty": round(suggested, 2),
                        "purchase_price": float(row["purchase_price"] or 0),
                        "average_cost": float(row["average_cost"] or 0),
                    }
                )
        predictions.sort(key=lambda p: p["days_left"])
        return predictions[: max(1, int(limit))]

    def purchase_list(
        self, *, window_days: int = 30, horizon_days: int = 14, limit: int = 50
    ) -> dict:
        """Build a ready-to-order purchase list from restock predictions.

        Returns ``{"lines": [...], "estimated_cost_usd": float, "count": int}``.
        Each line includes ``suggested_qty`` and cost estimates in stored USD.
        """
        lines = self.restock_predictions(
            window_days=window_days, horizon_days=horizon_days, limit=limit
        )
        total = 0.0
        for line in lines:
            unit_cost = float(line.get("average_cost") or line.get("purchase_price") or 0)
            qty = float(line.get("suggested_qty") or 0)
            line["line_cost_usd"] = unit_cost * qty
            total += line["line_cost_usd"]
        return {"lines": lines, "estimated_cost_usd": total, "count": len(lines)}

    def weekly_owner_summary(self) -> dict:
        """Owner-facing snapshot for the last 7 days vs the prior 7 days."""
        from datetime import date, timedelta
        today = date.today()
        cur_from = (today - timedelta(days=6)).isoformat()
        cur_to = today.isoformat()
        prev_from = (today - timedelta(days=13)).isoformat()
        prev_to = (today - timedelta(days=7)).isoformat()
        with self.db.connect() as conn:
            def _sales(d0, d1):
                row = conn.execute(
                    "SELECT COALESCE(SUM(total),0) FROM invoices WHERE type='sale' AND invoice_date>=? AND invoice_date<=?",
                    (d0, d1),
                ).fetchone()
                return float(row[0] or 0)

            def _cogs(d0, d1):
                row = conn.execute(
                    """SELECT COALESCE(SUM(il.cost_amount),0)
                       FROM invoice_lines il
                       JOIN invoices i ON i.id=il.invoice_id
                       WHERE i.type='sale' AND i.invoice_date>=? AND i.invoice_date<=?""",
                    (d0, d1),
                ).fetchone()
                return float(row[0] or 0)

            def _expenses(d0, d1):
                row = conn.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date>=? AND expense_date<=?",
                    (d0, d1),
                ).fetchone()
                return float(row[0] or 0)

            sales = _sales(cur_from, cur_to)
            prev_sales = _sales(prev_from, prev_to)
            cogs = _cogs(cur_from, cur_to)
            expenses = _expenses(cur_from, cur_to)
            receivables = float(conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN balance>0 THEN balance ELSE 0 END),0) FROM customers"
            ).fetchone()[0] or 0)
            low_stock = int(conn.execute(
                "SELECT COUNT(*) FROM items WHERE item_type='مخزون' AND quantity < 5"
            ).fetchone()[0] or 0)
        profit = sales - cogs - expenses
        change = None
        if prev_sales > 1e-9:
            change = ((sales - prev_sales) / prev_sales) * 100.0
        elif sales > 1e-9:
            change = 100.0
        return {
            "from": cur_from,
            "to": cur_to,
            "sales": sales,
            "prev_sales": prev_sales,
            "sales_change_pct": change,
            "cogs": cogs,
            "expenses": expenses,
            "approx_profit": profit,
            "receivables": receivables,
            "low_stock_count": low_stock,
        }

