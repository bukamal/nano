from __future__ import annotations

from nano_offline.core.database import Database


class StocktakeRepository:
    """Low-level storage for a stocktake session and its accumulated lines.

    A session is a scratchpad: nothing here touches `inventory_movements`
    or `items` while it is open (`status='open'`). Only `commit_session`
    performs the real accounting write, and it does so inside one
    `db.transaction()` so a crash mid-commit can never leave inventory
    half-adjusted. See StocktakeService for the higher-level flow (barcode
    resolution, permission checks, diff summaries) built on top of this.
    """

    def __init__(self, db: Database):
        self.db = db

    def create_session(self, *, notes: str | None = None) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO stocktake_sessions(status,notes) VALUES('open',?)",
                ((notes or "").strip() or None,),
            )
            return int(cur.lastrowid)

    def find_open_session(self) -> dict | None:
        """The most recent still-open session, if any.

        Used on entry to the stocktake screen so an app close mid-walk (a
        crash, the OS killing the process, someone just tapping back) never
        silently strands the counts already scanned -- there is at most one
        open session in normal use, but this picks the newest defensively
        in case that invariant is ever violated.
        """
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM stocktake_sessions WHERE status='open' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def get_session(self, session_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM stocktake_sessions WHERE id=?", (session_id,)).fetchone()
            return dict(row) if row else None

    def add_scan(self, session_id: int, item_id: int, *, qty: float = 1.0, system_qty_snapshot: float) -> None:
        """Accumulate ``qty`` onto this item's counted total for the session.

        ``system_qty_snapshot`` is only ever written on the *first* scan of
        this item in this session (the `DO UPDATE` below never touches it):
        it freezes the book quantity at that moment so the running diff
        shown to the person walking the shelves stays stable even if a sale
        posts concurrently elsewhere while they're still counting.
        """
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO stocktake_lines(session_id,item_id,counted_qty,system_qty_snapshot,scan_count,last_scanned_at)
                   VALUES(?,?,?,?,1,CURRENT_TIMESTAMP)
                   ON CONFLICT(session_id,item_id) DO UPDATE SET
                       counted_qty=counted_qty+excluded.counted_qty,
                       scan_count=scan_count+1,
                       last_scanned_at=CURRENT_TIMESTAMP""",
                (session_id, item_id, qty, system_qty_snapshot),
            )

    def set_counted_qty(self, session_id: int, item_id: int, counted_qty: float) -> None:
        """Manual correction of a line's running count (sidebar edit)."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE stocktake_lines SET counted_qty=? WHERE session_id=? AND item_id=?",
                (counted_qty, session_id, item_id),
            )

    def remove_line(self, session_id: int, item_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM stocktake_lines WHERE session_id=? AND item_id=?", (session_id, item_id))

    def list_lines(self, session_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT sl.*, i.name AS item_name, i.barcode AS item_barcode,
                          i.average_cost AS item_average_cost, u.abbreviation AS unit_abbreviation
                   FROM stocktake_lines sl
                   JOIN items i ON i.id=sl.item_id
                   LEFT JOIN units u ON u.id=i.base_unit_id
                   WHERE sl.session_id=?
                   ORDER BY sl.last_scanned_at DESC""",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def discard_session(self, session_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE stocktake_sessions SET status='discarded' WHERE id=? AND status='open'",
                (session_id,),
            )

    def commit_session(self, session_id: int, adjustments: list[dict], *, actor_username: str | None = None) -> None:
        """Write the real inventory effect for lines with a nonzero diff.

        ``adjustments`` is a list of {item_id, diff, unit_cost} -- already
        computed by StocktakeService (diff = counted_qty - system_qty at
        commit time, unit_cost = the item's current average cost). Every
        write happens in this single transaction:

        1. One `adjustment` row per nonzero diff in `inventory_movements`,
           dated today -- this is the audit trail shown in the item's
           movement history (`ItemRepository.movements`).
        2. `items.quantity`/`items.opening_quantity` shift by the same
           diff, matching exactly what `ItemRepository.create()` does for
           an item's opening balance. Shifting `opening_quantity` (not just
           `quantity`) matters: `AccountingRebuilder.rebuild_inventory`
           replays every invoice line from that baseline on every rebuild,
           so a diff that only touched `quantity` would silently vanish
           the next time a rebuild runs (e.g. after a backup restore).
           `average_cost` is deliberately left unchanged -- valuing the
           found/missing units at the item's own current average cost
           keeps the weighted average mathematically stable either way.
        3. The session is marked `committed`.
        """
        with self.db.transaction() as conn:
            session = conn.execute(
                "SELECT status FROM stocktake_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if session is None:
                raise ValueError("جلسة الجرد غير موجودة")
            if str(session["status"]) != "open":
                raise ValueError("جلسة الجرد ليست مفتوحة")

            today = conn.execute("SELECT date('now') AS d").fetchone()["d"]
            for adj in adjustments:
                item_id = int(adj["item_id"])
                diff = float(adj["diff"])
                if abs(diff) < 1e-9:
                    continue
                unit_cost = float(adj.get("unit_cost") or 0)
                conn.execute(
                    """INSERT INTO inventory_movements(item_id,movement_type,quantity_delta,unit_cost,value_delta,movement_date)
                       VALUES(?,?,?,?,?,?)""",
                    (item_id, "adjustment", diff, unit_cost, diff * unit_cost, today),
                )
                conn.execute(
                    """UPDATE items SET quantity=quantity+?, opening_quantity=opening_quantity+?,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (diff, diff, item_id),
                )

            conn.execute(
                "UPDATE stocktake_sessions SET status='committed', committed_at=CURRENT_TIMESTAMP WHERE id=?",
                (session_id,),
            )
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('commit','stocktake_session',?,?)",
                (session_id, f"lines={len(adjustments)} actor={actor_username or ''}"),
            )


__all__ = ["StocktakeRepository"]
