from __future__ import annotations

from nano_offline.core.database import Database


class DefinitionsRepository:
    def __init__(self, db: Database):
        self.db = db

    def list_categories(self) -> list[dict]:
        """Categories with a live count of items referencing each one.

        The count powers the UI badge ("٤ مواد") and lets the caller decide
        whether to offer a delete affordance at all, without a second
        round-trip per row.
        """
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, (SELECT COUNT(*) FROM items i WHERE i.category_id = c.id) AS item_count
                FROM categories c ORDER BY c.name
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def create_category(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("اسم التصنيف مطلوب")
        with self.db.transaction() as conn:
            category_id = int(conn.execute("INSERT INTO categories(name) VALUES(?)", (name,)).lastrowid)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create','category',?,?)",
                (category_id, name),
            )
            return category_id

    def rename_category(self, category_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("اسم التصنيف مطلوب")
        with self.db.transaction() as conn:
            conn.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update','category',?,?)",
                (category_id, name),
            )

    def delete_category(self, category_id: int) -> None:
        # Checked explicitly (same convention as PartyRepository.delete)
        # rather than relying on the schema's ON DELETE RESTRICT alone, so
        # the person gets a clear Arabic message instead of a raw sqlite
        # IntegrityError bubbling up from a foreign-key violation.
        with self.db.transaction() as conn:
            in_use = conn.execute("SELECT 1 FROM items WHERE category_id=? LIMIT 1", (category_id,)).fetchone()
            if in_use:
                raise ValueError("لا يمكن حذف التصنيف لوجود مواد مرتبطة به")
            conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('delete','category',?,NULL)",
                (category_id,),
            )

    def list_units(self) -> list[dict]:
        """Units with a live count of items that reference each one — either
        as their base unit, or as one of their alternate/conversion units
        (``item_units``). Both must be checked before a unit can be safely
        offered for deletion.
        """
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT u.*,
                    (SELECT COUNT(*) FROM items i WHERE i.base_unit_id = u.id) +
                    (SELECT COUNT(*) FROM item_units iu WHERE iu.unit_id = u.id) AS item_count
                FROM units u ORDER BY u.name
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def create_unit(self, name: str, abbreviation: str | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("اسم الوحدة مطلوب")
        with self.db.transaction() as conn:
            unit_id = int(conn.execute("INSERT INTO units(name,abbreviation) VALUES(?,?)", (name, abbreviation or None)).lastrowid)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create','unit',?,?)",
                (unit_id, name),
            )
            return unit_id

    def rename_unit(self, unit_id: int, name: str, abbreviation: str | None = None) -> None:
        name = name.strip()
        if not name:
            raise ValueError("اسم الوحدة مطلوب")
        with self.db.transaction() as conn:
            conn.execute("UPDATE units SET name=?,abbreviation=? WHERE id=?", (name, abbreviation or None, unit_id))
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update','unit',?,?)",
                (unit_id, name),
            )

    def delete_unit(self, unit_id: int) -> None:
        with self.db.transaction() as conn:
            as_base = conn.execute("SELECT 1 FROM items WHERE base_unit_id=? LIMIT 1", (unit_id,)).fetchone()
            as_alt = conn.execute("SELECT 1 FROM item_units WHERE unit_id=? LIMIT 1", (unit_id,)).fetchone()
            if as_base or as_alt:
                raise ValueError("لا يمكن حذف الوحدة لوجود مواد مرتبطة بها")
            conn.execute("DELETE FROM units WHERE id=?", (unit_id,))
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('delete','unit',?,NULL)",
                (unit_id,),
            )
