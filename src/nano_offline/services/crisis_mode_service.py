"""Crisis / Economic Emergency Mode.

When the parallel-market exchange rate is volatile (or electricity/internet
is unreliable), the owner can freeze the display rate and get proactive
suggestions for which products to reprice first.

Fully offline. Settings keys:
  crisis_mode_enabled   = "1" / "0"
  crisis_frozen_rate    = float string (SYP per USD at freeze time)
  crisis_activated_at   = ISO timestamp
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nano_offline.core.database import Database
    from nano_offline.repositories.settings_repository import SettingsRepository
    from nano_offline.repositories.item_repository import ItemRepository

from nano_offline.core import currency

CRISIS_ENABLED_KEY = "crisis_mode_enabled"
CRISIS_FROZEN_RATE_KEY = "crisis_frozen_rate"
CRISIS_ACTIVATED_AT_KEY = "crisis_activated_at"


@dataclass(slots=True, frozen=True)
class RepriceSuggestion:
    item_id: int
    name: str
    current_selling: float          # stored USD
    suggested_selling: float        # stored USD after uplift
    margin_pct: float
    reason: str


class CrisisModeService:
    def __init__(
        self,
        db: "Database",
        *,
        settings: "SettingsRepository",
        items: "ItemRepository",
    ) -> None:
        self.db = db
        self.settings = settings
        self.items = items

    # -- state ---------------------------------------------------------------

    def is_active(self) -> bool:
        return (self.settings.get(CRISIS_ENABLED_KEY) or "").strip().lower() in (
            "1", "true", "yes", "on",
        )

    def frozen_rate(self) -> float | None:
        raw = (self.settings.get(CRISIS_FROZEN_RATE_KEY) or "").strip()
        if not raw:
            return None
        try:
            v = float(raw)
            return v if v > 0 else None
        except ValueError:
            return None

    def activate(self, *, freeze_current_rate: bool = True) -> dict:
        """Turn crisis mode on. Optionally snapshot the current exchange rate."""
        current = currency.get_exchange_rate(self.settings)
        payload = {
            CRISIS_ENABLED_KEY: "1",
            CRISIS_ACTIVATED_AT_KEY: datetime.now().isoformat(timespec="seconds"),
        }
        if freeze_current_rate and current > 0:
            payload[CRISIS_FROZEN_RATE_KEY] = str(current)
            # Also lock the live rate so every screen stays consistent
            payload[currency.EXCHANGE_RATE_KEY] = str(current)
        self.settings.set_many(payload)
        return {"active": True, "frozen_rate": current if freeze_current_rate else None}

    def deactivate(self) -> dict:
        self.settings.set_many({
            CRISIS_ENABLED_KEY: "0",
            CRISIS_FROZEN_RATE_KEY: None,
            CRISIS_ACTIVATED_AT_KEY: None,
        })
        return {"active": False}

    def status(self) -> dict:
        return {
            "active": self.is_active(),
            "frozen_rate": self.frozen_rate(),
            "activated_at": self.settings.get(CRISIS_ACTIVATED_AT_KEY) or None,
            "current_rate": currency.get_exchange_rate(self.settings),
        }

    # -- suggestions ---------------------------------------------------------

    def reprice_suggestions(
        self,
        *,
        assumed_rate_increase_pct: float = 15.0,
        limit: int = 12,
    ) -> list[RepriceSuggestion]:
        """Suggest items whose margin would collapse if USD rose by the given %.

        Logic (deliberately simple & offline):
          - Only stock items with selling_price > 0 and average_cost > 0.
          - Current margin = (selling - cost) / selling.
          - After a rate shock the real cost in display currency rises, so
            we project a new selling price that restores the original margin.
        """
        if assumed_rate_increase_pct <= 0:
            return []

        factor = 1.0 + (assumed_rate_increase_pct / 100.0)
        out: list[RepriceSuggestion] = []

        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """SELECT id, name, selling_price, average_cost, purchase_price
                       FROM items
                       WHERE item_type='مخزون'
                         AND COALESCE(selling_price,0) > 0
                       ORDER BY selling_price * quantity DESC
                       LIMIT 80"""
                ).fetchall()
        except Exception:
            return []

        for r in rows:
            d = dict(r)
            sell = float(d["selling_price"] or 0)
            cost = float(d["average_cost"] or d["purchase_price"] or 0)
            if sell <= 0 or cost <= 0:
                continue
            margin = (sell - cost) / sell
            if margin < 0.05:
                # Already thin — force a stronger uplift
                new_sell = cost * factor * 1.12
                reason = "هامش ضعيف أصلاً — يحتاج حماية أقوى"
            else:
                # Keep the same margin after cost shock
                new_cost = cost * factor
                new_sell = new_cost / (1.0 - margin)
                reason = f"حماية الهامش الحالي ({margin*100:.0f}%)"

            uplift_pct = (new_sell - sell) / sell * 100.0
            if uplift_pct < 3:
                continue  # not worth suggesting

            out.append(
                RepriceSuggestion(
                    item_id=int(d["id"]),
                    name=str(d["name"]),
                    current_selling=sell,
                    suggested_selling=round(new_sell, 4),
                    margin_pct=round(margin * 100, 1),
                    reason=reason,
                )
            )
            if len(out) >= limit:
                break

        return out


__all__ = [
    "CrisisModeService",
    "RepriceSuggestion",
    "CRISIS_ENABLED_KEY",
    "CRISIS_FROZEN_RATE_KEY",
    "CRISIS_ACTIVATED_AT_KEY",
]
