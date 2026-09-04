from __future__ import annotations

from qeid_offline.core.database import Database


class DefinitionsRepository:
    def __init__(self, db: Database):
        self.db = db

    def list_categories(self) -> list[dict]:
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY name").fetchall()]

    def create_category(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("اسم التصنيف مطلوب")
        with self.db.transaction() as conn:
            return int(conn.execute("INSERT INTO categories(name) VALUES(?)", (name,)).lastrowid)

    def list_units(self) -> list[dict]:
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM units ORDER BY name").fetchall()]

    def create_unit(self, name: str, abbreviation: str | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("اسم الوحدة مطلوب")
        with self.db.transaction() as conn:
            return int(conn.execute("INSERT INTO units(name,abbreviation) VALUES(?,?)", (name, abbreviation or None)).lastrowid)
