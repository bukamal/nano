from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext

with tempfile.TemporaryDirectory(prefix="nano_phase5_auth_") as td:
    ctx = AppContext.create(Path(td) / "nano.db")
    assert not ctx.auth.has_users()
    admin_id = ctx.auth.create_initial_admin("admin", "المدير", "StrongPass1")
    assert ctx.auth.has_users()
    session = ctx.auth.login("admin", "StrongPass1")
    assert session.id == admin_id and session.role == "admin" and session.can("admin")

    with ctx.db.connect() as conn:
        row = conn.execute("SELECT password_hash,password_salt FROM users WHERE id=?", (admin_id,)).fetchone()
        assert row and row["password_hash"] != "StrongPass1" and len(row["password_salt"]) == 32

    viewer_id = ctx.auth.create_user(username="viewer", full_name="مشاهد", password="ViewerPass1", role="viewer")
    ctx.customers.create("عميل تدقيق", "0999", "عنوان")
    with ctx.db.connect() as conn:
        audit = conn.execute("SELECT username FROM audit_log WHERE entity_type='customer' ORDER BY id DESC LIMIT 1").fetchone()
        assert audit and audit["username"] == "admin", audit

    ctx.auth.logout()
    viewer = ctx.auth.login("viewer", "ViewerPass1")
    assert viewer.id == viewer_id and viewer.can("reports") and not viewer.can("finance") and not viewer.can("admin")
    try:
        ctx.auth.create_user(username="xuser", full_name="غير مسموح", password="LongPassword1", role="viewer")
    except PermissionError:
        pass
    else:
        raise AssertionError("viewer unexpectedly created a user")

    ctx.auth.logout()
    for _ in range(5):
        try:
            ctx.auth.login("viewer", "wrong-password")
        except (ValueError, PermissionError):
            pass
    try:
        ctx.auth.login("viewer", "ViewerPass1")
    except PermissionError as exc:
        assert "مقفل" in str(exc)
    else:
        raise AssertionError("lockout was not enforced")

print("phase5_auth_security_smoke_test passed")
