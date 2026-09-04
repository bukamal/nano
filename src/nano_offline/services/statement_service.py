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

            # Historical rate/currency for this specific movement -- pulled from
            # whichever source document produced it, so each row can be printed
            # at the rate that actually applied when it happened (invoices and
            # payments/vouchers each carry their own snapshot; see
            # invoice_exchange_rate / payment_exchange_rate).
            sql = """SELECT le.id,le.entry_date,le.account_code,le.debit,le.credit,
                            le.source_type,le.source_id,le.description,le.created_at,
                            CASE le.source_type
                                WHEN 'invoice' THEN i.invoice_exchange_rate
                                WHEN 'payment' THEN p.payment_exchange_rate
                            END AS movement_exchange_rate,
                            CASE le.source_type
                                WHEN 'invoice' THEN i.invoice_currency_code
                                WHEN 'payment' THEN p.payment_currency_code
                            END AS movement_currency_code,
                            CASE le.source_type
                                WHEN 'invoice' THEN i.invoice_currency_symbol
                                WHEN 'payment' THEN p.payment_currency_symbol
                            END AS movement_currency_symbol
                     FROM ledger_entries le
                     LEFT JOIN invoices i ON le.source_type='invoice' AND i.id=le.source_id
                     LEFT JOIN payments p ON le.source_type='payment' AND p.id=le.source_id
                     WHERE le.party_type=? AND le.party_id=? AND le.account_code=?"""
            row_params: list[object] = [party_type, party_id, account]
            if date_from:
                sql += " AND le.entry_date>=?"
                row_params.append(date_from)
            if date_to:
                sql += " AND le.entry_date<=?"
                row_params.append(date_to)
            sql += " ORDER BY le.entry_date,le.id"
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
