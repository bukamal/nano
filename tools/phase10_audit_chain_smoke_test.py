from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.core import audit_chain


def _fresh_ctx(root: Path) -> AppContext:
    ctx = AppContext.create(root / "data" / "nano.db")
    ctx.auth.create_initial_admin("admin", "المدير", "StrongPass1")
    ctx.auth.login("admin", "StrongPass1")
    return ctx


with tempfile.TemporaryDirectory(prefix="nano_phase10_audit_") as td:
    root = Path(td)

    # --- 1. fresh database: every insert gets hashed and the chain verifies ---
    ctx = _fresh_ctx(root / "fresh")
    cid = ctx.customers.create("عميل السلسلة")
    ctx.customers.create("عميل السلسلة 2")
    with ctx.db.connect() as conn:
        rows = conn.execute(
            "SELECT id, row_hash, prev_hash FROM audit_log ORDER BY id"
        ).fetchall()
        assert len(rows) >= 3  # create_user + 2 customers
        assert all(r["row_hash"] is not None for r in rows)
    res = audit_chain.verify_audit_chain(ctx.db)
    assert res["valid"] and res["hashed"] == len(rows) and res["broken_at"] is None, res

    # --- 2. tamper with a row: chain must point at it ---
    with ctx.db.connect() as conn:
        conn.execute(
            "UPDATE audit_log SET details='معدّل' WHERE entity_type='customer' AND entity_id=?",
            (cid,),
        )
    res = audit_chain.verify_audit_chain(ctx.db)
    assert not res["valid"] and res["broken_at"] is not None, res

    # --- 3. deleting a middle row breaks the next row's linkage ---
    ctx2 = _fresh_ctx(root / "delete")
    ids = []
    for name in ("أ", "ب", "ج"):
        ids.append(ctx2.customers.create(name))
    with ctx2.db.connect() as conn:
        conn.execute("DELETE FROM audit_log WHERE entity_type='customer' AND entity_id=?", (ids[1],))
    res = audit_chain.verify_audit_chain(ctx2.db)
    assert not res["valid"] and res["broken_at"] is not None, res

    # --- 4. legacy database (no hash columns) migrates non-destructively ---
    legacy = root / "legacy" / "nano.db"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(legacy)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_log("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, entity_type TEXT NOT NULL,"
        "entity_id INTEGER, details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO audit_log(action,entity_type,details) VALUES('legacy','test','before')")
    conn.commit()
    conn.close()

    from nano_offline.core.database import Database

    db = Database(legacy)
    db.initialize()
    with db.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        assert {"prev_hash", "row_hash"} <= cols
        legacy_row = conn.execute(
            "SELECT row_hash, prev_hash FROM audit_log WHERE action='legacy'"
        ).fetchone()
        assert legacy_row["row_hash"] is None  # sealed root, never rewritten
        conn.execute(
            "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create','test',1,'after')"
        )
        new_row = conn.execute(
            "SELECT row_hash, prev_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert new_row["row_hash"] is not None and new_row["prev_hash"] is None  # root of new chain
    res = audit_chain.verify_audit_chain(db)
    assert res["valid"] and res["hashed"] == 1, res

print("phase10_audit_chain_smoke_test passed")
