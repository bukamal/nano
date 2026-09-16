from __future__ import annotations

from nano_offline.core.asyncdb import Offloadable, blocking
from nano_offline.core.database import Database


class SettingsRepository(Offloadable):
    """Thin key/value accessor over the ``settings`` table.

    The schema already has an open-ended ``settings(key,value)`` table (used
    for ``currency``/``company_name``/etc.), so branding fields (logo,
    invoice accent color) live there too -- no schema migration needed.
    """

    def __init__(self, db: Database):
        self.db = db

    @blocking
    def get_all(self) -> dict[str, str]:
        with self.db.connect() as conn:
            return {str(r["key"]): str(r["value"]) for r in conn.execute("SELECT key,value FROM settings").fetchall()}

    @blocking
    def get(self, key: str, default: str = "") -> str:
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else default

    @blocking
    def set(self, key: str, value: str | None) -> None:
        with self.db.transaction() as conn:
            if value is None or value == "":
                conn.execute("DELETE FROM settings WHERE key=?", (key,))
            else:
                conn.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)),
                )

    @blocking
    def set_many(self, values: dict[str, str | None]) -> None:
        with self.db.transaction() as conn:
            for key, value in values.items():
                if value is None or value == "":
                    conn.execute("DELETE FROM settings WHERE key=?", (key,))
                else:
                    conn.execute(
                        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, str(value)),
                    )


__all__ = ["SettingsRepository"]
