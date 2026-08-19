from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.app_context import AppContext
from nano_offline.core.database import SCHEMA_VERSION


def make_phase2_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES('schema_version','2');
        CREATE TABLE customers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,phone TEXT,address TEXT,balance REAL NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,phone TEXT,address TEXT,balance REAL NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE items(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,category_id INTEGER,item_type TEXT NOT NULL DEFAULT 'مخزون',purchase_price REAL NOT NULL DEFAULT 0,selling_price REAL NOT NULL DEFAULT 0,quantity REAL NOT NULL DEFAULT 0,average_cost REAL NOT NULL DEFAULT 0,opening_quantity REAL NOT NULL DEFAULT 0,opening_unit_cost REAL NOT NULL DEFAULT 0,base_unit_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE invoices(id INTEGER PRIMARY KEY AUTOINCREMENT,type TEXT NOT NULL,customer_id INTEGER,supplier_id INTEGER,invoice_date TEXT NOT NULL,reference TEXT,notes TEXT,total REAL NOT NULL DEFAULT 0,paid_amount REAL NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'posted',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE payments(id INTEGER PRIMARY KEY AUTOINCREMENT,invoice_id INTEGER,customer_id INTEGER,supplier_id INTEGER,direction TEXT NOT NULL,amount REAL NOT NULL,payment_date TEXT NOT NULL,notes TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE inventory_movements(id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL,invoice_id INTEGER,movement_type TEXT NOT NULL,quantity_delta REAL NOT NULL,unit_cost REAL NOT NULL DEFAULT 0,value_delta REAL NOT NULL DEFAULT 0,movement_date TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE expenses(id INTEGER PRIMARY KEY AUTOINCREMENT,expense_date TEXT NOT NULL,category TEXT,description TEXT NOT NULL,amount REAL NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id INTEGER,details TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE license_state(id INTEGER PRIMARY KEY,license_key TEXT,signed_token TEXT,device_id TEXT,activated_at TEXT,last_verified_at TEXT,expires_at TEXT);
        INSERT INTO customers(id,name,balance) VALUES(1,'عميل قديم',80);
        INSERT INTO invoices(id,type,customer_id,invoice_date,total,paid_amount) VALUES(1,'sale',1,'2026-01-01',100,20);
        INSERT INTO payments(id,invoice_id,customer_id,direction,amount,payment_date,notes) VALUES(1,1,1,'in',20,'2026-01-01','دفعة تلقائية من الفاتورة');
        INSERT INTO expenses(id,expense_date,category,description,amount) VALUES(1,'2026-01-02','نقل','مصروف قديم',5);
        """
    )
    conn.commit()
    conn.close()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qeid-phase3-migrate-") as td:
        path = Path(td) / "phase2.db"
        make_phase2_db(path)
        ctx = AppContext.create(path)
        with ctx.db.connect() as conn:
            version = int(conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0])
            assert version == SCHEMA_VERSION and SCHEMA_VERSION >= 3
            invoice = conn.execute("SELECT total,initial_paid_amount,paid_amount FROM invoices WHERE id=1").fetchone()
            assert tuple(map(float, invoice)) == (100.0, 20.0, 20.0)
            payments = conn.execute("SELECT source_type,source_id,amount FROM payments").fetchall()
            assert len(payments) == 1
            assert payments[0]["source_type"] == "invoice_initial"
            assert int(payments[0]["source_id"]) == 1
            allocation = conn.execute("SELECT invoice_id,amount FROM payment_allocations").fetchone()
            assert int(allocation["invoice_id"]) == 1 and float(allocation["amount"]) == 20
            cat = conn.execute("SELECT id,name FROM expense_categories WHERE name='نقل'").fetchone()
            assert cat is not None
            exp = conn.execute("SELECT category_id,reference,notes,updated_at FROM expenses WHERE id=1").fetchone()
            assert int(exp["category_id"]) == int(cat["id"])
            assert exp["updated_at"] is not None
            expense_ledger = conn.execute("SELECT COUNT(*) FROM ledger_entries WHERE source_type='expense' AND source_id=1").fetchone()[0]
            assert int(expense_ledger) == 2
        assert float(ctx.customers.get(1)["balance"]) == 80.0
        assert ctx.db.integrity_check() == "ok"
        print("phase3_schema_migration_smoke_test passed")
        print("v2->v3 initial-payment=preserved allocations=rebuilt expense-category=normalized")


if __name__ == "__main__":
    main()
