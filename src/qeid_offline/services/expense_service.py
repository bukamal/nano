from __future__ import annotations

from datetime import date

from qeid_offline.core.database import Database
from qeid_offline.services.accounting_rebuilder import EPSILON


class ExpenseService:
    def __init__(self, db: Database):
        self.db = db

    def rebuild_ledger(self) -> None:
        """Reconcile expense ledger rows, including records migrated from phase 2."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ledger_entries WHERE source_type='expense'")
            rows = conn.execute(
                """SELECT e.*, COALESCE(ec.name,e.category,'') AS category_name
                   FROM expenses e LEFT JOIN expense_categories ec ON ec.id=e.category_id
                   ORDER BY e.expense_date,e.id"""
            ).fetchall()
            for row in rows:
                self._write_ledger(
                    conn, int(row["id"]), str(row["expense_date"]), float(row["amount"]),
                    str(row["description"]), str(row["category_name"] or "") or None,
                )

    def list_categories(self) -> list[dict]:
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM expense_categories ORDER BY name").fetchall()]

    def create_category(self, name: str) -> int:
        clean = (name or "").strip()
        if not clean:
            raise ValueError("اسم تصنيف المصروف مطلوب")
        with self.db.transaction() as conn:
            try:
                cur = conn.execute("INSERT INTO expense_categories(name) VALUES(?)", (clean,))
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    row = conn.execute("SELECT id FROM expense_categories WHERE name=?", (clean,)).fetchone()
                    if row:
                        return int(row["id"])
                    raise ValueError("التصنيف موجود مسبقًا") from exc
                raise
            return int(cur.lastrowid)

    def list_expenses(self, limit: int = 300) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT e.*, COALESCE(ec.name,e.category,'بلا تصنيف') AS category_name
                   FROM expenses e
                   LEFT JOIN expense_categories ec ON ec.id=e.category_id
                   ORDER BY e.expense_date DESC,e.id DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_expense(self, expense_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT e.*, COALESCE(ec.name,e.category,'بلا تصنيف') AS category_name
                   FROM expenses e LEFT JOIN expense_categories ec ON ec.id=e.category_id
                   WHERE e.id=?""",
                (expense_id,),
            ).fetchone()
            return dict(row) if row else None

    def create_expense(
        self,
        *,
        amount: float,
        description: str,
        expense_date: str | None = None,
        category_id: int | None = None,
        reference: str | None = None,
        notes: str | None = None,
    ) -> int:
        amount_value, description_value, category_name = self._validate(
            amount, description, category_id
        )
        with self.db.transaction() as conn:
            if category_id is not None:
                cat = conn.execute("SELECT name FROM expense_categories WHERE id=?", (category_id,)).fetchone()
                if cat is None:
                    raise ValueError("تصنيف المصروف غير موجود")
                category_name = str(cat["name"])
            edate = (expense_date or date.today().isoformat()).strip()
            cur = conn.execute(
                """INSERT INTO expenses(
                       expense_date,category,category_id,description,amount,reference,notes
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    edate, category_name, category_id, description_value, amount_value,
                    (reference or "").strip() or None,
                    (notes or "").strip() or None,
                ),
            )
            expense_id = int(cur.lastrowid)
            self._write_ledger(conn, expense_id, edate, amount_value, description_value, category_name)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create','expense',?,?)",
                (expense_id, f"{category_name or ''}:{amount_value}"),
            )
            return expense_id

    def update_expense(
        self,
        expense_id: int,
        *,
        amount: float,
        description: str,
        expense_date: str | None = None,
        category_id: int | None = None,
        reference: str | None = None,
        notes: str | None = None,
    ) -> None:
        amount_value, description_value, category_name = self._validate(
            amount, description, category_id
        )
        with self.db.transaction() as conn:
            old = conn.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
            if old is None:
                raise ValueError("المصروف غير موجود")
            if category_id is not None:
                cat = conn.execute("SELECT name FROM expense_categories WHERE id=?", (category_id,)).fetchone()
                if cat is None:
                    raise ValueError("تصنيف المصروف غير موجود")
                category_name = str(cat["name"])
            edate = (expense_date or str(old["expense_date"])).strip()
            conn.execute(
                """UPDATE expenses
                   SET expense_date=?,category=?,category_id=?,description=?,amount=?,reference=?,notes=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    edate, category_name, category_id, description_value, amount_value,
                    (reference or "").strip() or None,
                    (notes or "").strip() or None,
                    expense_id,
                ),
            )
            conn.execute("DELETE FROM ledger_entries WHERE source_type='expense' AND source_id=?", (expense_id,))
            self._write_ledger(conn, expense_id, edate, amount_value, description_value, category_name)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update','expense',?,?)",
                (expense_id, f"{old['amount']} -> {amount_value}"),
            )

    def delete_expense(self, expense_id: int) -> None:
        with self.db.transaction() as conn:
            old = conn.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
            if old is None:
                raise ValueError("المصروف غير موجود")
            conn.execute("DELETE FROM ledger_entries WHERE source_type='expense' AND source_id=?", (expense_id,))
            conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('delete','expense',?,?)",
                (expense_id, str(old["amount"])),
            )

    @staticmethod
    def _validate(amount: float, description: str, category_id: int | None):
        value = float(amount or 0)
        if value <= EPSILON:
            raise ValueError("قيمة المصروف يجب أن تكون أكبر من صفر")
        desc = (description or "").strip()
        if not desc:
            raise ValueError("بيان المصروف مطلوب")
        return value, desc, None

    @staticmethod
    def _write_ledger(
        conn,
        expense_id: int,
        expense_date: str,
        amount: float,
        description: str,
        category_name: str | None,
    ) -> None:
        label = f"مصروف {category_name}: {description}" if category_name else f"مصروف: {description}"
        conn.execute(
            "INSERT INTO ledger_entries(entry_date,account_code,debit,source_type,source_id,description) VALUES(?,?,?,'expense',?,?)",
            (expense_date, "EXPENSE", amount, expense_id, label),
        )
        conn.execute(
            "INSERT INTO ledger_entries(entry_date,account_code,credit,source_type,source_id,description) VALUES(?,?,?,'expense',?,?)",
            (expense_date, "CASH", amount, expense_id, label),
        )
