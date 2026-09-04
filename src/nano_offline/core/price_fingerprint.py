from __future__ import annotations

"""Purchase price fingerprint -- offline anomaly detection for purchase entry.

Every purchase line already carries enough to build a per-item price history
with no schema change: ``invoice_lines.unit_price`` (always stored in USD --
see ``core/currency.py``) together with ``conversion_factor`` normalizes to a
price *per base unit*, so a line entered as "1 box" and another entered as
"12 pieces" of the same item are still comparable.

The check prefers the same supplier's own recent history (catches a specific
supplier quietly raising prices, or a typo against what that supplier usually
charges). If that supplier doesn't have enough history yet, it falls back to
the item's price across all suppliers, so a first order from a brand-new
supplier still gets a useful baseline instead of no check at all.

Pure read-only SQL, no network, no external dependency -- consistent with the
rest of the app's fully offline design.
"""

from nano_offline.core.database import Database

_MIN_SAMPLES = 2


def check_purchase_price(
    db: Database,
    *,
    item_id: int | None,
    unit_price: float,
    conversion_factor: float = 1.0,
    supplier_id: int | None = None,
    exclude_invoice_id: int | None = None,
    lookback: int = 5,
    threshold: float = 0.20,
) -> dict:
    """Compare a purchase line's price per base unit against recent history.

    Returns a dict with at least ``flag`` (bool). When there's enough history
    it also includes ``has_history``, ``sample_size``, ``avg_price`` (USD per
    base unit), ``deviation_pct``, ``scope`` (``"المورد"`` or ``"عام"``) and a
    ready-to-display Arabic ``message``.
    """
    if not item_id or conversion_factor <= 0 or unit_price < 0:
        return {"flag": False, "has_history": False}

    new_price_per_base = float(unit_price) / float(conversion_factor)

    def _history(supplier_only: bool) -> list[float]:
        sql = (
            "SELECT il.unit_price / il.conversion_factor AS ppb "
            "FROM invoice_lines il "
            "JOIN invoices i ON i.id = il.invoice_id "
            "WHERE i.type='purchase' AND il.item_id=? AND il.conversion_factor > 0"
        )
        params: list[object] = [item_id]
        if supplier_only:
            sql += " AND i.supplier_id=?"
            params.append(supplier_id)
        if exclude_invoice_id:
            sql += " AND i.id != ?"
            params.append(exclude_invoice_id)
        sql += " ORDER BY i.invoice_date DESC, i.id DESC LIMIT ?"
        params.append(max(1, int(lookback)))
        with db.connect() as conn:
            return [float(r[0]) for r in conn.execute(sql, params).fetchall()]

    samples: list[float] = []
    scope = "عام"
    if supplier_id:
        samples = _history(True)
        scope = "المورد"
    if len(samples) < _MIN_SAMPLES:
        fallback = _history(False)
        if len(fallback) > len(samples):
            samples = fallback
            scope = "عام"

    if len(samples) < _MIN_SAMPLES:
        return {"flag": False, "has_history": False, "sample_size": len(samples)}

    avg = sum(samples) / len(samples)
    if avg <= 1e-9:
        return {"flag": False, "has_history": True, "sample_size": len(samples)}

    deviation = (new_price_per_base - avg) / avg
    flagged = abs(deviation) >= threshold
    direction = "أعلى" if deviation > 0 else "أقل"
    message = (
        f"السعر {direction} بـ {abs(deviation) * 100:.0f}٪ من متوسط {scope} "
        f"لآخر {len(samples)} فاتورة (${avg:.2f} للوحدة الأساسية)"
    )
    return {
        "flag": flagged,
        "has_history": True,
        "sample_size": len(samples),
        "avg_price": avg,
        "deviation_pct": deviation,
        "scope": scope,
        "message": message,
    }


__all__ = ["check_purchase_price"]
