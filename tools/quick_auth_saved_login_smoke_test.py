from pathlib import Path
from tempfile import TemporaryDirectory

from nano_offline.core.database import Database, SCHEMA_VERSION
from nano_offline.services.auth_service import AuthService

assert SCHEMA_VERSION == 9

with TemporaryDirectory() as td:
    db = Database(Path(td) / "nano.db")
    db.initialize()
    auth = AuthService(db)
    auth.create_initial_admin("admin", "مدير النظام", "password123")

    auth.login("admin", "password123", remember_login=True, remember_username=True)
    assert auth.remembered_username() == "admin"
    assert auth.saved_login_enabled("admin")

    auth.set_quick_auth("pin", "4826", "password123")
    assert auth.quick_auth_info("admin") == "pin"
    auth.logout(clear_saved=False)
    assert auth.login_quick("admin", "pin", "4826").username == "admin"

    auth.set_quick_auth("pattern", "1596", "password123")
    auth.logout(clear_saved=False)
    assert auth.login_quick("admin", "pattern", "1596").username == "admin"

    auth.logout(clear_saved=False)
    assert auth.restore_saved_session() is not None
    auth.logout()
    assert not auth.saved_login_enabled("admin")

print("quick_auth_saved_login_smoke_test passed")
