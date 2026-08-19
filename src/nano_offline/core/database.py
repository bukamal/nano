from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 6

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    phone TEXT,
    address TEXT,
    balance REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    phone TEXT,
    address TEXT,
    balance REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    abbreviation TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    item_type TEXT NOT NULL DEFAULT 'مخزون' CHECK(item_type IN ('مخزون','خدمة')),
    purchase_price REAL NOT NULL DEFAULT 0 CHECK(purchase_price >= 0),
    selling_price REAL NOT NULL DEFAULT 0 CHECK(selling_price >= 0),
    quantity REAL NOT NULL DEFAULT 0,
    average_cost REAL NOT NULL DEFAULT 0,
    opening_quantity REAL NOT NULL DEFAULT 0,
    opening_unit_cost REAL NOT NULL DEFAULT 0,
    base_unit_id INTEGER REFERENCES units(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    conversion_factor REAL NOT NULL DEFAULT 1 CHECK(conversion_factor > 0),
    UNIQUE(item_id, unit_id)
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('sale','purchase')),
    customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
    invoice_date TEXT NOT NULL,
    reference TEXT,
    notes TEXT,
    total REAL NOT NULL DEFAULT 0 CHECK(total >= 0),
    initial_paid_amount REAL NOT NULL DEFAULT 0 CHECK(initial_paid_amount >= 0),
    paid_amount REAL NOT NULL DEFAULT 0 CHECK(paid_amount >= 0),
    status TEXT NOT NULL DEFAULT 'posted',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK((type='sale' AND supplier_id IS NULL) OR (type='purchase' AND customer_id IS NULL))
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES items(id) ON DELETE RESTRICT,
    description TEXT NOT NULL,
    unit_id INTEGER REFERENCES units(id) ON DELETE RESTRICT,
    conversion_factor REAL NOT NULL DEFAULT 1 CHECK(conversion_factor > 0),
    quantity REAL NOT NULL CHECK(quantity > 0),
    quantity_in_base REAL NOT NULL CHECK(quantity_in_base > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    total REAL NOT NULL CHECK(total >= 0),
    unit_cost REAL NOT NULL DEFAULT 0,
    cost_amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
    direction TEXT NOT NULL CHECK(direction IN ('in','out')),
    amount REAL NOT NULL CHECK(amount > 0),
    payment_date TEXT NOT NULL,
    reference TEXT,
    notes TEXT,
    source_type TEXT NOT NULL DEFAULT 'legacy',
    source_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(NOT (customer_id IS NOT NULL AND supplier_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS payment_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    amount REAL NOT NULL CHECK(amount > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(payment_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS vouchers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_type TEXT NOT NULL CHECK(voucher_type IN ('receipt','payment')),
    customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
    voucher_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    reference TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK((voucher_type='receipt' AND customer_id IS NOT NULL AND supplier_id IS NULL)
       OR (voucher_type='payment' AND supplier_id IS NOT NULL AND customer_id IS NULL))
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    movement_type TEXT NOT NULL CHECK(movement_type IN ('purchase','sale','adjustment')),
    quantity_delta REAL NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0,
    value_delta REAL NOT NULL DEFAULT 0,
    movement_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    account_code TEXT NOT NULL,
    party_type TEXT CHECK(party_type IN ('customer','supplier') OR party_type IS NULL),
    party_id INTEGER,
    debit REAL NOT NULL DEFAULT 0 CHECK(debit >= 0),
    credit REAL NOT NULL DEFAULT 0 CHECK(credit >= 0),
    source_type TEXT NOT NULL,
    source_id INTEGER,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(NOT (debit > 0 AND credit > 0))
);

CREATE TABLE IF NOT EXISTS expense_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date TEXT NOT NULL,
    category TEXT,
    category_id INTEGER REFERENCES expense_categories(id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    reference TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','accountant','sales','viewer')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login_at TEXT,
    quick_auth_type TEXT,
    quick_auth_hash TEXT,
    quick_auth_salt TEXT,
    quick_auth_key_id TEXT,
    remember_token_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    details TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS license_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    license_key TEXT,
    signed_token TEXT,
    device_id TEXT,
    activated_at TEXT,
    last_verified_at TEXT,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_id);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id, payment_date);
CREATE INDEX IF NOT EXISTS idx_payments_supplier ON payments(supplier_id, payment_date);
CREATE INDEX IF NOT EXISTS idx_payments_source ON payments(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_allocations_invoice ON payment_allocations(invoice_id);
CREATE INDEX IF NOT EXISTS idx_allocations_payment ON payment_allocations(payment_id);
CREATE INDEX IF NOT EXISTS idx_vouchers_date ON vouchers(voucher_date);
CREATE INDEX IF NOT EXISTS idx_inventory_item_date ON inventory_movements(item_id, movement_date);
CREATE INDEX IF NOT EXISTS idx_ledger_party ON ledger_entries(party_type, party_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at);

CREATE TRIGGER IF NOT EXISTS trg_audit_attach_actor
AFTER INSERT ON audit_log
WHEN NEW.user_id IS NULL
BEGIN
    UPDATE audit_log
       SET user_id=qeid_actor_id(), username=qeid_actor_username()
     WHERE id=NEW.id;
END;
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._actor_user_id: int | None = None
        self._actor_username: str | None = None

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.create_function("qeid_actor_id", 0, lambda: self._actor_user_id)
        conn.create_function("qeid_actor_username", 0, lambda: self._actor_username)
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            # Existing databases need column migrations before the full schema
            # can safely create indexes that reference phase-3 columns.
            self._pre_schema_migrate(conn)
            conn.executescript(SCHEMA_SQL)
            self._migrate(conn)
            conn.execute(
                "INSERT INTO schema_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('currency','USD')")
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('company_name','نانو')")
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('payment_allocation_mode','oldest')")
            conn.commit()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        if not Database._table_exists(conn, table):
            return False
        return any(str(r[1]) == column for r in conn.execute(f"PRAGMA table_info({table})").fetchall())

    def _pre_schema_migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns needed by phase-3 indexes before SCHEMA_SQL runs."""
        if self._table_exists(conn, "invoices") and not self._has_column(conn, "invoices", "initial_paid_amount"):
            conn.execute("ALTER TABLE invoices ADD COLUMN initial_paid_amount REAL NOT NULL DEFAULT 0")
            conn.execute("UPDATE invoices SET initial_paid_amount=paid_amount")

        if self._table_exists(conn, "payments"):
            if not self._has_column(conn, "payments", "reference"):
                conn.execute("ALTER TABLE payments ADD COLUMN reference TEXT")
            if not self._has_column(conn, "payments", "source_type"):
                conn.execute("ALTER TABLE payments ADD COLUMN source_type TEXT NOT NULL DEFAULT 'legacy'")
            if not self._has_column(conn, "payments", "source_id"):
                conn.execute("ALTER TABLE payments ADD COLUMN source_id INTEGER")

        if self._table_exists(conn, "audit_log"):
            if not self._has_column(conn, "audit_log", "user_id"):
                conn.execute("ALTER TABLE audit_log ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
            if not self._has_column(conn, "audit_log", "username"):
                conn.execute("ALTER TABLE audit_log ADD COLUMN username TEXT")

        if self._table_exists(conn, "users"):
            for column in ("quick_auth_type", "quick_auth_hash", "quick_auth_salt", "quick_auth_key_id", "remember_token_hash"):
                if not self._has_column(conn, "users", column):
                    conn.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")

        if self._table_exists(conn, "expenses"):
            if not self._has_column(conn, "expenses", "category_id"):
                conn.execute("ALTER TABLE expenses ADD COLUMN category_id INTEGER REFERENCES expense_categories(id) ON DELETE SET NULL")
            if not self._has_column(conn, "expenses", "reference"):
                conn.execute("ALTER TABLE expenses ADD COLUMN reference TEXT")
            if not self._has_column(conn, "expenses", "notes"):
                conn.execute("ALTER TABLE expenses ADD COLUMN notes TEXT")
            if not self._has_column(conn, "expenses", "updated_at"):
                conn.execute("ALTER TABLE expenses ADD COLUMN updated_at TEXT")
                conn.execute("UPDATE expenses SET updated_at=created_at WHERE updated_at IS NULL")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Non-destructive migrations from phases 1 and 2."""
        added_opening_qty = False
        added_opening_cost = False
        if not self._has_column(conn, "items", "opening_quantity"):
            conn.execute("ALTER TABLE items ADD COLUMN opening_quantity REAL NOT NULL DEFAULT 0")
            added_opening_qty = True
        if not self._has_column(conn, "items", "opening_unit_cost"):
            conn.execute("ALTER TABLE items ADD COLUMN opening_unit_cost REAL NOT NULL DEFAULT 0")
            added_opening_cost = True

        if added_opening_qty or added_opening_cost:
            for item in conn.execute("SELECT id,purchase_price FROM items").fetchall():
                opening = conn.execute(
                    """SELECT COALESCE(SUM(quantity_delta),0) AS qty, COALESCE(SUM(value_delta),0) AS value
                       FROM inventory_movements
                       WHERE item_id=? AND invoice_id IS NULL AND movement_type='adjustment'""",
                    (item["id"],),
                ).fetchone()
                qty = float(opening["qty"] or 0)
                value = float(opening["value"] or 0)
                unit_cost = value / qty if abs(qty) > 1e-9 else 0.0
                conn.execute(
                    "UPDATE items SET opening_quantity=?,opening_unit_cost=? WHERE id=?",
                    (qty, unit_cost, item["id"]),
                )

        # Phase-2 invoice-linked payment rows were derived and can be safely
        # regenerated from invoices.initial_paid_amount by AccountingRebuilder.
        if self._table_exists(conn, "payments"):
            conn.execute(
                "DELETE FROM payments WHERE invoice_id IS NOT NULL AND source_type='legacy'"
            )

        # Phase 7: existing service sale lines had zero COGS. Snapshot the
        # current configured service purchase_price exactly once during the
        # schema-4 -> schema-5 upgrade; new invoices snapshot cost at creation.
        old_version_row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        old_version = int(old_version_row[0]) if old_version_row else 0
        if old_version < 5 and self._table_exists(conn, "invoice_lines") and self._table_exists(conn, "items"):
            conn.execute(
                """UPDATE invoice_lines
                   SET unit_cost=(SELECT COALESCE(i.purchase_price,0) * invoice_lines.conversion_factor
                                  FROM items i WHERE i.id=invoice_lines.item_id),
                       cost_amount=(SELECT COALESCE(i.purchase_price,0) * invoice_lines.conversion_factor * invoice_lines.quantity
                                    FROM items i WHERE i.id=invoice_lines.item_id)
                   WHERE invoice_id IN (SELECT id FROM invoices WHERE type='sale')
                     AND item_id IN (SELECT id FROM items WHERE item_type='خدمة')
                     AND ABS(COALESCE(cost_amount,0)) < 1e-9"""
            )

        # Preserve old text expense categories while normalizing new records.
        if self._table_exists(conn, "expenses"):
            names = [
                str(r[0]).strip()
                for r in conn.execute(
                    "SELECT DISTINCT category FROM expenses WHERE category IS NOT NULL AND TRIM(category)<>''"
                ).fetchall()
            ]
            for name in names:
                conn.execute("INSERT OR IGNORE INTO expense_categories(name) VALUES(?)", (name,))
            conn.execute(
                """UPDATE expenses
                   SET category_id=(SELECT ec.id FROM expense_categories ec WHERE ec.name=expenses.category)
                   WHERE category_id IS NULL AND category IS NOT NULL AND TRIM(category)<>''"""
            )

    def set_actor(self, user_id: int | None, username: str | None) -> None:
        self._actor_user_id = int(user_id) if user_id is not None else None
        self._actor_username = (username or "").strip() or None

    def actor(self) -> tuple[int | None, str | None]:
        return self._actor_user_id, self._actor_username

    def checkpoint(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def integrity_check(self) -> str:
        with self.connect() as conn:
            return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
