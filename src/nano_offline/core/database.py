from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 12

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
    barcode TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Partial unique index: many items legitimately have no barcode at all, and
-- SQLite already treats every NULL as distinct under UNIQUE -- but an empty
-- string is not NULL, so the WHERE clause excludes '' too, letting several
-- barcode-less items coexist without a bogus uniqueness clash.
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_barcode
    ON items(barcode) WHERE barcode IS NOT NULL AND TRIM(barcode) <> '';

-- Secondary barcodes for the same item -- e.g. a separate code printed on
-- the carton/pack vs the single piece, or an old code the manufacturer
-- retired and replaced (kept here so stock printed with the old label can
-- still be scanned). items.barcode remains the item's *primary* code and
-- is unaffected by this table; each row here is an additional alias that
-- resolves to the same item. unit_id lets a specific packaging barcode
-- (e.g. "carton") map to a specific selling unit so scanning it can add
-- the right quantity, not just identify the item.
CREATE TABLE IF NOT EXISTS item_barcodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    barcode TEXT NOT NULL,
    unit_id INTEGER REFERENCES units(id) ON DELETE SET NULL,
    label TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Global uniqueness spans this table AND items.barcode together (enforced
-- in ItemRepository, since SQLite can't express a UNIQUE constraint across
-- two different tables) -- a code can only ever mean one item, whether it
-- is that item's primary or a secondary code.
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_barcodes_barcode ON item_barcodes(barcode);
CREATE INDEX IF NOT EXISTS idx_item_barcodes_item ON item_barcodes(item_id);

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
    -- Snapshot of the *display* currency in effect the moment the invoice was
    -- created (see core/currency.py). Printed documents must keep showing the
    -- rate that was actually used to compute the invoice's amounts, even if
    -- the admin changes today's rate later -- otherwise an old SYP invoice
    -- would silently reprice itself against a rate that never applied to it.
    invoice_exchange_rate REAL,
    invoice_currency_code TEXT,
    invoice_currency_symbol TEXT,
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
    -- Same historical-snapshot idea as invoices.invoice_exchange_rate: the
    -- rate/currency in force the moment this cash movement happened, so a
    -- customer/supplier statement can show each line at the rate it actually
    -- occurred at instead of retroactively repricing old movements at
    -- today's rate.
    payment_exchange_rate REAL,
    payment_currency_code TEXT,
    payment_currency_symbol TEXT,
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

-- Smart notifications (schema 11): a log of alerts the rules engine in
-- NotificationService has already surfaced, kept only for dedupe/read-state.
-- The truth of *whether something is still true* (an invoice still unpaid,
-- an item still low) is always recomputed live from the real tables above --
-- this table never becomes a second source of truth for accounting/stock
-- data. `dedupe_key` normally embeds the day (e.g. 'low_stock:2026-08-29')
-- so a still-unresolved condition naturally re-surfaces once per day instead
-- of spamming, without needing a separate scheduler table. Per-rule
-- configuration (enabled/thresholds/quiet hours) intentionally lives in the
-- existing open-ended `settings` table instead of new columns/tables here --
-- same reasoning SettingsRepository already documents for branding fields.
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    rule_key TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info' CHECK(severity IN ('info','warning','urgent')),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notification_log_created ON notification_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notification_log_unread ON notification_log(read_at) WHERE read_at IS NULL;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Continuous-scan stocktake: a session is a walk-the-shelves counting run.
-- Lines accumulate locally (one row per item, counted_qty grows with every
-- scan) and nothing touches `inventory_movements`/`items` until the session
-- is explicitly committed -- see StocktakeService.commit for the write path.
CREATE TABLE IF NOT EXISTS stocktake_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','committed','discarded')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS stocktake_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES stocktake_sessions(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    counted_qty REAL NOT NULL DEFAULT 0,
    system_qty_snapshot REAL NOT NULL,
    scan_count INTEGER NOT NULL DEFAULT 0,
    last_scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_stocktake_lines_session ON stocktake_lines(session_id);

CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_id);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines(invoice_id);
-- Without this, ItemRepository.list()'s per-row "has_activity" check
-- (EXISTS(SELECT 1 FROM invoice_lines WHERE item_id=...)) full-scans
-- invoice_lines once for EVERY item on screen -- items x invoice_lines
-- comparisons, which is the single biggest cause of the app slowing down
-- as sales history grows. This index turns each check into an instant
-- lookup instead.
CREATE INDEX IF NOT EXISTS idx_invoice_lines_item ON invoice_lines(item_id);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category_id);
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
        # Perf: give SQLite a bigger page cache (~20MB, negative = KB) and do
        # sorting/temp tables in RAM instead of on disk -- both cheap on a
        # phone and noticeably faster once tables have thousands of rows.
        conn.execute("PRAGMA cache_size = -20000")
        conn.execute("PRAGMA temp_store = MEMORY")
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
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES('exchange_rate_syp_per_usd','13500')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES('display_currency_symbol','ل.س')"
            )
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

        # Schema 8: snapshot the display currency/rate onto each invoice so
        # printed documents reflect the rate that was actually in force when
        # the invoice was issued. Invoices created before this migration have
        # no true historical rate on file, so they are backfilled with
        # whichever rate/currency is configured *now* -- identical to what
        # they already displayed everywhere else before this change, and far
        # better than leaving the printed rate blank.
        if self._table_exists(conn, "invoices") and not self._has_column(conn, "invoices", "invoice_exchange_rate"):
            conn.execute("ALTER TABLE invoices ADD COLUMN invoice_exchange_rate REAL")
            conn.execute("ALTER TABLE invoices ADD COLUMN invoice_currency_code TEXT")
            conn.execute("ALTER TABLE invoices ADD COLUMN invoice_currency_symbol TEXT")
            if self._table_exists(conn, "settings"):
                settings = {
                    str(r["key"]): str(r["value"])
                    for r in conn.execute("SELECT key,value FROM settings").fetchall()
                }
            else:
                settings = {}
            from nano_offline.core import currency as _currency

            rate = _currency.get_effective_rate(settings)
            code = _currency.get_display_currency(settings)
            symbol = _currency.get_display_symbol(settings)
            conn.execute(
                "UPDATE invoices SET invoice_exchange_rate=?, invoice_currency_code=?, invoice_currency_symbol=? "
                "WHERE invoice_exchange_rate IS NULL",
                (rate, code, symbol),
            )

        # Schema 9: same snapshot on `payments`, so a customer/supplier
        # statement can show every cash movement at the rate that applied
        # when it happened, not just invoices. `invoice_initial` rows are
        # regenerated from their invoice on every rebuild (see
        # AccountingRebuilder._sync_initial_invoice_payments) and inherit the
        # invoice's own rate there, so this backfill only needs to cover
        # existing `voucher`/`legacy` rows already on disk.
        if self._table_exists(conn, "payments") and not self._has_column(conn, "payments", "payment_exchange_rate"):
            conn.execute("ALTER TABLE payments ADD COLUMN payment_exchange_rate REAL")
            conn.execute("ALTER TABLE payments ADD COLUMN payment_currency_code TEXT")
            conn.execute("ALTER TABLE payments ADD COLUMN payment_currency_symbol TEXT")
            if self._table_exists(conn, "settings"):
                settings = {
                    str(r["key"]): str(r["value"])
                    for r in conn.execute("SELECT key,value FROM settings").fetchall()
                }
            else:
                settings = {}
            from nano_offline.core import currency as _currency

            rate = _currency.get_effective_rate(settings)
            code = _currency.get_display_currency(settings)
            symbol = _currency.get_display_symbol(settings)
            conn.execute(
                "UPDATE payments SET payment_exchange_rate=?, payment_currency_code=?, payment_currency_symbol=? "
                "WHERE payment_exchange_rate IS NULL",
                (rate, code, symbol),
            )

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

        if self._table_exists(conn, "items") and not self._has_column(conn, "items", "barcode"):
            # Must happen here (pre-schema), not in _migrate(), because
            # SCHEMA_SQL's CREATE UNIQUE INDEX on items(barcode) runs right
            # after this and would fail against an old database that doesn't
            # have the column yet.
            conn.execute("ALTER TABLE items ADD COLUMN barcode TEXT")

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
