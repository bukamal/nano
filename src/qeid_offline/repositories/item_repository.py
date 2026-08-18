from __future__ import annotations

from qeid_offline.core.database import Database


class ItemRepository:
    def __init__(self, db: Database):
        self.db = db

    def list(self, search: str = "") -> list[dict]:
        sql = """
        SELECT i.*, c.name AS category_name, u.name AS unit_name, u.abbreviation AS unit_abbreviation
        FROM items i
        LEFT JOIN categories c ON c.id=i.category_id
        LEFT JOIN units u ON u.id=i.base_unit_id
        """
        params: tuple = ()
        if search.strip():
            sql += " WHERE i.name LIKE ?"
            params = (f"%{search.strip()}%",)
        sql += " ORDER BY i.name"
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get(self, item_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT i.*, c.name AS category_name, u.name AS unit_name, u.abbreviation AS unit_abbreviation
                   FROM items i
                   LEFT JOIN categories c ON c.id=i.category_id
                   LEFT JOIN units u ON u.id=i.base_unit_id
                   WHERE i.id=?""",
                (item_id,),
            ).fetchone()
            return dict(row) if row else None

    def units(self, item_id: int) -> list[dict]:
        """Return allowed invoice units with authoritative conversion factors."""
        with self.db.connect() as conn:
            item = conn.execute("SELECT base_unit_id FROM items WHERE id=?", (item_id,)).fetchone()
            if item is None:
                return []
            result: list[dict] = []
            base_id = item["base_unit_id"]
            if base_id is not None:
                u = conn.execute("SELECT * FROM units WHERE id=?", (base_id,)).fetchone()
                if u:
                    d = dict(u)
                    d["conversion_factor"] = 1.0
                    d["is_base"] = True
                    result.append(d)
            rows = conn.execute(
                """SELECT u.*, iu.conversion_factor
                   FROM item_units iu JOIN units u ON u.id=iu.unit_id
                   WHERE iu.item_id=? ORDER BY u.name""",
                (item_id,),
            ).fetchall()
            seen = {int(x["id"]) for x in result}
            for row in rows:
                if int(row["id"]) in seen:
                    continue
                d = dict(row)
                d["is_base"] = False
                result.append(d)
            return result

    def create(
        self,
        *,
        name: str,
        category_id: int | None = None,
        item_type: str = "مخزون",
        purchase_price: float = 0,
        selling_price: float = 0,
        quantity: float = 0,
        base_unit_id: int | None = None,
        item_units: list[dict] | None = None,
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("اسم المادة مطلوب")
        if item_type not in {"مخزون", "خدمة"}:
            raise ValueError("نوع المادة غير صحيح")
        initial_qty = 0.0 if item_type == "خدمة" else float(quantity or 0)
        avg = float(purchase_price or 0)
        if initial_qty < 0 or avg < 0 or float(selling_price or 0) < 0:
            raise ValueError("القيم المالية أو الكمية غير صحيحة")
        with self.db.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO items(
                       name,category_id,item_type,purchase_price,selling_price,quantity,average_cost,
                       opening_quantity,opening_unit_cost,base_unit_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    name, category_id, item_type, avg, float(selling_price or 0), initial_qty, avg,
                    initial_qty, avg if initial_qty else 0.0, base_unit_id,
                ),
            )
            item_id = int(cur.lastrowid)
            self._replace_units(conn, item_id, base_unit_id, item_units or [])
            if initial_qty:
                conn.execute(
                    """INSERT INTO inventory_movements(item_id,movement_type,quantity_delta,unit_cost,value_delta,movement_date)
                       VALUES(?,?,?,?,?,date('now'))""",
                    (item_id, "adjustment", initial_qty, avg, initial_qty * avg),
                )
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create','item',?,?)",
                (item_id, name),
            )
            return item_id

    def update(
        self,
        item_id: int,
        *,
        name: str,
        category_id: int | None = None,
        item_type: str = "مخزون",
        purchase_price: float = 0,
        selling_price: float = 0,
        base_unit_id: int | None = None,
        item_units: list[dict] | None = None,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("اسم المادة مطلوب")
        if item_type not in {"مخزون", "خدمة"}:
            raise ValueError("نوع المادة غير صحيح")
        with self.db.transaction() as conn:
            old = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if old is None:
                raise ValueError("المادة غير موجودة")
            if old["item_type"] != item_type:
                used = conn.execute("SELECT 1 FROM invoice_lines WHERE item_id=? LIMIT 1", (item_id,)).fetchone()
                if used:
                    raise ValueError("لا يمكن تغيير نوع المادة بعد استخدامها في فاتورة")
            conn.execute(
                """UPDATE items SET name=?,category_id=?,item_type=?,purchase_price=?,selling_price=?,base_unit_id=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (name, category_id, item_type, float(purchase_price or 0), float(selling_price or 0), base_unit_id, item_id),
            )
            self._replace_units(conn, item_id, base_unit_id, item_units or [])
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update','item',?,?)",
                (item_id, name),
            )

    @staticmethod
    def _replace_units(conn, item_id: int, base_unit_id: int | None, item_units: list[dict]) -> None:
        conn.execute("DELETE FROM item_units WHERE item_id=?", (item_id,))
        seen: set[int] = set()
        for raw in item_units:
            unit_id = int(raw["unit_id"])
            factor = float(raw.get("conversion_factor", 1))
            if factor <= 0:
                raise ValueError("معامل تحويل الوحدة يجب أن يكون أكبر من صفر")
            if base_unit_id is not None and int(base_unit_id) == unit_id:
                continue
            if unit_id in seen:
                continue
            seen.add(unit_id)
            conn.execute(
                "INSERT INTO item_units(item_id,unit_id,conversion_factor) VALUES(?,?,?)",
                (item_id, unit_id, factor),
            )
