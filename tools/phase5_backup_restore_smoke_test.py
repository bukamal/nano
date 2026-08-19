from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.core.database import SCHEMA_VERSION

with tempfile.TemporaryDirectory(prefix="nano_phase5_backup_") as td:
    root = Path(td)
    ctx = AppContext.create(root / "data" / "nano.db")
    ctx.auth.create_initial_admin("admin", "المدير", "StrongPass1")
    ctx.auth.login("admin", "StrongPass1")
    first_id = ctx.customers.create("العميل الأصلي")
    device_id = ctx.license.device_id()
    with ctx.db.transaction() as conn:
        conn.execute(
            "INSERT INTO license_state(id,license_key,signed_token,device_id,activated_at) VALUES(1,'CURRENT','device-token',?,CURRENT_TIMESTAMP)",
            (device_id,),
        )

    backup = ctx.backup.create_backup(root / "snapshot.nanobackup")
    validation = ctx.backup.validate_backup(backup)
    assert validation.valid and validation.schema_version == SCHEMA_VERSION

    with tempfile.TemporaryDirectory(prefix="nano_phase5_backup_inspect_") as inspect_dir:
        import sqlite3, zipfile
        out = Path(inspect_dir)
        with zipfile.ZipFile(backup) as zf:
            zf.extract("nano.db", out)
        conn = sqlite3.connect(out / "nano.db")
        try:
            assert conn.execute("SELECT COUNT(*) FROM license_state").fetchone()[0] == 0
        finally:
            conn.close()

    ctx.customers.create("عميل بعد النسخة")
    assert len(ctx.customers.list()) == 2
    safety = ctx.backup.restore_backup(backup)
    assert safety.exists()
    customers = ctx.customers.list()
    assert len(customers) == 1 and int(customers[0]["id"]) == first_id and customers[0]["name"] == "العميل الأصلي"
    with ctx.db.connect() as conn:
        lic = conn.execute("SELECT license_key,device_id FROM license_state WHERE id=1").fetchone()
        assert lic and lic["license_key"] == "CURRENT" and lic["device_id"] == device_id
    assert ctx.db.integrity_check().lower() == "ok"

print("phase5_backup_restore_smoke_test passed")
