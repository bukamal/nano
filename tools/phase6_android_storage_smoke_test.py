from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from qeid_offline.core.paths import app_data_dir, database_path, migrate_legacy_database

with tempfile.TemporaryDirectory(prefix="qeid_phase6_storage_") as td:
    root = Path(td)
    data = root / "android_data"
    previous = os.environ.get("FLET_APP_STORAGE_DATA")
    os.environ["FLET_APP_STORAGE_DATA"] = str(data)
    try:
        assert app_data_dir() == data
        assert database_path() == data / "qeid.db"
        assert data.is_dir()

        legacy = root / "legacy" / "qeid.db"
        legacy.parent.mkdir(parents=True)
        conn = sqlite3.connect(legacy)
        conn.execute("CREATE TABLE sample(value TEXT)")
        conn.execute("INSERT INTO sample VALUES('phase5-data')")
        conn.commit()
        conn.close()

        target = database_path()
        assert migrate_legacy_database(legacy, target)
        check = sqlite3.connect(target)
        assert check.execute("SELECT value FROM sample").fetchone()[0] == "phase5-data"
        check.close()
        assert not migrate_legacy_database(legacy, target), "existing Android data must never be overwritten"
    finally:
        if previous is None:
            os.environ.pop("FLET_APP_STORAGE_DATA", None)
        else:
            os.environ["FLET_APP_STORAGE_DATA"] = previous

print("phase6_android_storage_smoke_test passed")
