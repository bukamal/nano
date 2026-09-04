from __future__ import annotations

from datetime import date

from qeid_offline.core.database import Database
from qeid_offline.services.accounting_rebuilder import AccountingRebuilder, EPSILON


class PaymentService:
    """Receipt/payment vouchers and invoice allocation service."""

    def __init__(self, db: Database):
        self.db = db

    def list_vouchers(self, limit: int = 300) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT v.*, c.name AS customer_name, s.name AS supplier_name,
                       p.id AS payment_id,
                       COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.payment_id=p.id),0) AS allocated_amount
                FROM vouchers v
                LEFT JOIN customers c ON c.id=v.customer_id
                LEFT JOIN suppliers s ON s.id=v.supplier_id
                LEFT JOIN payments p ON p.source_type='voucher' AND p.source_id=v.id
                ORDER BY v.voucher_date DESC, v.id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            result = [dict(r) for r in rows]
        for row in result:
            row["party_name"] = row.get("customer_name") or row.get("supplier_name") or "—"
            row["unallocated_amount"] = max(0.0, float(row["amount"]) - float(row["allocated_amount"] or 0))
        return result

    def get_voucher(self, voucher_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*, c.name AS customer_name, s.name AS supplier_name, p.id AS payment_id
                FROM vouchers v
                LEFT JOIN customers c ON c.id=v.customer_id
                LEFT JOIN suppliers s ON s.id=v.supplier_id
                LEFT JOIN payments p ON p.source_type='voucher' AND p.source_id=v.id
                WHERE v.id=?
                """,
                (voucher_id,),
            ).fetchone()
            if row is None:
                return None
            data = dict(row)
            data["party_name"] = data.get("customer_name") or data.get("supplier_name") or "—"
            if data.get("payment_id"):
                data["allocations"] = [
                    dict(r)
                    for r in conn.execute(
                        """
                        SELECT pa.*, i.invoice_date,i.reference,i.total,i.paid_amount,i.type
                        FROM payment_allocations pa
                        JOIN invoices i ON i.id=pa.invoice_id
                        WHERE pa.payment_id=?
                        ORDER BY i.invoice_date,i.id
                        """,
                        (data["payment_id"],),
                    ).fetchall()
                ]
            else:
                data["allocations"] = []
            data["allocated_amount"] = sum(float(a["amount"]) for a in data["allocations"])
            data["unallocated_amount"] = max(0.0, float(data["amount"]) - data["allocated_amount"])
            return data

    def create_voucher(
        self,
        *,
        voucher_type: str,
        amount: float,
        customer_id: int | None = None,
        supplier_id: int | None = None,
        voucher_date: str | None = None,
        reference: str | None = None,
        notes: str | None = None,
        allocation_mode: str = "oldest",
        allocations: dict[int, float] | None = None,
    ) -> int:
        with self.db.transaction() as conn:
            direction, customer_id, supplier_id = self._validate_party(
                conn, voucher_type, customer_id, supplier_id
            )
            amount_value = self._validate_amount(amount)
            vdate = (voucher_date or date.today().isoformat()).strip()
            cur = conn.execute(
                """INSERT INTO vouchers(
                       voucher_type,customer_id,supplier_id,voucher_date,amount,reference,notes
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    voucher_type, customer_id, supplier_id, vdate, amount_value,
                    (reference or "").strip() or None,
                    (notes or "").strip() or None,
                ),
            )
            voucher_id = int(cur.lastrowid)
            pcur = conn.execute(
                """INSERT INTO payments(
                       customer_id,supplier_id,direction,amount,payment_date,reference,notes,source_type,source_id
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    customer_id, supplier_id, direction, amount_value, vdate,
                    (reference or "").strip() or None,
                    self._payment_note(voucher_type, notes),
                    "voucher", voucher_id,
                ),
            )
            self._apply_allocations(
                conn,
                payment_id=int(pcur.lastrowid),
                voucher_type=voucher_type,
                party_id=int(customer_id or supplier_id),
                amount=amount_value,
                allocation_mode=allocation_mode,
                allocations=allocations,
            )
            AccountingRebuilder.rebuild(conn, inventory=False)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create','voucher',?,?)",
                (voucher_id, f"{voucher_type}:{amount_value}"),
            )
            return voucher_id

    def update_voucher(
        self,
        voucher_id: int,
        *,
        voucher_type: str,
        amount: float,
        customer_id: int | None = None,
        supplier_id: int | None = None,
        voucher_date: str | None = None,
        reference: str | None = None,
        notes: str | None = None,
        allocation_mode: str = "oldest",
        allocations: dict[int, float] | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            old = conn.execute("SELECT * FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
            if old is None:
                raise ValueError("السند غير موجود")
            direction, customer_id, supplier_id = self._validate_party(
                conn, voucher_type, customer_id, supplier_id
            )
            amount_value = self._validate_amount(amount)
            vdate = (voucher_date or str(old["voucher_date"])).strip()
            payment = conn.execute(
                "SELECT * FROM payments WHERE source_type='voucher' AND source_id=?",
                (voucher_id,),
            ).fetchone()
            if payment is None:
                raise ValueError("حركة السند المالية غير موجودة")

            conn.execute(
                """UPDATE vouchers
                   SET voucher_type=?,customer_id=?,supplier_id=?,voucher_date=?,amount=?,reference=?,notes=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    voucher_type, customer_id, supplier_id, vdate, amount_value,
                    (reference or "").strip() or None,
                    (notes or "").strip() or None,
                    voucher_id,
                ),
            )
            conn.execute(
                """UPDATE payments
                   SET customer_id=?,supplier_id=?,direction=?,amount=?,payment_date=?,reference=?,notes=?
                   WHERE id=?""",
                (
                    customer_id, supplier_id, direction, amount_value, vdate,
                    (reference or "").strip() or None,
                    self._payment_note(voucher_type, notes),
                    payment["id"],
                ),
            )
            conn.execute("DELETE FROM payment_allocations WHERE payment_id=?", (payment["id"],))
            self._apply_allocations(
                conn,
                payment_id=int(payment["id"]),
                voucher_type=voucher_type,
                party_id=int(customer_id or supplier_id),
                amount=amount_value,
                allocation_mode=allocation_mode,
                allocations=allocations,
            )
            AccountingRebuilder.rebuild(conn, inventory=False)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update','voucher',?,?)",
                (voucher_id, f"{old['voucher_type']}:{old['amount']} -> {voucher_type}:{amount_value}"),
            )

    def delete_voucher(self, voucher_id: int) -> None:
        with self.db.transaction() as conn:
            old = conn.execute("SELECT * FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
            if old is None:
                raise ValueError("السند غير موجود")
            conn.execute("DELETE FROM payments WHERE source_type='voucher' AND source_id=?", (voucher_id,))
            conn.execute("DELETE FROM vouchers WHERE id=?", (voucher_id,))
            AccountingRebuilder.rebuild(conn, inventory=False)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('delete','voucher',?,?)",
                (voucher_id, f"{old['voucher_type']}:{old['amount']}"),
            )

    def register_invoice_payment(
        self,
        invoice_id: int,
        amount: float,
        *,
        payment_date: str | None = None,
        reference: str | None = None,
        notes: str | None = None,
    ) -> int:
        with self.db.connect() as conn:
            inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if inv is None:
                raise ValueError("الفاتورة غير موجودة")
            if inv["type"] == "sale":
                if inv["customer_id"] is None:
                    raise ValueError("لا يمكن تسجيل دفعة لاحقة لفاتورة بيع بلا عميل")
                kwargs = {"voucher_type": "receipt", "customer_id": int(inv["customer_id"]), "supplier_id": None}
            else:
                if inv["supplier_id"] is None:
                    raise ValueError("لا يمكن تسجيل دفعة لاحقة لفاتورة شراء بلا مورد")
                kwargs = {"voucher_type": "payment", "supplier_id": int(inv["supplier_id"]), "customer_id": None}
        return self.create_voucher(
            amount=amount,
            voucher_date=payment_date,
            reference=reference,
            notes=notes,
            allocation_mode="manual",
            allocations={invoice_id: float(amount)},
            **kwargs,
        )

    def open_invoices(self, party_type: str, party_id: int) -> list[dict]:
        if party_type not in {"customer", "supplier"}:
            raise ValueError("نوع الحساب غير صحيح")
        invoice_type = "sale" if party_type == "customer" else "purchase"
        column = "customer_id" if party_type == "customer" else "supplier_id"
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT i.id,i.invoice_date,i.reference,i.total,i.paid_amount,
                           (i.total-i.paid_amount) AS remaining_amount
                    FROM invoices i
                    WHERE i.type=? AND i.{column}=? AND i.total-i.paid_amount>?
                    ORDER BY i.invoice_date,i.id""",
                (invoice_type, party_id, EPSILON),
            ).fetchall()
            return [dict(r) for r in rows]


    def allocatable_invoices(self, party_type: str, party_id: int, *, exclude_payment_id: int | None = None) -> list[dict]:
        """Invoices with allocatable remaining, optionally ignoring one payment's current allocations."""
        if party_type not in {"customer", "supplier"}:
            raise ValueError("نوع الحساب غير صحيح")
        invoice_type = "sale" if party_type == "customer" else "purchase"
        column = "customer_id" if party_type == "customer" else "supplier_id"
        with self.db.connect() as conn:
            if exclude_payment_id is None:
                allocation_expr = "COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.invoice_id=i.id),0)"
                params: list[object] = [invoice_type, party_id, EPSILON]
            else:
                allocation_expr = "COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.invoice_id=i.id AND pa.payment_id<>?),0)"
                # allocation_expr appears twice in SQL.
                params = [exclude_payment_id, invoice_type, party_id, exclude_payment_id, EPSILON]
            rows = conn.execute(
                f"""SELECT i.id,i.invoice_date,i.reference,i.total,i.paid_amount,
                           (i.total-{allocation_expr}) AS allocatable_amount
                    FROM invoices i
                    WHERE i.type=? AND i.{column}=?
                      AND (i.total-{allocation_expr})>?
                    ORDER BY i.invoice_date,i.id""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _validate_amount(amount: float) -> float:
        value = float(amount or 0)
        if value <= EPSILON:
            raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
        return value

    @staticmethod
    def _validate_party(conn, voucher_type: str, customer_id: int | None, supplier_id: int | None):
        if voucher_type == "receipt":
            if customer_id is None or supplier_id is not None:
                raise ValueError("سند القبض يجب أن يرتبط بعميل")
            if conn.execute("SELECT 1 FROM customers WHERE id=?", (customer_id,)).fetchone() is None:
                raise ValueError("العميل غير موجود")
            return "in", customer_id, None
        if voucher_type == "payment":
            if supplier_id is None or customer_id is not None:
                raise ValueError("سند الصرف يجب أن يرتبط بمورد")
            if conn.execute("SELECT 1 FROM suppliers WHERE id=?", (supplier_id,)).fetchone() is None:
                raise ValueError("المورد غير موجود")
            return "out", None, supplier_id
        raise ValueError("نوع السند غير صحيح")

    @staticmethod
    def _payment_note(voucher_type: str, notes: str | None) -> str:
        prefix = "سند قبض" if voucher_type == "receipt" else "سند صرف"
        clean = (notes or "").strip()
        return f"{prefix} — {clean}" if clean else prefix

    def _apply_allocations(
        self,
        conn,
        *,
        payment_id: int,
        voucher_type: str,
        party_id: int,
        amount: float,
        allocation_mode: str,
        allocations: dict[int, float] | None,
    ) -> None:
        mode = (allocation_mode or "oldest").strip().lower()
        if mode == "none":
            return
        if mode == "manual":
            manual = allocations or {}
            if not manual:
                return
            used = 0.0
            for invoice_id, raw_amount in manual.items():
                alloc = float(raw_amount or 0)
                if alloc <= EPSILON:
                    continue
                remaining = self._invoice_remaining_for_allocation(
                    conn, int(invoice_id), voucher_type, party_id
                )
                if alloc > remaining + EPSILON:
                    raise ValueError(
                        f"المبلغ الموزع على الفاتورة #{invoice_id} يتجاوز المتبقي {remaining:.2f}"
                    )
                used += alloc
                if used > amount + EPSILON:
                    raise ValueError("إجمالي التوزيع يتجاوز قيمة السند")
                conn.execute(
                    "INSERT INTO payment_allocations(payment_id,invoice_id,amount) VALUES(?,?,?)",
                    (payment_id, int(invoice_id), alloc),
                )
            return
        if mode != "oldest":
            raise ValueError("طريقة توزيع الدفعة غير صحيحة")

        invoice_type = "sale" if voucher_type == "receipt" else "purchase"
        column = "customer_id" if voucher_type == "receipt" else "supplier_id"
        rows = conn.execute(
            f"""SELECT i.id,i.total,
                       COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.invoice_id=i.id),0) AS allocated
                FROM invoices i
                WHERE i.type=? AND i.{column}=?
                ORDER BY i.invoice_date,i.created_at,i.id""",
            (invoice_type, party_id),
        ).fetchall()
        left = amount
        for inv in rows:
            remaining = max(0.0, float(inv["total"]) - float(inv["allocated"] or 0))
            if remaining <= EPSILON:
                continue
            alloc = min(left, remaining)
            conn.execute(
                "INSERT INTO payment_allocations(payment_id,invoice_id,amount) VALUES(?,?,?)",
                (payment_id, inv["id"], alloc),
            )
            left -= alloc
            if left <= EPSILON:
                break

    @staticmethod
    def _invoice_remaining_for_allocation(conn, invoice_id: int, voucher_type: str, party_id: int) -> float:
        row = conn.execute(
            """SELECT i.*,
                      COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.invoice_id=i.id),0) AS allocated
               FROM invoices i WHERE i.id=?""",
            (invoice_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"الفاتورة #{invoice_id} غير موجودة")
        if voucher_type == "receipt":
            if row["type"] != "sale" or row["customer_id"] != party_id:
                raise ValueError(f"الفاتورة #{invoice_id} لا تخص العميل المحدد")
        else:
            if row["type"] != "purchase" or row["supplier_id"] != party_id:
                raise ValueError(f"الفاتورة #{invoice_id} لا تخص المورد المحدد")
        return max(0.0, float(row["total"]) - float(row["allocated"] or 0))
