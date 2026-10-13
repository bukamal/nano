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
            "day_close": "تسوية",
        }.get(str(source_type), str(source_type))

    # General-ledger account registry: every account_code the rebuilder and
    # services post into, with its Arabic label and normal-balance nature
    # (which side a positive balance sits on). Unknown future codes fall
    # back to a debit nature and their raw code as label -- trial_balance()
    # and account_statement() never crash on them.
    ACCOUNT_LABELS: dict[str, tuple[str, str]] = {
        "CASH": ("الصندوق", "debit"),
        "AR": ("العملاء", "debit"),
        "AP": ("الموردون", "credit"),
        "SALES": ("المبيعات", "credit"),
        "PURCHASES": ("المشتريات", "debit"),
        "COGS": ("تكلفة البضاعة", "debit"),
        "INVENTORY": ("المخزون", "debit"),
        "EXPENSE": ("المصروفات", "debit"),
    }

    @classmethod
    def account_info(cls, code: str) -> tuple[str, str]:
        return cls.ACCOUNT_LABELS.get(str(code), (str(code), "debit"))

    def trial_balance(self) -> dict:
        """Trial balance over all ledger postings.

        One row per known account (zero rows included, as a real trial
        balance lists every account), each with its debit/credit totals and
        its balance on the account's normal side, plus grand totals and a
        balanced flag. NOTE: day-close adjustments post single-sided CASH
        lines, so a posted adjustment shows here honestly as a difference
        instead of being silently absorbed.
        """
        with self.db.connect() as conn:
            sums = {
                str(r["account_code"]): (float(r["d"] or 0), float(r["c"] or 0))
                for r in conn.execute(
                    "SELECT account_code, COALESCE(SUM(debit),0) AS d, COALESCE(SUM(credit),0) AS c"
                    " FROM ledger_entries GROUP BY account_code"
                ).fetchall()
            }
            known = [r["account_code"] for r in conn.execute(
                "SELECT DISTINCT account_code FROM ledger_entries"
            ).fetchall()]
            codes = list(self.ACCOUNT_LABELS) + [c for c in known if c not in self.ACCOUNT_LABELS]
            accounts = []
            total_debit = 0.0
            total_credit = 0.0
            for code in codes:
                d, c = sums.get(str(code), (0.0, 0.0))
                label, nature = self.account_info(code)
                balance = (d - c) if nature == "debit" else (c - d)
                accounts.append({
                    "code": code, "label": label, "nature": nature,
                    "debit": d, "credit": c, "balance": balance,
                })
                total_debit += d
                total_credit += c
            return {
                "accounts": accounts,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "difference": total_debit - total_credit,
                "balanced": abs(total_debit - total_credit) <= 1e-6,
            }

    def account_statement(
        self,
        account_code: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Chronological statement for one GL account, same shape as
        party_statement: opening balance, ordered movements with running
        balances, debit/credit totals, and source labels -- except party
        names are resolved per row (a CASH or SALES movement usually has
        no party at all)."""
        code = str(account_code)
        _, nature = self.account_info(code)
        sign = 1 if nature == "debit" else -1

        def _signed(debit: float, credit: float) -> float:
            return (debit - credit) if sign == 1 else (credit - debit)

        with self.db.connect() as conn:
            params: list[object] = [code]
            before_sql = "SELECT COALESCE(SUM(debit-credit),0) FROM ledger_entries WHERE account_code=?"
            if date_from:
                before_sql += " AND entry_date<?"
                params.append(date_from)
            else:
                before_sql += " AND 1=0"
            raw_opening = float(conn.execute(before_sql, params).fetchone()[0])
            opening = raw_opening if sign == 1 else -raw_opening
            sql = """SELECT le.id,le.entry_date,le.account_code,le.debit,le.credit,
                            le.source_type,le.source_id,le.description,le.created_at,
                            le.party_type,le.party_id,
                            COALESCE(c.name, s.name) AS party_name
                     FROM ledger_entries le
                     LEFT JOIN customers c ON le.party_type='customer' AND c.id=le.party_id
                     LEFT JOIN suppliers s ON le.party_type='supplier' AND s.id=le.party_id
                     WHERE le.account_code=?"""
            row_params: list[object] = [code]
            if date_from:
                sql += " AND le.entry_date>=?"
                row_params.append(date_from)
            if date_to:
                sql += " AND le.entry_date<=?"
                row_params.append(date_to)
            sql += " ORDER BY le.entry_date,le.id"
            running = opening
            rows: list[dict] = []
            debit_total = 0.0
            credit_total = 0.0
            for raw in conn.execute(sql, row_params).fetchall():
                row = dict(raw)
                debit = float(row["debit"] or 0)
                credit = float(row["credit"] or 0)
                movement = _signed(debit, credit)
                running += movement
                debit_total += debit
                credit_total += credit
                row["movement"] = movement
                row["balance"] = running
                row["source_label"] = self._source_label(row["source_type"])
                rows.append(row)
            return {
                "code": code,
                "label": self.account_info(code)[0],
                "nature": nature,
                "opening_balance": opening,
                "rows": rows,
                "debit_total": debit_total,
                "credit_total": credit_total,
                "closing_balance": running,
            }
