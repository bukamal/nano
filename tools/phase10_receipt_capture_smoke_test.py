from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.core.database import Database, SCHEMA_VERSION

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"  # tiny non-empty JPEG-ish blob

with tempfile.TemporaryDirectory(prefix="nano_phase10_capture_") as td:
    root = Path(td)
    ctx = AppContext.create(root / "data" / "nano.db")
    ctx.auth.create_initial_admin("admin", "المدير", "StrongPass1")
    ctx.auth.login("admin", "StrongPass1")

    # --- 1. expense without a photo: has_receipt False, receipt absent ---
    eid = ctx.expenses.create_expense(amount=120.5, description="فاتورة كهرباء", expense_date="2026-09-01")
    row = ctx.expenses.get_expense(eid)
    assert row is not None and not row["has_receipt"], row
    assert ctx.expenses.get_expense_receipt(eid)["image"] is None

    # --- 2. attach a photo: bytes + name round-trip ---
    ctx.expenses.set_expense_receipt(eid, FAKE_JPEG, "receipt_2026_09_01.jpg")
    row = ctx.expenses.get_expense(eid)
    assert row["has_receipt"] and row["receipt_name"] == "receipt_2026_09_01.jpg", row
    receipt = ctx.expenses.get_expense_receipt(eid)
    assert receipt is not None and receipt["image"] == FAKE_JPEG and receipt["name"] == "receipt_2026_09_01.jpg"

    # --- 3. list rows never carry the BLOB -- only a flag ---
    listed = [e for e in ctx.expenses.list_expenses() if e["id"] == eid][0]
    assert listed["has_receipt"] and "receipt_image" not in listed, listed.keys()

    # --- 4. create_expense accepts a photo directly ---
    eid2 = ctx.expenses.create_expense(
        amount=40, description="نقل", expense_date="2026-09-02",
        receipt_image=FAKE_JPEG, receipt_name="transport.jpg",
    )
    assert ctx.expenses.get_expense_receipt(eid2)["image"] == FAKE_JPEG

    # --- 5. update_expense can replace the photo ---
    ctx.expenses.update_expense(
        eid, amount=130, description="فاتورة كهرباء معدلة",
        receipt_image=FAKE_JPEG, receipt_name="new.jpg",
    )
    assert ctx.expenses.get_expense_receipt(eid)["name"] == "new.jpg"

    # --- 6. removing the photo clears it ---
    ctx.expenses.set_expense_receipt(eid, None)
    assert ctx.expenses.get_expense_receipt(eid)["image"] is None
    assert not ctx.expenses.get_expense(eid)["has_receipt"]

    # --- 7. legacy database (schema 13, no photo columns) migrates non-destructively ---
    legacy = root / "legacy" / "nano.db"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(legacy)
    conn.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','13')")
    conn.execute(
        "CREATE TABLE expenses("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, expense_date TEXT NOT NULL, category TEXT,"
        "category_id INTEGER, description TEXT NOT NULL, amount REAL NOT NULL,"
        "reference TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT)"
    )
    conn.execute("INSERT INTO expenses(expense_date,description,amount) VALUES('2026-08-01','قديم',10)")
    conn.commit()
    conn.close()
    db = Database(legacy)
    db.initialize()
    with db.connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(expenses)").fetchall()}
        assert {"receipt_image", "receipt_name"} <= cols, cols
        version = int(c.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0])
        assert version == SCHEMA_VERSION and SCHEMA_VERSION == 14, version
        assert c.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1  # untouched

    # --- 8. contract needles: bridge + dart + pubspec + service + UI ---
    ROOT = Path(__file__).resolve().parents[1]
    native_py = (ROOT / "extensions/flet_native_files/src/flet_native_files/native_files.py").read_text(encoding="utf-8")
    dart = (ROOT / "extensions/flet_native_files/src/flutter/flet_native_files/lib/src/native_files.dart").read_text(encoding="utf-8")
    pubspec = (ROOT / "extensions/flet_native_files/src/flutter/flet_native_files/pubspec.yaml").read_text(encoding="utf-8")
    finance = (ROOT / "src/nano_offline/views/finance_view.py").read_text(encoding="utf-8")
    service = (ROOT / "src/nano_offline/services/expense_service.py").read_text(encoding="utf-8")
    assert "capture_receipt" in native_py
    assert "case 'capture_receipt'" in dart and "ImagePicker().pickImage" in dart and "ImageSource.camera" in dart
    assert "image_picker" in pubspec
    assert "receipt_image" in service and "set_expense_receipt" in service and "get_expense_receipt" in service
    assert "التقاط صورة الإيصال" in finance and "show_receipt_photo" in finance and "has_receipt" in finance

print("phase10_receipt_capture_smoke_test passed")
