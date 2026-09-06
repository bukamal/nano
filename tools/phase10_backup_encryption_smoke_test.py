from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from nano_offline.app_context import AppContext

with tempfile.TemporaryDirectory(prefix="nano_phase10_enc_") as td:
    root = Path(td)
    ctx = AppContext.create(root / "data" / "nano.db")
    ctx.auth.create_initial_admin("admin", "المدير", "StrongPass1")
    ctx.auth.login("admin", "StrongPass1")
    secret = "العميل السرّي 987"
    ctx.customers.create(secret)

    # --- 1. encrypted backup: validate with password, reject without ---
    enc = ctx.backup.create_backup(root / "snapshot-enc.nanobackup", password="صعب-1234")
    val = ctx.backup.validate_backup(enc, password="صعب-1234")
    assert val.valid and val.encrypted, val
    try:
        ctx.backup.validate_backup(enc)
        raise SystemExit("expected ValueError for missing password")
    except ValueError as exc:
        assert "مشفرة" in str(exc)
    try:
        ctx.backup.validate_backup(enc, password="خطأ")
        raise SystemExit("expected ValueError for wrong password")
    except ValueError as exc:
        assert "كلمة المرور" in str(exc)

    # --- 2. plaintext must NOT be recoverable by sniffing zip bytes ---
    with zipfile.ZipFile(enc) as zf:
        assert "nano.db.enc" in zf.namelist() and "nano.db" not in zf.namelist()
        manifest = zf.read("manifest.json").decode("utf-8")
        assert '"encrypted": true' in manifest and "aes-256-gcm" in manifest
    raw = enc.read_bytes()
    assert secret.encode("utf-8") not in raw

    # --- 3. encrypted restore round-trips the data and keeps the device license ---
    ctx.customers.create("عميل بعد النسخة")
    assert len(ctx.customers.list()) == 2
    safety = ctx.backup.restore_backup(enc, password="صعب-1234")
    assert safety.exists()
    names = {c["name"] for c in ctx.customers.list()}
    assert len(names) == 1 and secret in names, names
    assert ctx.db.integrity_check().lower() == "ok"

    # --- 4. legacy plain backup still validates and reports encrypted=False ---
    plain = ctx.backup.create_backup(root / "snapshot-plain.nanobackup")
    val_plain = ctx.backup.validate_backup(plain)
    assert val_plain.valid and not val_plain.encrypted, val_plain
    ctx.backup.restore_backup(plain)

print("phase10_backup_encryption_smoke_test passed")
