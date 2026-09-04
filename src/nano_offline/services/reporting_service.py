from __future__ import annotations

from datetime import date

from nano_offline.core.database import Database

EPSILON = 1e-9


class ReportingService:
    """Read-only local reports derived from source documents and rebuilt ledger state."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _normalize_dates(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        for value in (start, end):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("التاريخ يجب أن يكون بصيغة YYYY-MM-DD") from exc
        if start and end and start > end:
            raise ValueError("تاريخ البداية يجب ألا يكون بعد تاريخ النهاية")
        return start, end

    @staticmethod
    def _date_clause(column: str, date_from: str | None, date_to: str | None) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if date_from:
            clauses.append(f"{column}>=?")
            params.append(date_from)
        if date_to:
            clauses.append(f"{column}<=?")
            params.append(date_to)
        return (" AND ".join(clauses) if clauses else "1=1"), params

    def income_statement(self, *, date_from: str | None = None, date_to: str | None = None) -> dict:
        date_from, date_to = self._normalize_dates(date_from, date_to)
        clause, params = self._date_clause("i.invoice_date", date_from, date_to)
        e_clause, e_params = self._date_clause("e.expense_date", date_from, date_to)
        with self.db.connect() as conn:
            sales = float(conn.execute(
                f"SELECT COALESCE(SUM(i.total),0) FROM invoices i WHERE i.type='sale' AND {clause}", params
            ).fetchone()[0])
            purchases = float(conn.execute(
                f"SELECT COALESCE(SUM(i.total),0) FROM invoices i WHERE i.type='purchase' AND {clause}", params
            ).fetchone()[0])
            cogs = float(conn.execute(
                f"""SELECT COALESCE(SUM(il.cost_amount),0)
                    FROM invoice_lines il JOIN invoices i ON i.id=il.invoice_id
                    WHERE i.type='sale' AND {clause}""", params
            ).fetchone()[0])
            expenses = float(conn.execute(
                f"SELECT COALESCE(SUM(e.amount),0) FROM expenses e WHERE {e_clause}", e_params
            ).fetchone()[0])
            expense_rows = [dict(r) for r in conn.execute(
                f"""SELECT COALESCE(ec.name,e.category,'بلا تصنيف') AS category,
                           SUM(e.amount) AS amount, COUNT(*) AS count
                    FROM expenses e LEFT JOIN expense_categories ec ON ec.id=e.category_id
                    WHERE {e_clause}
                    GROUP BY COALESCE(ec.name,e.category,'بلا تصنيف')
                    ORDER BY amount DESC,category""", e_params
            ).fetchall()]
            gross_profit = sales - cogs
            return {
                "date_from": date_from,
                "date_to": date_to,
                "sales": sales,
                "purchases": purchases,
                "cogs": cogs,
                "gross_profit": gross_profit,
                "gross_margin_percent": (gross_profit / sales * 100.0) if sales > EPSILON else 0.0,
                "expenses": expenses,
                "net_profit": gross_profit - expenses,
                "expense_breakdown": expense_rows,
            }

    def invoice_profitability(self, *, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        date_from, date_to = self._normalize_dates(date_from, date_to)
        clause, params = self._date_clause("i.invoice_date", date_from, date_to)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT i.id,i.invoice_date,i.reference,i.total,i.paid_amount,
                           COALESCE(c.name,'نقدي') AS customer_name,
                           COALESCE(SUM(il.cost_amount),0) AS cogs
                    FROM invoices i
                    LEFT JOIN customers c ON c.id=i.customer_id
                    LEFT JOIN invoice_lines il ON il.invoice_id=i.id
                    WHERE i.type='sale' AND {clause}
                    GROUP BY i.id
                    ORDER BY i.invoice_date DESC,i.id DESC""",
                params,
            ).fetchall()
            result: list[dict] = []
            for raw in rows:
                row = dict(raw)
                total = float(row["total"] or 0)
                cogs = float(row["cogs"] or 0)
                profit = total - cogs
                row["gross_profit"] = profit
                row["margin_percent"] = (profit / total * 100.0) if total > EPSILON else 0.0
                row["remaining_amount"] = max(0.0, total - float(row["paid_amount"] or 0))
                result.append(row)
            return result

    def item_profitability(self, *, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        date_from, date_to = self._normalize_dates(date_from, date_to)
        clause, params = self._date_clause("i.invoice_date", date_from, date_to)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT COALESCE(it.id,0) AS item_id,
                           COALESCE(it.name,il.description) AS item_name,
                           COALESCE(it.item_type,'خدمة') AS item_type,
                           COALESCE(u.name,'') AS base_unit_name,
                           SUM(il.quantity_in_base) AS quantity_in_base,
                           SUM(il.total) AS revenue,
                           SUM(il.cost_amount) AS cogs,
                           COUNT(DISTINCT i.id) AS invoice_count
                    FROM invoice_lines il
                    JOIN invoices i ON i.id=il.invoice_id
                    LEFT JOIN items it ON it.id=il.item_id
                    LEFT JOIN units u ON u.id=it.base_unit_id
                    WHERE i.type='sale' AND {clause}
                    GROUP BY COALESCE(it.id,0),COALESCE(it.name,il.description),COALESCE(it.item_type,'خدمة'),COALESCE(u.name,'')
                    ORDER BY revenue DESC,item_name""",
                params,
            ).fetchall()
            result: list[dict] = []
            for raw in rows:
                row = dict(raw)
                revenue = float(row["revenue"] or 0)
                cogs = float(row["cogs"] or 0)
                profit = revenue - cogs
                row["gross_profit"] = profit
                row["margin_percent"] = (profit / revenue * 100.0) if revenue > EPSILON else 0.0
                result.append(row)
            return result

    def top_selling_items(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        order_by: str = "revenue",
    ) -> list[dict]:
        rows = self.item_profitability(date_from=date_from, date_to=date_to)
        key = "quantity_in_base" if order_by == "quantity" else "revenue"
        rows.sort(key=lambda row: float(row.get(key) or 0), reverse=True)
        return rows[: max(1, int(limit))]

    def inventory_report(self, *, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        """Inventory movement and valuation by item for a period.

        Opening inventory is a timeless baseline. Historical value is deterministic
        because inventory_movements.value_delta stores purchase value and sale COGS.
        """
        date_from, date_to = self._normalize_dates(date_from, date_to)
        with self.db.connect() as conn:
            items = conn.execute(
                """SELECT i.id,i.name,i.opening_quantity,i.opening_unit_cost,i.quantity,i.average_cost,
                          COALESCE(u.name,'') AS unit_name
                   FROM items i LEFT JOIN units u ON u.id=i.base_unit_id
                   WHERE i.item_type='مخزون' ORDER BY i.name"""
            ).fetchall()
            result: list[dict] = []
            for raw in items:
                item = dict(raw)
                iid = int(item["id"])
                opening_qty = float(item["opening_quantity"] or 0)
                opening_value = opening_qty * float(item["opening_unit_cost"] or 0)
                if date_from:
                    before = conn.execute(
                        """SELECT COALESCE(SUM(quantity_delta),0),COALESCE(SUM(value_delta),0)
                           FROM inventory_movements
                           WHERE item_id=? AND invoice_id IS NOT NULL AND movement_date<?""",
                        (iid, date_from),
                    ).fetchone()
                    opening_qty += float(before[0] or 0)
                    opening_value += float(before[1] or 0)

                period_where = ["item_id=?", "invoice_id IS NOT NULL"]
                p: list[object] = [iid]
                if date_from:
                    period_where.append("movement_date>=?")
                    p.append(date_from)
                if date_to:
                    period_where.append("movement_date<=?")
                    p.append(date_to)
                stats = conn.execute(
                    f"""SELECT
                            COALESCE(SUM(CASE WHEN quantity_delta>0 THEN quantity_delta ELSE 0 END),0) AS in_qty,
                            COALESCE(SUM(CASE WHEN quantity_delta<0 THEN -quantity_delta ELSE 0 END),0) AS out_qty,
                            COALESCE(SUM(CASE WHEN value_delta>0 THEN value_delta ELSE 0 END),0) AS in_value,
                            COALESCE(SUM(CASE WHEN value_delta<0 THEN -value_delta ELSE 0 END),0) AS out_value,
                            COALESCE(SUM(quantity_delta),0) AS net_qty,
                            COALESCE(SUM(value_delta),0) AS net_value
                        FROM inventory_movements WHERE {' AND '.join(period_where)}""",
                    p,
                ).fetchone()
                closing_qty = opening_qty + float(stats["net_qty"] or 0)
                closing_value = opening_value + float(stats["net_value"] or 0)
                if abs(closing_qty) <= EPSILON:
                    closing_qty = 0.0
                    closing_value = 0.0
                result.append({
                    **item,
                    "opening_quantity_period": opening_qty,
                    "opening_value": opening_value,
                    "purchases_quantity": float(stats["in_qty"] or 0),
                    "sales_quantity": float(stats["out_qty"] or 0),
                    "purchases_value": float(stats["in_value"] or 0),
                    "cogs_value": float(stats["out_value"] or 0),
                    "closing_quantity": closing_qty,
                    "closing_value": closing_value,
                    "closing_unit_cost": (closing_value / closing_qty) if closing_qty > EPSILON else 0.0,
                })
            return result

    def inventory_valuation(self, *, as_of: str | None = None) -> dict:
        _, as_of = self._normalize_dates(None, as_of)
        rows = self.inventory_report(date_to=as_of)
        return {
            "as_of": as_of,
            "rows": rows,
            "total_quantity": sum(float(r["closing_quantity"]) for r in rows),
            "total_value": sum(float(r["closing_value"]) for r in rows),
            "item_count": len(rows),
        }

    def party_balances(self, party_type: str, *, as_of: str | None = None) -> dict:
        _, as_of = self._normalize_dates(None, as_of)
        if party_type == "customer":
            table, account, sign, invoice_type, column = "customers", "AR", 1, "sale", "customer_id"
        elif party_type == "supplier":
            table, account, sign, invoice_type, column = "suppliers", "AP", -1, "purchase", "supplier_id"
        else:
            raise ValueError("نوع الحساب غير صحيح")
        with self.db.connect() as conn:
            parties = conn.execute(f"SELECT id,name,phone,address FROM {table} ORDER BY name").fetchall()
            result: list[dict] = []
            positive = 0.0
            credits = 0.0
            for p in parties:
                ledger_sql = "SELECT COALESCE(SUM(debit-credit),0) FROM ledger_entries WHERE party_type=? AND party_id=? AND account_code=?"
                params: list[object] = [party_type, p["id"], account]
                if as_of:
                    ledger_sql += " AND entry_date<=?"
                    params.append(as_of)
                raw_balance = float(conn.execute(ledger_sql, params).fetchone()[0])
                balance = raw_balance if sign == 1 else -raw_balance

                invoice_sql = f"SELECT COUNT(*) FROM invoices WHERE type=? AND {column}=?"
                ip: list[object] = [invoice_type, p["id"]]
                if as_of:
                    invoice_sql += " AND invoice_date<=?"
                    ip.append(as_of)
                invoice_count = int(conn.execute(invoice_sql, ip).fetchone()[0])

                if balance > EPSILON:
                    positive += balance
                elif balance < -EPSILON:
                    credits += -balance
                result.append({**dict(p), "balance": balance, "invoice_count": invoice_count})
            result.sort(key=lambda r: abs(float(r["balance"])), reverse=True)
            return {
                "party_type": party_type,
                "as_of": as_of,
                "rows": result,
                "positive_total": positive,
                "credit_total": credits,
                "net_total": positive - credits,
            }

    def outstanding_invoices(self, party_type: str, *, as_of: str | None = None) -> list[dict]:
        _, as_of = self._normalize_dates(None, as_of)
        if party_type == "customer":
            invoice_type, column, party_table = "sale", "customer_id", "customers"
        elif party_type == "supplier":
            invoice_type, column, party_table = "purchase", "supplier_id", "suppliers"
        else:
            raise ValueError("نوع الحساب غير صحيح")
        with self.db.connect() as conn:
            sql = f"""SELECT i.id,i.invoice_date,i.reference,i.total,p.name AS party_name,
                              COALESCE((SELECT SUM(pa.amount)
                                        FROM payment_allocations pa
                                        JOIN payments pay ON pay.id=pa.payment_id
                                        WHERE pa.invoice_id=i.id {{pay_date_filter}}),0) AS paid_as_of
                       FROM invoices i
                       JOIN {party_table} p ON p.id=i.{column}
                       WHERE i.type=? {{invoice_date_filter}}
                       ORDER BY i.invoice_date,i.id"""
            pay_filter = ""
            invoice_filter = ""
            params: list[object] = []
            if as_of:
                pay_filter = "AND pay.payment_date<=?"
                invoice_filter = "AND i.invoice_date<=?"
                params = [as_of, invoice_type, as_of]
            else:
                params = [invoice_type]
            rows = conn.execute(sql.format(pay_date_filter=pay_filter, invoice_date_filter=invoice_filter), params).fetchall()
            result = []
            for raw in rows:
                row = dict(raw)
                remaining = float(row["total"] or 0) - float(row["paid_as_of"] or 0)
                if remaining > EPSILON:
                    row["remaining_amount"] = remaining
                    result.append(row)
            return result

    def cash_movement(self, *, date_from: str | None = None, date_to: str | None = None) -> dict:
        date_from, date_to = self._normalize_dates(date_from, date_to)
        clause, params = self._date_clause("entry_date", date_from, date_to)
        with self.db.connect() as conn:
            opening = 0.0
            if date_from:
                opening = float(conn.execute(
                    "SELECT COALESCE(SUM(debit-credit),0) FROM ledger_entries WHERE account_code='CASH' AND entry_date<?",
                    (date_from,),
                ).fetchone()[0])
            rows = [dict(r) for r in conn.execute(
                f"""SELECT entry_date,debit,credit,source_type,source_id,description
                    FROM ledger_entries
                    WHERE account_code='CASH' AND {clause}
                    ORDER BY entry_date,id""",
                params,
            ).fetchall()]
            receipts = sum(float(r["debit"] or 0) for r in rows)
            payments = sum(float(r["credit"] or 0) for r in rows)
            running = opening
            for row in rows:
                running += float(row["debit"] or 0) - float(row["credit"] or 0)
                row["balance"] = running
            return {
                "date_from": date_from,
                "date_to": date_to,
                "opening_balance": opening,
                "receipts": receipts,
                "payments": payments,
                "net_movement": receipts - payments,
                "closing_balance": running,
                "rows": rows,
            }
