from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qeid_offline.core.database import Database, SCHEMA_VERSION

with tempfile.TemporaryDirectory(prefix="qeid-phase2-migration-") as td:
    path = Path(td) / "qeid.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta(key,value) VALUES('schema_version','1');

        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            category_id INTEGER,
            item_type TEXT NOT NULL DEFAULT 'مخزون',
            purchase_price REAL NOT NULL DEFAULT 0,
            selling_price REAL NOT NULL DEFAULT 0,
            quantity REAL NOT NULL DEFAULT 0,
            average_cost REAL NOT NULL DEFAULT 0,
            base_unit_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO items(name,item_type,purchase_price,selling_price,quantity,average_cost)
        VALUES('مادة محفوظة','مخزون',12,20,12,11);

        CREATE TABLE inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            invoice_id INTEGER,
            movement_type TEXT NOT NULL,
            quantity_delta REAL NOT NULL,
            unit_cost REAL NOT NULL DEFAULT 0,
            value_delta REAL NOT NULL DEFAULT 0,
            movement_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO inventory_movements(item_id,invoice_id,movement_type,quantity_delta,unit_cost,value_delta,movement_date)
        VALUES(1,NULL,'adjustment',10,10,100,'2026-08-01');
        """
    )
    conn.commit()
    conn.close()

    db = Database(path)
    db.initialize()
    with db.connect() as conn:
        version = int(conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0])
        item = conn.execute(
            "SELECT name,quantity,opening_quantity,opening_unit_cost FROM items WHERE id=1"
        ).fetchone()
        columns = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
        assert version == SCHEMA_VERSION and SCHEMA_VERSION >= 2
        assert {"opening_quantity", "opening_unit_cost"} <= columns
        assert item["name"] == "مادة محفوظة"
        assert float(item["quantity"]) == 12  # current state preserved during migration
        assert float(item["opening_quantity"]) == 10
        assert float(item["opening_unit_cost"]) == 10
    assert db.integrity_check() == "ok"

print("phase2_schema_upgrade_smoke_test passed")
