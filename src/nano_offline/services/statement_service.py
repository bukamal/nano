from __future__ import annotations

from nano_offline.core.database import Database


class StatementService:
    def __init__(self, db: Database):
        self.db = db

    def party_statement(
        self,
        party_type: str,
        party_id: int,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        table, account, sign = self._party_contract(party_type)
        with self.db.connect() as conn:
            party = conn.execute(f"SELECT * FROM {table} WHERE id=?", (party_id,)).fetchone()
            if party is None:
                raise ValueError("الحساب غير موجود")

            before_sql = "SELECT COALESCE(SUM(debit-credit),0) FROM ledger_entries WHERE party_type=? AND party_id=? AND account_code=?"
            params: list[object] = [party_type, party_id, account]
            if date_from:
                before_sql += " AND entry_date<?"
                params.append(date_from)
            else:
                before_sql += " AND 1=0"
            raw_opening = float(conn.execute(before_sql, params).fetchone()[0])
            opening = raw_opening if sign == 1 else -raw_opening

            sql = """SELECT id,entry_date,account_code,debit,credit,source_type,source_id,description,created_at
                     FROM ledger_entries
                     WHERE party_type=? AND party_id=? AND account_code=?"""
            row_params: list[object] = [party_type, party_id, account]
            if date_from:
                sql += " AND entry_date>=?"
                row_params.append(date_from)
            if date_to:
                sql += " AND entry_date<=?"
                row_params.append(date_to)
            sql += " ORDER BY entry_date,id"
            ledger_rows = conn.execute(sql, row_params).fetchall()

            running = opening
            rows: list[dict] = []
            debit_total = 0.0
            credit_total = 0.0
            for raw in ledger_rows:
                row = dict(raw)
                debit = float(row["debit"] or 0)
                credit = float(row["credit"] or 0)
                movement = (debit - credit) if sign == 1 else (credit - debit)
                running += movement
                debit_total += debit
                credit_total += credit
                row["movement"] = movement
                row["balance"] = running
                row["source_label"] = self._source_label(row["source_type"])
                rows.append(row)

            invoice_type = "sale" if party_type == "customer" else "purchase"
            column = "customer_id" if party_type == "customer" else "supplier_id"
            open_invoices = [
                dict(r)
                for r in conn.execute(
                    f"""SELECT id,invoice_date,reference,total,paid_amount,(total-paid_amount) AS remaining_amount
                        FROM invoices
                        WHERE type=? AND {column}=? AND total-paid_amount>1e-9
                        ORDER BY invoice_date,id""",
                    (invoice_type, party_id),
                ).fetchall()
            ]

            current_balance = float(party["balance"] or 0)
            return {
                "party": dict(party),
                "party_type": party_type,
                "opening_balance": opening,
                "rows": rows,
                "debit_total": debit_total,
                "credit_total": credit_total,
                "closing_balance": running,
                "current_balance": current_balance,
                "open_invoices": open_invoices,
                "credit_balance": abs(current_balance) if current_balance < 0 else 0.0,
            }

    def parties_summary(self, party_type: str) -> list[dict]:
        table, _, _ = self._party_contract(party_type)
        invoice_type = "sale" if party_type == "customer" else "purchase"
        column = "customer_id" if party_type == "customer" else "supplier_id"
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT p.*,
                           (SELECT COUNT(*) FROM invoices i WHERE i.type=? AND i.{column}=p.id) AS invoice_count,
                           (SELECT COUNT(*) FROM invoices i WHERE i.type=? AND i.{column}=p.id AND i.total-i.paid_amount>1e-9) AS open_invoice_count
                    FROM {table} p
                    ORDER BY ABS(p.balance) DESC,p.name""",
                (invoice_type, invoice_type),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _party_contract(party_type: str) -> tuple[str, str, int]:
        if party_type == "customer":
            return "customers", "AR", 1
        if party_type == "supplier":
            # Supplier business balance is liability: credit increases it.
            return "suppliers", "AP", -1
        raise ValueError("نوع الحساب غير صحيح")

    @staticmethod
    def _source_label(source_type: str) -> str:
        return {
            "invoice": "فاتورة",
            "payment": "دفعة",
            "expense": "مصروف",
        }.get(str(source_type), str(source_type))
