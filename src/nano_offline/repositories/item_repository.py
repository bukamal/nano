from __future__ import annotations

import sqlite3

from nano_offline.core.database import Database


class ItemRepository:
    def __init__(self, db: Database):
        self.db = db

    def list(self, search: str = "", limit: int | None = None, offset: int = 0) -> list[dict]:
        """List items, optionally filtered by name/barcode.

        ``limit``/``offset`` are optional so existing callers that need the
        full set (stats, exports, pickers) keep working unchanged -- but any
        screen rendering this as a scrollable list should pass a ``limit``
        (e.g. 50) and page with ``offset`` instead of pulling every row and
        building a widget for each one. That's what actually keeps the UI
        fast once there are thousands of items, not just a fast query.
        """
        sql = """
        SELECT i.*, c.name AS category_name, u.name AS unit_name, u.abbreviation AS unit_abbreviation,
            (
                EXISTS(SELECT 1 FROM invoice_lines WHERE item_id = i.id)
                OR EXISTS(SELECT 1 FROM inventory_movements WHERE item_id = i.id)
            ) AS has_activity
        FROM items i
        LEFT JOIN categories c ON c.id=i.category_id
        LEFT JOIN units u ON u.id=i.base_unit_id
        """
        params: list = []
        search = search.strip()
        if search:
            # A leading "%" wildcard can't use the name index either way,
            # but matching barcode too means this stays a full scan -- fine
            # at current data sizes given the new item_id/invoice_lines
            # index above; worth an FTS5 table if item counts get very large.
            sql += " WHERE i.name LIKE ? OR i.barcode LIKE ?"
            params.extend([f"%{search}%", f"%{search}%"])
        sql += " ORDER BY i.name"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get(self, item_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT i.*, c.name AS category_name, u.name AS unit_name, u.abbreviation AS unit_abbreviation
                   FROM items i
                   LEFT JOIN categories c ON c.id=i.category_id
                   LEFT JOIN units u ON u.id=i.base_unit_id
                   WHERE i.id=?""",
                (item_id,),
            ).fetchone()
            return dict(row) if row else None

    def pos_catalog(self, limit_best_sellers: int = 12) -> list[dict]:
        """Items ordered for the POS grid: best sellers first, then the rest A-Z.

        "Best seller" is derived live from posted sale invoice lines rather
        than a stored counter, so the ranking always reflects real history
        without a separate table to keep in sync.
        """
        sql = """
        SELECT i.*, c.name AS category_name, u.abbreviation AS unit_abbreviation,
               COALESCE(SUM(CASE WHEN inv.type='sale' THEN il.quantity_in_base ELSE 0 END), 0) AS sold_qty
        FROM items i
        LEFT JOIN categories c ON c.id = i.category_id
        LEFT JOIN units u ON u.id = i.base_unit_id
        LEFT JOIN invoice_lines il ON il.item_id = i.id
        LEFT JOIN invoices inv ON inv.id = il.invoice_id
        GROUP BY i.id
        ORDER BY sold_qty DESC, i.name
        """
        with self.db.connect() as conn:
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
        best = [r for r in rows if r["sold_qty"] > 0][: max(0, int(limit_best_sellers))]
        best_ids = {r["id"] for r in best}
        rest = sorted((r for r in rows if r["id"] not in best_ids), key=lambda r: r["name"])
        return best + rest

    def purchased_by_party(self, party_type: str, party_id: int, limit: int = 20) -> list[dict]:
        """Items a given customer/supplier has previously transacted, most-frequent first.

        Powers the "مشترياته السابقة" quick filter on the invoice editor --
        derived live from posted invoice lines, same approach as
        ``pos_catalog``'s best-seller ranking, so it never drifts from
        actual history.
        """
        id_column = "customer_id" if party_type == "sale" else "supplier_id"
        sql = f"""
        SELECT i.*, c.name AS category_name, u.abbreviation AS unit_abbreviation,
               COUNT(*) AS times_bought, MAX(inv.invoice_date) AS last_bought
        FROM invoice_lines il
        JOIN invoices inv ON inv.id = il.invoice_id
        JOIN items i ON i.id = il.item_id
        LEFT JOIN categories c ON c.id = i.category_id
        LEFT JOIN units u ON u.id = i.base_unit_id
        WHERE inv.type = ? AND inv.{id_column} = ? AND inv.status = 'posted'
        GROUP BY i.id
        ORDER BY times_bought DESC, last_bought DESC
        LIMIT ?
        """
        with self.db.connect() as conn:
            rows = conn.execute(sql, (party_type, party_id, int(limit))).fetchall()
            return [dict(r) for r in rows]

    def find_by_barcode(self, barcode: str) -> dict | None:
        """Resolve ``barcode`` against an item's primary code (``items.barcode``)
        or any of its secondary codes (``item_barcodes`` -- e.g. a carton
        code alongside the piece code). Either way returns the same item
        row, plus ``matched_unit_id``/``matched_label`` when the match came
        from a secondary code registered against a specific selling unit,
        so a caller (POS) can add the right unit/quantity instead of
        always assuming the base unit.
        """
        code = (barcode or "").strip()
        if not code:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT i.*, c.name AS category_name, u.name AS unit_name, u.abbreviation AS unit_abbreviation
                   FROM items i
                   LEFT JOIN categories c ON c.id=i.category_id
                   LEFT JOIN units u ON u.id=i.base_unit_id
                   WHERE i.barcode=?""",
                (code,),
            ).fetchone()
            if row is not None:
                result = dict(row)
                result["matched_unit_id"] = None
                result["matched_label"] = None
                return result
            alt = conn.execute(
                """SELECT i.*, c.name AS category_name, u.name AS unit_name, u.abbreviation AS unit_abbreviation,
                          ib.unit_id AS matched_unit_id, ib.label AS matched_label
                   FROM item_barcodes ib
                   JOIN items i ON i.id=ib.item_id
                   LEFT JOIN categories c ON c.id=i.category_id
                   LEFT JOIN units u ON u.id=i.base_unit_id
                   WHERE ib.barcode=?""",
                (code,),
            ).fetchone()
            return dict(alt) if alt else None

    def list_barcodes(self, item_id: int) -> list[dict]:
        """Secondary codes registered for an item (primary code lives on
        the item row itself and is not included here)."""
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT ib.*, u.name AS unit_name
                   FROM item_barcodes ib
                   LEFT JOIN units u ON u.id=ib.unit_id
                   WHERE ib.item_id=? ORDER BY ib.id""",
                (item_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_barcode(self, item_id: int, barcode: str, *, unit_id: int | None = None, label: str | None = None) -> int:
        code = (barcode or "").strip()
        if not code:
            raise ValueError("الباركود مطلوب")
        with self.db.transaction() as conn:
            self._check_barcode_free(conn, code, exclude_item_id=item_id)
            try:
                cur = conn.execute(
                    "INSERT INTO item_barcodes(item_id,barcode,unit_id,label) VALUES(?,?,?,?)",
                    (item_id, code, unit_id, (label or "").strip() or None),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("هذا الباركود مسجّل بالفعل لهذه المادة") from exc
            return int(cur.lastrowid)

    def remove_barcode(self, barcode_row_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM item_barcodes WHERE id=?", (barcode_row_id,))

    def find_similar_barcodes(self, code: str, *, exclude_item_id: int | None = None) -> list[str]:
        """Item names whose primary or secondary barcode is a likely
        typo/scan-glitch away from ``code`` (see
        ``core.barcode_quality.find_similar``). Advisory only -- callers
        decide whether to warn and let the user proceed.
        """
        code = (code or "").strip()
        if not code:
            return []
        from nano_offline.core.barcode_quality import find_similar

        with self.db.connect() as conn:
            candidates: list[tuple[str, str]] = []
            for row in conn.execute("SELECT barcode, name, id FROM items WHERE barcode IS NOT NULL AND TRIM(barcode)<>''"):
                if exclude_item_id is not None and int(row["id"]) == int(exclude_item_id):
                    continue
                candidates.append((row["barcode"], row["name"]))
            for row in conn.execute(
                """SELECT ib.barcode, i.name, i.id
                   FROM item_barcodes ib JOIN items i ON i.id=ib.item_id"""
            ):
                if exclude_item_id is not None and int(row["id"]) == int(exclude_item_id):
                    continue
                candidates.append((row["barcode"], row["name"]))
        return find_similar(code, candidates)

    def find_similar_names(self, name: str, *, exclude_item_id: int | None = None) -> list[str]:
        """Existing item names that look like a likely duplicate of
        ``name`` -- an exact match once case/whitespace is normalized, or
        a close textual match (e.g. a typo, extra space, or singular vs.
        plural spelling). Advisory only, same pattern as
        ``find_similar_barcodes``: callers warn and let the user proceed,
        since two genuinely different products can share a very similar
        name (e.g. two sizes/colors entered as separate items).
        """
        import difflib

        normalized = " ".join((name or "").strip().split()).casefold()
        if not normalized:
            return []
        matches: list[str] = []
        with self.db.connect() as conn:
            for row in conn.execute("SELECT id, name FROM items"):
                if exclude_item_id is not None and int(row["id"]) == int(exclude_item_id):
                    continue
                other_raw = row["name"] or ""
                other = " ".join(other_raw.strip().split()).casefold()
                if not other:
                    continue
                if other == normalized or difflib.SequenceMatcher(None, normalized, other).ratio() >= 0.84:
                    matches.append(other_raw)
        return matches

    @staticmethod
    def _check_barcode_free(conn, code: str, *, exclude_item_id: int | None) -> None:
        """Raise if ``code`` is already used as anyone *else's* primary or
        secondary barcode. Needed because the two UNIQUE indexes
        (``items.barcode`` and ``item_barcodes.barcode``) each guard their
        own table only -- SQLite can't express a uniqueness constraint
        that spans both, so the cross-table check happens here before
        either insert. ``exclude_item_id`` lets an item keep (or promote
        to primary) a code it already legitimately holds, on itself,
        without tripping over its own existing row.
        """
        params: tuple = (code,) if exclude_item_id is None else (code, exclude_item_id)
        clash = conn.execute(
            "SELECT 1 FROM items WHERE barcode=?" + ("" if exclude_item_id is None else " AND id<>?"),
            params,
        ).fetchone()
        if clash is None:
            clash = conn.execute(
                "SELECT 1 FROM item_barcodes WHERE barcode=?" + ("" if exclude_item_id is None else " AND item_id<>?"),
                params,
            ).fetchone()
        if clash is not None:
            raise ValueError("هذا الباركود مستخدم بالفعل لمادة أخرى")

    def units(self, item_id: int) -> list[dict]:
        """Return allowed invoice units with authoritative conversion factors."""
        with self.db.connect() as conn:
            item = conn.execute("SELECT base_unit_id FROM items WHERE id=?", (item_id,)).fetchone()
            if item is None:
                return []
            result: list[dict] = []
            base_id = item["base_unit_id"]
            if base_id is not None:
                u = conn.execute("SELECT * FROM units WHERE id=?", (base_id,)).fetchone()
                if u:
                    d = dict(u)
                    d["conversion_factor"] = 1.0
                    d["is_base"] = True
                    result.append(d)
            rows = conn.execute(
                """SELECT u.*, iu.conversion_factor
                   FROM item_units iu JOIN units u ON u.id=iu.unit_id
                   WHERE iu.item_id=? ORDER BY u.name""",
                (item_id,),
            ).fetchall()
            seen = {int(x["id"]) for x in result}
            for row in rows:
                if int(row["id"]) in seen:
                    continue
                d = dict(row)
                d["is_base"] = False
                result.append(d)
            return result

    def activity_summary(self, item_id: int) -> dict:
        """Return sales/purchase and stock metrics for an item."""
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT i.id, i.name, i.item_type, i.quantity, i.average_cost, i.purchase_price, i.selling_price,
                          COALESCE(SUM(CASE WHEN inv.type='sale' THEN il.quantity_in_base ELSE 0 END),0) AS sold_qty,
                          COALESCE(SUM(CASE WHEN inv.type='purchase' THEN il.quantity_in_base ELSE 0 END),0) AS purchased_qty,
                          COUNT(DISTINCT CASE WHEN inv.type='sale' THEN inv.id END) AS sale_count,
                          COUNT(DISTINCT CASE WHEN inv.type='purchase' THEN inv.id END) AS purchase_count,
                          MAX(CASE WHEN inv.type='sale' THEN inv.invoice_date END) AS last_sale_date,
                          MAX(CASE WHEN inv.type='purchase' THEN inv.invoice_date END) AS last_purchase_date
                   FROM items i
                   LEFT JOIN invoice_lines il ON il.item_id=i.id
                   LEFT JOIN invoices inv ON inv.id=il.invoice_id AND inv.status='posted'
                   WHERE i.id=?
                   GROUP BY i.id""",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("المادة غير موجودة")
            result = dict(row)
            qty = float(result.get("quantity") or 0)
            avg = float(result.get("average_cost") or 0)
            sell = float(result.get("selling_price") or 0)
            result["inventory_cost_value"] = qty * avg
            result["inventory_sale_value"] = qty * sell
            return result

    def movements(self, item_id: int, limit: int = 30) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT m.*, inv.type AS invoice_type, inv.reference AS invoice_reference
                   FROM inventory_movements m
                   LEFT JOIN invoices inv ON inv.id=m.invoice_id
                   WHERE m.item_id=?
                   ORDER BY m.movement_date DESC, m.id DESC
                   LIMIT ?""",
                (item_id, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def create(
        self,
        *,
        name: str,
        category_id: int | None = None,
        item_type: str = "مخزون",
        purchase_price: float = 0,
        selling_price: float = 0,
        quantity: float = 0,
        base_unit_id: int | None = None,
        item_units: list[dict] | None = None,
        barcode: str | None = None,
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("اسم المادة مطلوب")
        if item_type not in {"مخزون", "خدمة"}:
            raise ValueError("نوع المادة غير صحيح")
        initial_qty = 0.0 if item_type == "خدمة" else float(quantity or 0)
        avg = float(purchase_price or 0)
        if initial_qty < 0 or avg < 0 or float(selling_price or 0) < 0:
            raise ValueError("القيم المالية أو الكمية غير صحيحة")
        code = (barcode or "").strip() or None
        with self.db.transaction() as conn:
            if code is not None:
                self._check_barcode_free(conn, code, exclude_item_id=None)
            try:
                cur = conn.execute(
                    """INSERT INTO items(
                           name,category_id,item_type,purchase_price,selling_price,quantity,average_cost,
                           opening_quantity,opening_unit_cost,base_unit_id,barcode
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        name, category_id, item_type, avg, float(selling_price or 0), initial_qty, avg,
                        initial_qty, avg if initial_qty else 0.0, base_unit_id, code,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "barcode" in str(exc):
                    raise ValueError("هذا الباركود مستخدم بالفعل لمادة أخرى") from exc
                raise
            item_id = int(cur.lastrowid)
            self._replace_units(conn, item_id, base_unit_id, item_units or [])
            if initial_qty:
                conn.execute(
                    """INSERT INTO inventory_movements(item_id,movement_type,quantity_delta,unit_cost,value_delta,movement_date)
                       VALUES(?,?,?,?,?,date('now'))""",
                    (item_id, "adjustment", initial_qty, avg, initial_qty * avg),
                )
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('create','item',?,?)",
                (item_id, name),
            )
            return item_id

    def update(
        self,
        item_id: int,
        *,
        name: str,
        category_id: int | None = None,
        item_type: str = "مخزون",
        purchase_price: float = 0,
        selling_price: float = 0,
        base_unit_id: int | None = None,
        item_units: list[dict] | None = None,
        barcode: str | None = None,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("اسم المادة مطلوب")
        if item_type not in {"مخزون", "خدمة"}:
            raise ValueError("نوع المادة غير صحيح")
        code = (barcode or "").strip() or None
        with self.db.transaction() as conn:
            old = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if old is None:
                raise ValueError("المادة غير موجودة")
            if old["item_type"] != item_type:
                used = conn.execute("SELECT 1 FROM invoice_lines WHERE item_id=? LIMIT 1", (item_id,)).fetchone()
                if used:
                    raise ValueError("لا يمكن تغيير نوع المادة بعد استخدامها في فاتورة")
            if code is not None:
                self._check_barcode_free(conn, code, exclude_item_id=item_id)
            try:
                conn.execute(
                    """UPDATE items SET name=?,category_id=?,item_type=?,purchase_price=?,selling_price=?,base_unit_id=?,barcode=?,updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (name, category_id, item_type, float(purchase_price or 0), float(selling_price or 0), base_unit_id, code, item_id),
                )
            except sqlite3.IntegrityError as exc:
                if "barcode" in str(exc):
                    raise ValueError("هذا الباركود مستخدم بالفعل لمادة أخرى") from exc
                raise
            self._replace_units(conn, item_id, base_unit_id, item_units or [])
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update','item',?,?)",
                (item_id, name),
            )

    def delete(self, item_id: int) -> None:
        # Deliberately narrow: safe only for an item that has never
        # appeared on an invoice and never generated an inventory movement
        # (both ON DELETE RESTRICT in the schema). In practice this covers
        # a service item that was never invoiced, or a stock item created
        # with a zero opening quantity that was never used — i.e. genuine
        # "added by mistake" cases, not an undo for real business history.
        # A non-zero opening quantity already creates an 'adjustment'
        # movement row at creation time (see create()), so such an item is
        # excluded here even before any invoice ever touches it.
        with self.db.transaction() as conn:
            invoiced = conn.execute("SELECT 1 FROM invoice_lines WHERE item_id=? LIMIT 1", (item_id,)).fetchone()
            moved = conn.execute("SELECT 1 FROM inventory_movements WHERE item_id=? LIMIT 1", (item_id,)).fetchone()
            if invoiced or moved:
                raise ValueError("لا يمكن حذف المادة لوجود حركات مخزون أو فواتير مرتبطة بها")
            conn.execute("DELETE FROM items WHERE id=?", (item_id,))
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('delete','item',?,NULL)",
                (item_id,),
            )

    @staticmethod
    def _replace_units(conn, item_id: int, base_unit_id: int | None, item_units: list[dict]) -> None:
        conn.execute("DELETE FROM item_units WHERE item_id=?", (item_id,))
        seen: set[int] = set()
        for raw in item_units:
            unit_id = int(raw["unit_id"])
            factor = float(raw.get("conversion_factor", 1))
            if factor <= 0:
                raise ValueError("معامل تحويل الوحدة يجب أن يكون أكبر من صفر")
            if base_unit_id is not None and int(base_unit_id) == unit_id:
                continue
            if unit_id in seen:
                continue
            seen.add(unit_id)
            conn.execute(
                "INSERT INTO item_units(item_id,unit_id,conversion_factor) VALUES(?,?,?)",
                (item_id, unit_id, factor),
            )
