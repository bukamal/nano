"""Party Trust Score — offline reliability rating for customers & suppliers.

Score 0–100 computed purely from local history:
  - Payment speed (how quickly outstanding balances are cleared)
  - Overdue frequency
  - Transaction volume & recency
  - Return / credit-note rate (if present)

No schema change. Score is calculated on demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nano_offline.core.database import Database


@dataclass(slots=True, frozen=True)
class TrustScore:
    party_id: int
    party_type: str          # customer | supplier
    score: int               # 0–100
    label: str               # ممتاز | جيد | متوسط | ضعيف | جديد
    color_key: str           # success | info | warning | danger | muted
    factors: dict            # breakdown for UI tooltip
    computed_at: str


_LABELS = [
    (85, "ممتاز", "success"),
    (70, "جيد", "info"),
    (50, "متوسط", "warning"),
    (25, "ضعيف", "danger"),
    (0, "جديد", "muted"),
]


class PartyTrustService:
    def __init__(self, db: "Database") -> None:
        self.db = db

    def score(self, party_id: int, *, party_type: str = "customer") -> TrustScore:
        """Compute trust score for one party."""
        if party_type not in ("customer", "supplier"):
            raise ValueError("party_type must be customer or supplier")

        table = "customers" if party_type == "customer" else "suppliers"
        id_col = "customer_id" if party_type == "customer" else "supplier_id"
        inv_type = "sale" if party_type == "customer" else "purchase"

        factors: dict = {
            "invoice_count": 0,
            "paid_ratio": 0.0,
            "avg_days_to_pay": None,
            "overdue_count": 0,
            "recency_days": None,
            "volume": 0.0,
        }

        try:
            with self.db.connect() as conn:
                party = conn.execute(
                    f"SELECT id, balance, created_at FROM {table} WHERE id=?",
                    (party_id,),
                ).fetchone()
                if party is None:
                    return self._empty(party_id, party_type)

                inv_rows = conn.execute(
                    f"""SELECT id, invoice_date, total, paid_amount,
                               MAX(total - paid_amount, 0) AS remaining
                        FROM invoices
                        WHERE type=? AND {id_col}=? AND status='posted'
                        ORDER BY invoice_date DESC""",
                    (inv_type, party_id),
                ).fetchall()
        except Exception:
            return self._empty(party_id, party_type)

        invoices = [dict(r) for r in inv_rows]
        count = len(invoices)
        factors["invoice_count"] = count

        if count == 0:
            return TrustScore(
                party_id=party_id,
                party_type=party_type,
                score=50,
                label="جديد",
                color_key="muted",
                factors=factors,
                computed_at=datetime.now().isoformat(timespec="seconds"),
            )

        total_vol = sum(float(i["total"] or 0) for i in invoices)
        paid_vol = sum(float(i["paid_amount"] or 0) for i in invoices)
        factors["volume"] = total_vol
        factors["paid_ratio"] = (paid_vol / total_vol) if total_vol > 0 else 1.0

        # Recency
        last_date = invoices[0].get("invoice_date")
        if last_date:
            try:
                last = date.fromisoformat(str(last_date)[:10])
                factors["recency_days"] = (date.today() - last).days
            except Exception:
                pass

        # Overdue: remaining > 0 and older than 30 days
        overdue = 0
        days_to_pay_samples: list[float] = []
        today = date.today()
        for inv in invoices:
            remaining = float(inv.get("remaining") or 0)
            inv_date_s = inv.get("invoice_date")
            if not inv_date_s:
                continue
            try:
                inv_d = date.fromisoformat(str(inv_date_s)[:10])
            except Exception:
                continue
            age = (today - inv_d).days
            if remaining > 1 and age > 30:
                overdue += 1
            # Approximate days-to-pay for fully paid invoices
            if remaining < 1 and float(inv.get("total") or 0) > 0:
                # We don't store exact payment date per invoice here;
                # use age as a conservative proxy when paid_amount ≈ total
                days_to_pay_samples.append(float(age))

        factors["overdue_count"] = overdue
        if days_to_pay_samples:
            factors["avg_days_to_pay"] = sum(days_to_pay_samples) / len(days_to_pay_samples)

        # ---- scoring (0–100) ----
        score = 60.0  # base for anyone with history

        # Paid ratio (0–25 points)
        score += factors["paid_ratio"] * 25

        # Overdue penalty
        if count > 0:
            overdue_ratio = overdue / count
            score -= overdue_ratio * 35

        # Volume bonus (small)
        if total_vol > 500:   # USD
            score += 5
        if total_vol > 2000:
            score += 5

        # Recency
        rec = factors.get("recency_days")
        if rec is not None:
            if rec <= 30:
                score += 8
            elif rec <= 90:
                score += 3
            elif rec > 180:
                score -= 10

        # Speed of payment
        avg_days = factors.get("avg_days_to_pay")
        if avg_days is not None:
            if avg_days <= 7:
                score += 10
            elif avg_days <= 21:
                score += 5
            elif avg_days > 45:
                score -= 8

        score = max(0, min(100, int(round(score))))

        label, color = "جديد", "muted"
        for threshold, lab, col in _LABELS:
            if score >= threshold:
                label, color = lab, col
                break

        return TrustScore(
            party_id=party_id,
            party_type=party_type,
            score=score,
            label=label,
            color_key=color,
            factors=factors,
            computed_at=datetime.now().isoformat(timespec="seconds"),
        )

    def score_many(
        self,
        party_ids: list[int],
        *,
        party_type: str = "customer",
    ) -> dict[int, TrustScore]:
        return {pid: self.score(pid, party_type=party_type) for pid in party_ids}

    def _empty(self, party_id: int, party_type: str) -> TrustScore:
        return TrustScore(
            party_id=party_id,
            party_type=party_type,
            score=50,
            label="جديد",
            color_key="muted",
            factors={},
            computed_at=datetime.now().isoformat(timespec="seconds"),
        )


__all__ = ["PartyTrustService", "TrustScore"]
