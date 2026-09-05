"""Sale margin protection for dual-currency display.

Stored prices are always USD. When the cashier sells below average cost
(or purchase price fallback), the UI should warn — especially easy to miss
when amounts are shown in SYP after FX conversion.
"""

from __future__ import annotations

from nano_offline.core import currency


def unit_cost_usd(item: dict | None) -> float:
    if not item:
        return 0.0
    avg = float(item.get("average_cost") or 0)
    if avg > 0:
        return avg
    return float(item.get("purchase_price") or 0)


def check_sale_margin(
    *,
    unit_price_usd: float,
    item: dict | None,
    settings=None,
    min_margin_pct: float = 0.0,
) -> dict:
    """Return margin diagnostics for one sale unit price (USD stored).

    ``flag`` is True when selling at/below cost or below ``min_margin_pct``.
    """
    cost = unit_cost_usd(item)
    price = float(unit_price_usd or 0)
    if cost <= 0 or price < 0:
        return {
            "flag": False,
            "has_cost": cost > 0,
            "cost_usd": cost,
            "price_usd": price,
            "margin_pct": None,
            "message": "",
        }
    margin = price - cost
    margin_pct = (margin / cost) * 100.0 if cost else 0.0
    below_cost = price + 1e-9 < cost
    below_min = margin_pct < float(min_margin_pct or 0)
    flag = below_cost or below_min
    if not flag:
        return {
            "flag": False,
            "has_cost": True,
            "cost_usd": cost,
            "price_usd": price,
            "margin_pct": margin_pct,
            "message": "",
        }
    cost_disp = currency.format_amount(cost, settings)
    price_disp = currency.format_amount(price, settings)
    if below_cost:
        message = (
            f"بيع تحت التكلفة: السعر {price_disp} أقل من التكلفة {cost_disp}"
            f" (خسارة {currency.format_amount(cost - price, settings)} للوحدة)."
        )
    else:
        message = (
            f"هامش منخفض: {margin_pct:.1f}% فقط "
            f"(السعر {price_disp} / التكلفة {cost_disp})."
        )
    return {
        "flag": True,
        "has_cost": True,
        "cost_usd": cost,
        "price_usd": price,
        "margin_pct": margin_pct,
        "below_cost": below_cost,
        "message": message,
    }


def cart_margin_warnings(cart_rows: list[dict], settings=None) -> list[dict]:
    """``cart_rows`` items are dicts with ``item`` and optional ``qty``."""
    warnings: list[dict] = []
    for row in cart_rows:
        item = row.get("item") or {}
        price = float(item.get("selling_price") or 0)
        result = check_sale_margin(unit_price_usd=price, item=item, settings=settings)
        if result["flag"]:
            result = dict(result)
            result["item_id"] = item.get("id")
            result["name"] = item.get("name") or "—"
            result["qty"] = float(row.get("qty") or 1)
            warnings.append(result)
    return warnings


__all__ = ["check_sale_margin", "cart_margin_warnings", "unit_cost_usd"]
