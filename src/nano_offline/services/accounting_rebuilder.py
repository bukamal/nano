from __future__ import annotations

EPSILON = 1e-9


class AccountingRebuilder:
    """Rebuild deterministic derived accounting/inventory state.

    Source documents are invoices, vouchers/payments, allocations, expenses and
    explicit opening inventory. Party balances, invoice paid amounts, invoice
    COGS, invoice inventory movements and invoice/payment ledger entries are
    derived state and may be rebuilt safely inside the caller transaction.
    """

    @classmethod
    def rebuild(cls, conn, *, inventory: bool = True) -> None:
        if inventory:
            cls.rebuild_inventory(conn)
        cls.rebuild_financials(conn)

    @staticmethod
    def rebuild_inventory(conn) -> None:
        conn.execute("DELETE FROM inventory_movements WHERE invoice_id IS NOT NULL")
        conn.execute("""UPDATE invoice_lines SET unit_cost=0,cost_amount=0
                       WHERE item_id IN (SELECT id FROM items WHERE item_type='مخزون')""")

        state: dict[int, dict[str, float]] = {}
        for item in conn.execute(
            "SELECT id,opening_quantity,opening_unit_cost FROM items WHERE item_type='مخزون'"
        ).fetchall():
            qty = float(item["opening_quantity"] or 0)
            avg = float(item["opening_unit_cost"] or 0) if qty > EPSILON else 0.0
            state[int(item["id"])] = {"qty": qty, "avg": avg}
            conn.execute(
                "UPDATE items SET quantity=?,average_cost=?,purchase_price=CASE WHEN ? > 0 THEN ? ELSE purchase_price END WHERE id=?",
                (qty, avg, qty, avg, item["id"]),
            )

        def get_state(item_id: int) -> dict[str, float]:
            if item_id not in state:
                state[item_id] = {"qty": 0.0, "avg": 0.0}
            return state[item_id]

        rows = conn.execute(
            """
            SELECT il.*, inv.type AS invoice_type, inv.invoice_date,
                   inv.created_at AS invoice_created_at,
                   it.name AS item_name, it.item_type
            FROM invoice_lines il
            JOIN invoices inv ON inv.id=il.invoice_id
            LEFT JOIN items it ON it.id=il.item_id
            WHERE il.item_id IS NOT NULL AND it.item_type='مخزون'
            ORDER BY inv.invoice_date, inv.created_at, inv.id, il.id
            """
        ).fetchall()

        for raw in rows:
            row = dict(raw)
            item_id = int(row["item_id"])
            st = get_state(item_id)
            base_qty = float(row["quantity_in_base"])
            line_total = float(row["total"])
            if row["invoice_type"] == "purchase":
                unit_cost = line_total / base_qty if base_qty else 0.0
                new_qty = st["qty"] + base_qty
                st["avg"] = ((st["qty"] * st["avg"]) + line_total) / new_qty if new_qty else unit_cost
                st["qty"] = new_qty
                conn.execute(
                    "UPDATE invoice_lines SET unit_cost=?,cost_amount=0 WHERE id=?",
                    (unit_cost, row["id"]),
                )
                conn.execute(
                    """INSERT INTO inventory_movements(
                           item_id,invoice_id,movement_type,quantity_delta,unit_cost,value_delta,movement_date
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (item_id, row["invoice_id"], "purchase", base_qty, unit_cost, line_total, row["invoice_date"]),
                )
                conn.execute("UPDATE items SET purchase_price=? WHERE id=?", (unit_cost, item_id))
            else:
                if st["qty"] + EPSILON < base_qty:
                    raise ValueError(
                        f"المخزون غير كافٍ للمادة: {row['item_name']} — المتاح {st['qty']:.3f} والمطلوب {base_qty:.3f}"
                    )
                unit_cost = st["avg"]
                cost_amount = unit_cost * base_qty
                st["qty"] -= base_qty
                if st["qty"] <= EPSILON:
                    st["qty"] = 0.0
                conn.execute(
                    "UPDATE invoice_lines SET unit_cost=?,cost_amount=? WHERE id=?",
                    (unit_cost, cost_amount, row["id"]),
                )
                conn.execute(
                    """INSERT INTO inventory_movements(
                           item_id,invoice_id,movement_type,quantity_delta,unit_cost,value_delta,movement_date
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (item_id, row["invoice_id"], "sale", -base_qty, unit_cost, -cost_amount, row["invoice_date"]),
                )

        for item in conn.execute("SELECT id FROM items WHERE item_type='مخزون'").fetchall():
            st = state.get(int(item["id"]), {"qty": 0.0, "avg": 0.0})
            conn.execute(
                "UPDATE items SET quantity=?,average_cost=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (st["qty"], st["avg"], item["id"]),
            )

    @classmethod
    def rebuild_financials(cls, conn) -> None:
        cls._sync_initial_invoice_payments(conn)
        cls._validate_allocations(conn)
        cls._refresh_invoice_paid_amounts(conn)
        cls._rebuild_ledger_and_party_balances(conn)

    @staticmethod
    def _sync_initial_invoice_payments(conn) -> None:
        # Initial payments are source-document fields on invoices. Regenerate
        # their cash rows and allocations deterministically on every rebuild.
        conn.execute("DELETE FROM payments WHERE source_type='invoice_initial'")

        invoices = conn.execute(
            "SELECT * FROM invoices ORDER BY invoice_date, created_at, id"
        ).fetchall()
        for inv in invoices:
            initial = float(inv["initial_paid_amount"] or 0)
            total = float(inv["total"] or 0)
            if initial < -EPSILON or initial > total + EPSILON:
                raise ValueError(f"الدفعة الأولى غير صالحة للفاتورة #{inv['id']}")
            if initial <= EPSILON:
                continue
            direction = "in" if inv["type"] == "sale" else "out"
            # This payment is a derived reflection of the invoice's own initial
            # payment, not a separate real-world event -- so it inherits the
            # invoice's historical rate snapshot rather than stamping "now".
            cur = conn.execute(
                """INSERT INTO payments(
                       invoice_id,customer_id,supplier_id,direction,amount,payment_date,
                       reference,notes,source_type,source_id,
                       payment_exchange_rate,payment_currency_code,payment_currency_symbol
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    inv["id"],
                    inv["customer_id"],
                    inv["supplier_id"],
                    direction,
                    initial,
                    inv["invoice_date"],
                    inv["reference"],
                    "دفعة أولى من الفاتورة",
                    "invoice_initial",
                    inv["id"],
                    inv["invoice_exchange_rate"],
                    inv["invoice_currency_code"],
                    inv["invoice_currency_symbol"],
                ),
            )
            conn.execute(
                "INSERT INTO payment_allocations(payment_id,invoice_id,amount) VALUES(?,?,?)",
                (int(cur.lastrowid), inv["id"], initial),
            )

    @staticmethod
    def _validate_allocations(conn) -> None:
        payment_sums = {
            int(r["payment_id"]): float(r["allocated"] or 0)
            for r in conn.execute(
                "SELECT payment_id,SUM(amount) AS allocated FROM payment_allocations GROUP BY payment_id"
            ).fetchall()
        }
        for p in conn.execute("SELECT * FROM payments").fetchall():
            allocated = payment_sums.get(int(p["id"]), 0.0)
            if allocated > float(p["amount"]) + EPSILON:
                raise ValueError(f"توزيع الدفعة #{p['id']} يتجاوز قيمة الدفعة")

        invoice_sums = {
            int(r["invoice_id"]): float(r["allocated"] or 0)
            for r in conn.execute(
                "SELECT invoice_id,SUM(amount) AS allocated FROM payment_allocations GROUP BY invoice_id"
            ).fetchall()
        }
        for inv in conn.execute("SELECT * FROM invoices").fetchall():
            allocated = invoice_sums.get(int(inv["id"]), 0.0)
            if allocated > float(inv["total"]) + EPSILON:
                raise ValueError(
                    f"الدفعات الموزعة على الفاتورة #{inv['id']} تتجاوز إجمالي الفاتورة؛ عدّل السندات المرتبطة أولًا"
                )

        rows = conn.execute(
            """
            SELECT pa.id, p.direction,p.customer_id AS p_customer,p.supplier_id AS p_supplier,
                   i.type,i.customer_id AS i_customer,i.supplier_id AS i_supplier
            FROM payment_allocations pa
            JOIN payments p ON p.id=pa.payment_id
            JOIN invoices i ON i.id=pa.invoice_id
            """
        ).fetchall()
        for row in rows:
            if row["direction"] == "in":
                if row["type"] != "sale":
                    raise ValueError("لا يمكن توزيع سند قبض على فاتورة شراء")
                if row["p_customer"] is not None and row["i_customer"] != row["p_customer"]:
                    raise ValueError("سند القبض مرتبط بعميل مختلف عن الفاتورة")
            else:
                if row["type"] != "purchase":
                    raise ValueError("لا يمكن توزيع سند صرف على فاتورة بيع")
                if row["p_supplier"] is not None and row["i_supplier"] != row["p_supplier"]:
                    raise ValueError("سند الصرف مرتبط بمورد مختلف عن الفاتورة")

    @staticmethod
    def _refresh_invoice_paid_amounts(conn) -> None:
        conn.execute(
            """UPDATE invoices
               SET paid_amount=COALESCE((
                   SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.invoice_id=invoices.id
               ),0)"""
        )

    @classmethod
    def _rebuild_ledger_and_party_balances(cls, conn) -> None:
        conn.execute("DELETE FROM ledger_entries WHERE source_type IN ('invoice','payment')")
        conn.execute("UPDATE customers SET balance=0,updated_at=CURRENT_TIMESTAMP")
        conn.execute("UPDATE suppliers SET balance=0,updated_at=CURRENT_TIMESTAMP")

        invoices = conn.execute(
            "SELECT * FROM invoices ORDER BY invoice_date, created_at, id"
        ).fetchall()
        for inv in invoices:
            invoice_id = int(inv["id"])
            total = float(inv["total"])
            if inv["type"] == "sale":
                conn.execute(
                    """INSERT INTO ledger_entries(
                           entry_date,account_code,party_type,party_id,debit,source_type,source_id,description
                       ) VALUES(?,?,?,?,?,'invoice',?,?)""",
                    (
                        inv["invoice_date"], "AR",
                        "customer" if inv["customer_id"] else None,
                        inv["customer_id"], total, invoice_id, "فاتورة بيع",
                    ),
                )
                conn.execute(
                    "INSERT INTO ledger_entries(entry_date,account_code,credit,source_type,source_id,description) VALUES(?,?,?,'invoice',?,?)",
                    (inv["invoice_date"], "SALES", total, invoice_id, "إيراد مبيعات"),
                )
                cogs = float(conn.execute(
                    "SELECT COALESCE(SUM(cost_amount),0) FROM invoice_lines WHERE invoice_id=?",
                    (invoice_id,),
                ).fetchone()[0])
                if cogs > EPSILON:
                    conn.execute(
                        "INSERT INTO ledger_entries(entry_date,account_code,debit,source_type,source_id,description) VALUES(?,?,?,'invoice',?,?)",
                        (inv["invoice_date"], "COGS", cogs, invoice_id, "تكلفة بضاعة مباعة"),
                    )
                    conn.execute(
                        "INSERT INTO ledger_entries(entry_date,account_code,credit,source_type,source_id,description) VALUES(?,?,?,'invoice',?,?)",
                        (inv["invoice_date"], "INVENTORY", cogs, invoice_id, "انخفاض مخزون"),
                    )
                if inv["customer_id"]:
                    conn.execute("UPDATE customers SET balance=balance+? WHERE id=?", (total, inv["customer_id"]))
            else:
                conn.execute(
                    "INSERT INTO ledger_entries(entry_date,account_code,debit,source_type,source_id,description) VALUES(?,?,?,'invoice',?,?)",
                    (inv["invoice_date"], "PURCHASES", total, invoice_id, "فاتورة شراء"),
                )
                conn.execute(
                    """INSERT INTO ledger_entries(
                           entry_date,account_code,party_type,party_id,credit,source_type,source_id,description
                       ) VALUES(?,?,?,?,?,'invoice',?,?)""",
                    (
                        inv["invoice_date"], "AP",
                        "supplier" if inv["supplier_id"] else None,
                        inv["supplier_id"], total, invoice_id, "التزام مورد",
                    ),
                )
                if inv["supplier_id"]:
                    conn.execute("UPDATE suppliers SET balance=balance+? WHERE id=?", (total, inv["supplier_id"]))

        for p in conn.execute("SELECT * FROM payments ORDER BY payment_date, created_at, id").fetchall():
            amount = float(p["amount"])
            cls._write_payment_ledger(
                conn, int(p["id"]), str(p["direction"]), amount,
                str(p["payment_date"]), p["customer_id"], p["supplier_id"],
                str(p["notes"] or ""),
            )
            if p["direction"] == "in" and p["customer_id"]:
                conn.execute("UPDATE customers SET balance=balance-? WHERE id=?", (amount, p["customer_id"]))
            elif p["direction"] == "out" and p["supplier_id"]:
                conn.execute("UPDATE suppliers SET balance=balance-? WHERE id=?", (amount, p["supplier_id"]))

    @staticmethod
    def _write_payment_ledger(
        conn,
        payment_id: int,
        direction: str,
        amount: float,
        payment_date: str,
        customer_id: int | None,
        supplier_id: int | None,
        notes: str = "",
    ) -> None:
        if direction == "in":
            conn.execute(
                "INSERT INTO ledger_entries(entry_date,account_code,debit,source_type,source_id,description) VALUES(?,?,?,'payment',?,?)",
                (payment_date, "CASH", amount, payment_id, notes or "قبض نقدي"),
            )
            conn.execute(
                """INSERT INTO ledger_entries(
                       entry_date,account_code,party_type,party_id,credit,source_type,source_id,description
                   ) VALUES(?,?,?,?,?,'payment',?,?)""",
                (
                    payment_date, "AR", "customer" if customer_id else None,
                    customer_id, amount, payment_id, notes or "تسديد عميل",
                ),
            )
        else:
            conn.execute(
                """INSERT INTO ledger_entries(
                       entry_date,account_code,party_type,party_id,debit,source_type,source_id,description
                   ) VALUES(?,?,?,?,?,'payment',?,?)""",
                (
                    payment_date, "AP", "supplier" if supplier_id else None,
                    supplier_id, amount, payment_id, notes or "تسديد مورد",
                ),
            )
            conn.execute(
                "INSERT INTO ledger_entries(entry_date,account_code,credit,source_type,source_id,description) VALUES(?,?,?,'payment',?,?)",
                (payment_date, "CASH", amount, payment_id, notes or "صرف نقدي"),
            )
