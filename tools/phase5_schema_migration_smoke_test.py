from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from nano_offline.core.database import Database, SCHEMA_VERSION

with tempfile.TemporaryDirectory(prefix="nano_phase5_migration_") as td:
    db_path = Path(td) / "nano.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
        CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES('schema_version','3');
        CREATE TABLE audit_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          action TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id INTEGER,details TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        conn.execute("INSERT INTO audit_log(action,entity_type,details) VALUES('legacy','test','before phase5')")
        conn.commit()
    finally:
        conn.close()

    db = Database(db_path)
    db.initialize()
    assert SCHEMA_VERSION >= 4
    with db.connect() as conn:
        version = int(conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0])
        assert version == SCHEMA_VERSION
        user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        audit_cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        assert {"username","password_hash","password_salt","role","is_active"} <= user_cols
        assert {"user_id","username"} <= audit_cols
        legacy = conn.execute("SELECT details FROM audit_log WHERE action='legacy'").fetchone()
        assert legacy and legacy[0] == "before phase5"
    assert db.integrity_check().lower() == "ok"

print("phase5_schema_migration_smoke_test passed")
