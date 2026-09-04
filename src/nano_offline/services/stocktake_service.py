from __future__ import annotations

from nano_offline.core import barcode_quality
from nano_offline.core.database import Database
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.stocktake_repository import StocktakeRepository
from nano_offline.services.auth_service import AuthService

EPSILON = 1e-9


class StocktakeService:
    """High-level continuous-scan stocktake flow on top of `StocktakeRepository`.

    Owns everything a screen needs beyond raw storage: resolving a scanned
    code against the item catalog (reusing the exact same
    `ItemRepository.find_by_barcode` + unit-conversion logic POS already
    uses for a carton/case barcode), permission checks, checksum/duplicate
    detection on unknown codes, and building the diff-only review summary
    plus the actual commit write.
    """

    def __init__(self, db: Database, items: ItemRepository, stocktake: StocktakeRepository, auth: AuthService):
        self.db = db
        self.items = items
        self.stocktake = stocktake
        self.auth = auth

    # ---- session lifecycle -------------------------------------------- #

    def start_session(self, *, notes: str | None = None) -> int:
        self.auth.require("items")
        return self.stocktake.create_session(notes=notes)

    def find_resumable_session(self) -> dict | None:
        """A still-open session from a prior walk, with its line count
        attached, so the screen can offer "resume" instead of silently
        losing an interrupted stocktake (app closed mid-walk, etc.)."""
        self.auth.require("items")
        session = self.stocktake.find_open_session()
        if session is None:
            return None
        session = dict(session)
        session["line_count"] = len(self.stocktake.list_lines(int(session["id"])))
        return session

    def discard_session(self, session_id: int) -> None:
        self.auth.require("items")
        self.stocktake.discard_session(session_id)

    # ---- scanning ------------------------------------------------------ #

    def scan(self, session_id: int, code: str) -> dict:
        """Resolve one scanned code and, on a match, accumulate it onto the
        session. Returns a small result dict the view renders feedback
        from -- never raises for an ordinary "not found"/"bad checksum"
        outcome, since those are expected parts of the scan loop, not
        exceptional failures.

        Result shapes:
          {"status": "added", "item": <row>, "qty_delta": float, "counted_qty": float}
          {"status": "checksum", "code": code}          -- likely a misread, ask to rescan
          {"status": "similar", "code": code, "names": [...]}  -- close to an existing item
          {"status": "not_found", "code": code}
        """
        self.auth.require("items")
        clean = (code or "").strip()
        if not clean:
            return {"status": "not_found", "code": clean}

        warning = barcode_quality.checksum_warning(clean)
        if warning:
            return {"status": "checksum", "code": clean, "message": warning}

        found = self.items.find_by_barcode(clean)
        if not found:
            similar = self.items.find_similar_barcodes(clean)
            if similar:
                return {"status": "similar", "code": clean, "names": similar}
            return {"status": "not_found", "code": clean}

        if found.get("item_type") == "خدمة":
            # Services carry no physical stock -- nothing for a stocktake
            # to count. Surfaced distinctly so the screen can explain why
            # the scan was accepted but not added, instead of looking like
            # a silent no-op.
            return {"status": "service", "item": found}

        item_id = int(found["id"])
        qty_delta = 1.0
        matched_unit_id = found.get("matched_unit_id")
        if matched_unit_id:
            unit_row = next(
                (u for u in self.items.units(item_id) if int(u["id"]) == int(matched_unit_id)), None
            )
            if unit_row:
                qty_delta = float(unit_row.get("conversion_factor") or 1)

        system_qty = float(found.get("quantity") or 0)
        self.stocktake.add_scan(session_id, item_id, qty=qty_delta, system_qty_snapshot=system_qty)

        line = next((ln for ln in self.stocktake.list_lines(session_id) if int(ln["item_id"]) == item_id), None)
        counted_qty = float(line["counted_qty"]) if line else qty_delta
        return {"status": "added", "item": found, "qty_delta": qty_delta, "counted_qty": counted_qty}

    def set_counted_qty(self, session_id: int, item_id: int, counted_qty: float) -> None:
        self.auth.require("items")
        if counted_qty < 0:
            raise ValueError("الكمية لا يمكن أن تكون سالبة")
        self.stocktake.set_counted_qty(session_id, item_id, counted_qty)

    def remove_line(self, session_id: int, item_id: int) -> None:
        self.auth.require("items")
        self.stocktake.remove_line(session_id, item_id)

    def lines(self, session_id: int) -> list[dict]:
        return self.stocktake.list_lines(session_id)

    # ---- review + commit ------------------------------------------------ #

    def diff_summary(self, session_id: int, *, only_diffs: bool = True) -> list[dict]:
        """Lines annotated with `diff` (counted - book) and `value_diff`
        (diff priced at the item's current average cost), sorted by the
        financial size of the difference -- the ones worth double-checking
        first. `only_diffs=False` returns every scanned line, matched-book
        rows included, for the always-visible sidebar list.
        """
        rows = self.stocktake.list_lines(session_id)
        out = []
        for row in rows:
            counted = float(row["counted_qty"])
            system = float(row["system_qty_snapshot"])
            diff = counted - system
            unit_cost = float(row.get("item_average_cost") or 0)
            enriched = dict(row)
            enriched["diff"] = diff
            enriched["value_diff"] = diff * unit_cost
            if only_diffs and abs(diff) < EPSILON:
                continue
            out.append(enriched)
        out.sort(key=lambda r: abs(r["value_diff"]), reverse=True)
        return out

    def commit(self, session_id: int) -> int:
        """Recompute diffs from the *current* book quantity (not the
        session's frozen snapshot) so a concurrent sale/purchase that
        happened while the session was open is respected -- the
        adjustment only ever accounts for the gap the count actually
        found, never re-applies stock movements that already posted.
        Returns the number of lines that produced a real adjustment.
        """
        session_actor = self.auth.require("items")
        rows = self.stocktake.list_lines(session_id)
        adjustments: list[dict] = []
        for row in rows:
            item = self.items.get(int(row["item_id"]))
            if item is None:
                continue
            current_system_qty = float(item.get("quantity") or 0)
            counted = float(row["counted_qty"])
            diff = counted - current_system_qty
            if abs(diff) < EPSILON:
                continue
            adjustments.append({
                "item_id": int(row["item_id"]),
                "diff": diff,
                "unit_cost": float(item.get("average_cost") or 0),
            })
        self.stocktake.commit_session(session_id, adjustments, actor_username=session_actor.username)
        return len(adjustments)


__all__ = ["StocktakeService"]
