"""End-of-day cash drawer close (offline).

Compares book cash (ledger CASH) to a counted amount, records the session
in settings + audit_log, and optionally posts a small ledger adjustment
so the book matches the count.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from nano_offline.core.database import Database

LAST_CLOSE_KEY = "cash_day_close_last_json"


class CashDayCloseService:
    def __init__(self, db: Database):
        self.db = db

    def book_cash(self) -> float:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(debit-credit),0) FROM ledger_entries WHERE account_code='CASH'"
            ).fetchone()
            return float(row[0] or 0)

    def today_cash_movement(self) -> dict:
        today = date.today().isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT
                     COALESCE(SUM(debit),0) AS inflow,
                     COALESCE(SUM(credit),0) AS outflow
                   FROM ledger_entries
                   WHERE account_code='CASH' AND entry_date=?""",
                (today,),
            ).fetchone()
            inflow = float(row[0] or 0)
            outflow = float(row[1] or 0)
        return {"date": today, "inflow": inflow, "outflow": outflow, "net": inflow - outflow}

    def last_close(self) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (LAST_CLOSE_KEY,)
            ).fetchone()
        if not row or not row[0]:
            return None
        try:
            return json.loads(str(row[0]))
        except Exception:
            return None

    def close_day(
        self,
        *,
        counted_cash: float,
        note: str = "",
        post_adjustment: bool = True,
        username: str | None = None,
        user_id: int | None = None,
    ) -> dict:
        """Record day close. Returns summary dict including variance."""
        book = self.book_cash()
        counted = float(counted_cash or 0)
        variance = counted - book
        movement = self.today_cash_movement()
        today = date.today().isoformat()
        now = datetime.now().isoformat(timespec="seconds")

        payload = {
            "date": today,
            "closed_at": now,
            "book_cash": book,
            "counted_cash": counted,
            "variance": variance,
            "inflow": movement["inflow"],
            "outflow": movement["outflow"],
            "note": (note or "").strip(),
            "username": username or "",
        }

        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO settings(key,value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (LAST_CLOSE_KEY, json.dumps(payload, ensure_ascii=False)),
            )
            conn.execute(
                """INSERT INTO audit_log(action,entity_type,entity_id,details,user_id,username)
                   VALUES('day_close','cash',NULL,?,?,?)""",
                (
                    json.dumps(
                        {
                            "book": book,
                            "counted": counted,
                            "variance": variance,
                            "note": payload["note"],
                        },
                        ensure_ascii=False,
                    ),
                    user_id,
                    username,
                ),
            )
            if post_adjustment and abs(variance) > 1e-6:
                # Align book to counted: positive variance => debit CASH, negative => credit
                if variance > 0:
                    conn.execute(
                        """INSERT INTO ledger_entries(
                               entry_date,account_code,debit,credit,source_type,source_id,description
                           ) VALUES(?,?,?,?, 'day_close', NULL, ?)""",
                        (today, "CASH", abs(variance), 0.0, f"تسوية إغلاق يوم {today}"),
                    )
                else:
                    conn.execute(
                        """INSERT INTO ledger_entries(
                               entry_date,account_code,debit,credit,source_type,source_id,description
                           ) VALUES(?,?,?,?, 'day_close', NULL, ?)""",
                        (today, "CASH", 0.0, abs(variance), f"تسوية إغلاق يوم {today}"),
                    )
                payload["adjustment_posted"] = True
            else:
                payload["adjustment_posted"] = False

        payload["book_cash_after"] = self.book_cash()
        return payload


__all__ = ["CashDayCloseService", "LAST_CLOSE_KEY"]
