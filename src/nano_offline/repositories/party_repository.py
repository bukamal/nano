from __future__ import annotations

from nano_offline.core.database import Database


class PartyRepository:
    def __init__(self, db: Database, table: str):
        if table not in {"customers", "suppliers"}:
            raise ValueError(table)
        self.db = db
        self.table = table

    def list(self, search: str = "") -> list[dict]:
        with self.db.connect() as conn:
            if search.strip():
                rows = conn.execute(
                    f"SELECT * FROM {self.table} WHERE name LIKE ? ORDER BY name",
                    (f"%{search.strip()}%",),
                ).fetchall()
            else:
                rows = conn.execute(f"SELECT * FROM {self.table} ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    def get(self, party_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(f"SELECT * FROM {self.table} WHERE id=?", (party_id,)).fetchone()
            return dict(row) if row else None

    def activity_summary(self, party_id: int) -> dict:
        party = self.get(party_id)
        if party is None:
            raise ValueError("الحساب غير موجود")
        id_column = "customer_id" if self.table == "customers" else "supplier_id"
        invoice_type = "sale" if self.table == "customers" else "purchase"
        with self.db.connect() as conn:
            stats = conn.execute(
                f"""SELECT COUNT(*) AS invoice_count, COALESCE(SUM(total),0) AS invoice_total,
                           COALESCE(SUM(paid_amount),0) AS paid_total,
                           COALESCE(SUM(MAX(total-paid_amount,0)),0) AS outstanding_total,
                           MAX(invoice_date) AS last_invoice_date
                    FROM invoices WHERE type=? AND {id_column}=? AND status='posted'""",
                (invoice_type, party_id),
            ).fetchone()
            recent = conn.execute(
                f"""SELECT id,type,invoice_date,reference,total,paid_amount,
                           MAX(total-paid_amount,0) AS remaining_amount
                    FROM invoices WHERE type=? AND {id_column}=? AND status='posted'
                    ORDER BY invoice_date DESC,id DESC LIMIT 8""",
                (invoice_type, party_id),
            ).fetchall()
        result = dict(party)
        result.update(dict(stats))
        result["recent_invoices"] = [dict(r) for r in recent]
        return result

    def create(self, name: str, phone: str | None = None, address: str | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("الاسم مطلوب")
        with self.db.transaction() as conn:
            try:
                cur = conn.execute(
                    f"INSERT INTO {self.table}(name,phone,address) VALUES(?,?,?)",
                    (name, phone or None, address or None),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ValueError("يوجد سجل بنفس الاسم") from exc
                raise
            party_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create',?,?,?)",
                (self.table[:-1], party_id, name),
            )
            return party_id

    def update(self, party_id: int, name: str, phone: str | None = None, address: str | None = None) -> None:
        name = name.strip()
        if not name:
            raise ValueError("الاسم مطلوب")
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE {self.table} SET name=?,phone=?,address=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, phone or None, address or None, party_id),
            )
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update',?,?,?)",
                (self.table[:-1], party_id, name),
            )

    def delete(self, party_id: int) -> None:
        with self.db.transaction() as conn:
            related = "customer_id" if self.table == "customers" else "supplier_id"
            invoice = conn.execute(f"SELECT 1 FROM invoices WHERE {related}=? LIMIT 1", (party_id,)).fetchone()
            payment = conn.execute(f"SELECT 1 FROM payments WHERE {related}=? LIMIT 1", (party_id,)).fetchone()
            if invoice or payment:
                raise ValueError("لا يمكن الحذف لوجود حركات مالية مرتبطة")
            conn.execute(f"DELETE FROM {self.table} WHERE id=?", (party_id,))
