"""Business Memory Graph — offline narrative insights from local history.

Turns raw invoices / stock / payments into short Arabic «stories» the owner
can act on, without any external AI or schema change.

Examples of memories:
  • «مبيعات الثلاثاء أعلى ٣× من متوسط الثلاثاء السابق بعد تخفيض سعر السكر ٨٪»
  • «المورد أحمد يتأخر ٤ أيام عن عادته → خطر نقص خلال ٩ أيام»
  • «عميل سارة سدّد أسرع من المتوسط هذا الشهر»
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nano_offline.core.database import Database
    from nano_offline.repositories.settings_repository import SettingsRepository

from nano_offline.core import currency

_AR_WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


@dataclass(slots=True, frozen=True)
class MemoryInsight:
    """One remembered business pattern / story."""

    key: str
    kind: str  # weekday_spike | supplier_delay | customer_speed | restock_link | price_effect | volume_shift
    severity: str  # urgent | warning | info | good
    title: str
    body: str
    action_label: str | None = None
    action_target: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    score: float = 0.0
    evidence: dict = field(default_factory=dict)


class BusinessMemoryService:
    def __init__(self, db: "Database", *, settings: "SettingsRepository") -> None:
        self.db = db
        self.settings = settings

    def insights(self, *, limit: int = 8) -> list[MemoryInsight]:
        """Ranked list of narrative insights from local history."""
        items: list[MemoryInsight] = []
        items.extend(self._weekday_sales_pattern())
        items.extend(self._supplier_delay_pattern())
        items.extend(self._customer_payment_speed())
        items.extend(self._top_item_velocity_shift())
        items.extend(self._quiet_period_warning())

        rank = {"urgent": 3, "warning": 2, "info": 1, "good": 0}
        items.sort(key=lambda m: (rank.get(m.severity, 0), m.score), reverse=True)
        seen: set[str] = set()
        unique: list[MemoryInsight] = []
        for m in items:
            if m.key in seen:
                continue
            seen.add(m.key)
            unique.append(m)
        return unique[: max(1, int(limit))]

    def story_of_the_day(self) -> MemoryInsight | None:
        ranked = self.insights(limit=1)
        return ranked[0] if ranked else None

    # ------------------------------------------------------------------ #
    # Sources
    # ------------------------------------------------------------------ #

    def _weekday_sales_pattern(self) -> list[MemoryInsight]:
        """Compare today's weekday sales vs the same weekday average historically."""
        today = date.today()
        weekday = today.weekday()  # 0=Mon
        weekday_name = _AR_WEEKDAYS[weekday]

        try:
            with self.db.connect() as conn:
                # Last ~12 weeks of same weekday
                rows = conn.execute(
                    """SELECT invoice_date, COALESCE(SUM(total),0) AS day_total
                       FROM invoices
                       WHERE type='sale' AND status='posted'
                         AND invoice_date >= date('now', '-90 days')
                       GROUP BY invoice_date"""
                ).fetchall()
        except Exception:
            return []

        by_weekday: dict[int, list[float]] = defaultdict(list)
        today_total = 0.0
        for r in rows:
            d = dict(r)
            try:
                inv_d = date.fromisoformat(str(d["invoice_date"])[:10])
            except Exception:
                continue
            total = float(d["day_total"] or 0)
            by_weekday[inv_d.weekday()].append(total)
            if inv_d == today:
                today_total = total

        history = [v for v in by_weekday.get(weekday, []) if v > 0]
        # Exclude today from average if present
        hist_for_avg = history[:-1] if history and today_total > 0 and abs(history[-1] - today_total) < 1e-6 else history
        if len(hist_for_avg) < 2:
            return []

        avg = mean(hist_for_avg)
        if avg < 1:
            return []

        ratio = today_total / avg if today_total > 0 else 0.0
        out: list[MemoryInsight] = []

        if today_total > 0 and ratio >= 1.8:
            out.append(
                MemoryInsight(
                    key=f"weekday:spike:{today.isoformat()}",
                    kind="weekday_spike",
                    severity="good",
                    title=f"مبيعات {weekday_name} أعلى من المعتاد",
                    body=(
                        f"اليوم بعتَ {self._fmt(today_total)} — حوالي {ratio:.1f}× متوسط "
                        f"{weekday_name} خلال الأشهر الماضية ({self._fmt(avg)})."
                    ),
                    action_label="عرض التقارير",
                    action_target="reports",
                    score=50 + min(ratio * 10, 40),
                    evidence={"today": today_total, "avg": avg, "ratio": ratio, "weekday": weekday},
                )
            )
        elif today_total > 0 and ratio <= 0.45 and avg > 50:
            out.append(
                MemoryInsight(
                    key=f"weekday:drop:{today.isoformat()}",
                    kind="weekday_spike",
                    severity="warning",
                    title=f"مبيعات {weekday_name} أضعف من المعتاد",
                    body=(
                        f"اليوم {self._fmt(today_total)} فقط — نحو {ratio*100:.0f}% من متوسط "
                        f"{weekday_name} ({self._fmt(avg)}). راجع العروض أو الحضور."
                    ),
                    action_label="فتح نقطة البيع",
                    action_target="pos",
                    score=55,
                    evidence={"today": today_total, "avg": avg, "ratio": ratio},
                )
            )
        return out

    def _supplier_delay_pattern(self) -> list[MemoryInsight]:
        """Flag suppliers whose recent purchase gap is longer than their historical average."""
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """SELECT s.id, s.name, i.invoice_date
                       FROM invoices i
                       JOIN suppliers s ON s.id = i.supplier_id
                       WHERE i.type='purchase' AND i.status='posted'
                         AND i.invoice_date >= date('now', '-180 days')
                       ORDER BY s.id, i.invoice_date"""
                ).fetchall()
        except Exception:
            return []

        by_supplier: dict[int, list[tuple[str, date]]] = defaultdict(list)
        names: dict[int, str] = {}
        for r in rows:
            d = dict(r)
            sid = int(d["id"])
            names[sid] = str(d["name"])
            try:
                inv_d = date.fromisoformat(str(d["invoice_date"])[:10])
            except Exception:
                continue
            by_supplier[sid].append((str(d["invoice_date"]), inv_d))

        today = date.today()
        out: list[MemoryInsight] = []
        for sid, events in by_supplier.items():
            if len(events) < 3:
                continue
            gaps = []
            for i in range(1, len(events)):
                gaps.append((events[i][1] - events[i - 1][1]).days)
            if not gaps:
                continue
            avg_gap = mean(gaps)
            if avg_gap < 3:
                continue
            last = events[-1][1]
            days_since = (today - last).days
            if days_since > avg_gap * 1.4 and days_since >= 7:
                risk_days = max(1, int(avg_gap - (days_since - avg_gap)))
                out.append(
                    MemoryInsight(
                        key=f"supplier:delay:{sid}",
                        kind="supplier_delay",
                        severity="warning" if days_since < avg_gap * 2 else "urgent",
                        title=f"المورد «{names[sid]}» متأخر عن عادته",
                        body=(
                            f"آخر شراء منذ {days_since} يوماً، بينما متوسط الفترة بين مشترياتك منه "
                            f"{avg_gap:.0f} يوماً. قد يظهر نقص خلال نحو {max(risk_days, 3)} أيام."
                        ),
                        action_label="فتح المشتريات",
                        action_target="invoices",
                        entity_type="supplier",
                        entity_id=sid,
                        score=40 + min(days_since - avg_gap, 30),
                        evidence={"avg_gap": avg_gap, "days_since": days_since},
                    )
                )
        return out[:3]

    def _customer_payment_speed(self) -> list[MemoryInsight]:
        """Highlight customers who paid faster or slower than their own average recently."""
        try:
            with self.db.connect() as conn:
                # Approximate: fully paid sale invoices with age as proxy for days-to-pay
                rows = conn.execute(
                    """SELECT c.id, c.name, i.invoice_date, i.total, i.paid_amount,
                              MAX(i.total - i.paid_amount, 0) AS remaining
                       FROM invoices i
                       JOIN customers c ON c.id = i.customer_id
                       WHERE i.type='sale' AND i.status='posted'
                         AND i.invoice_date >= date('now', '-120 days')
                       ORDER BY c.id, i.invoice_date"""
                ).fetchall()
        except Exception:
            return []

        by_cust: dict[int, list[dict]] = defaultdict(list)
        names: dict[int, str] = {}
        for r in rows:
            d = dict(r)
            cid = int(d["id"])
            names[cid] = str(d["name"])
            by_cust[cid].append(d)

        today = date.today()
        out: list[MemoryInsight] = []
        for cid, invs in by_cust.items():
            paid_ages: list[int] = []
            recent_paid_ages: list[int] = []
            for inv in invs:
                remaining = float(inv.get("remaining") or 0)
                if remaining > 1:
                    continue
                try:
                    inv_d = date.fromisoformat(str(inv["invoice_date"])[:10])
                except Exception:
                    continue
                age = (today - inv_d).days
                paid_ages.append(age)
                if inv_d >= today - timedelta(days=45):
                    recent_paid_ages.append(age)
            if len(paid_ages) < 3 or not recent_paid_ages:
                continue
            hist_avg = mean(paid_ages)
            recent_avg = mean(recent_paid_ages)
            if hist_avg < 2:
                continue
            if recent_avg <= hist_avg * 0.55 and hist_avg >= 7:
                out.append(
                    MemoryInsight(
                        key=f"customer:fast:{cid}",
                        kind="customer_speed",
                        severity="good",
                        title=f"«{names[cid]}» يسدّد أسرع من عادته",
                        body=(
                            f"متوسط السداد الأخير ~{recent_avg:.0f} يوماً مقابل متوسطه التاريخي "
                            f"~{hist_avg:.0f} يوماً — إشارة إيجابية على السيولة."
                        ),
                        action_label="عرض العملاء",
                        action_target="customers",
                        entity_type="customer",
                        entity_id=cid,
                        score=35,
                        evidence={"hist_avg": hist_avg, "recent_avg": recent_avg},
                    )
                )
            elif recent_avg >= hist_avg * 1.6 and recent_avg >= 20:
                out.append(
                    MemoryInsight(
                        key=f"customer:slow:{cid}",
                        kind="customer_speed",
                        severity="warning",
                        title=f"«{names[cid]}» بدأ يتأخر في السداد",
                        body=(
                            f"متوسط السداد الأخير ~{recent_avg:.0f} يوماً (كان ~{hist_avg:.0f}). "
                            "راقب الذمم أو قلّل الأجل."
                        ),
                        action_label="تحصيل",
                        action_target="customers",
                        entity_type="customer",
                        entity_id=cid,
                        score=45 + min(recent_avg - hist_avg, 25),
                        evidence={"hist_avg": hist_avg, "recent_avg": recent_avg},
                    )
                )
        return out[:3]

    def _top_item_velocity_shift(self) -> list[MemoryInsight]:
        """Items whose sale velocity changed sharply week-over-week."""
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """SELECT il.item_id, it.name,
                              SUM(CASE WHEN i.invoice_date >= date('now','-7 days')
                                       THEN il.quantity ELSE 0 END) AS q_cur,
                              SUM(CASE WHEN i.invoice_date >= date('now','-14 days')
                                        AND i.invoice_date < date('now','-7 days')
                                       THEN il.quantity ELSE 0 END) AS q_prev
                       FROM invoice_lines il
                       JOIN invoices i ON i.id = il.invoice_id
                       JOIN items it ON it.id = il.item_id
                       WHERE i.type='sale' AND i.status='posted'
                         AND i.invoice_date >= date('now','-14 days')
                         AND it.item_type='مخزون'
                       GROUP BY il.item_id
                       HAVING q_cur > 0 OR q_prev > 0
                       ORDER BY q_cur DESC
                       LIMIT 40"""
                ).fetchall()
        except Exception:
            return []

        out: list[MemoryInsight] = []
        for r in rows:
            d = dict(r)
            q_cur = float(d["q_cur"] or 0)
            q_prev = float(d["q_prev"] or 0)
            name = str(d["name"])
            iid = int(d["item_id"])
            if q_prev >= 2 and q_cur >= q_prev * 2.2:
                out.append(
                    MemoryInsight(
                        key=f"item:surge:{iid}",
                        kind="volume_shift",
                        severity="info",
                        title=f"ارتفاع ملحوظ في مبيعات «{name}»",
                        body=(
                            f"هذا الأسبوع {q_cur:.0f} وحدة مقابل {q_prev:.0f} الأسبوع الماضي. "
                            "تأكد من كفاية المخزون."
                        ),
                        action_label="فتح المواد",
                        action_target="items",
                        entity_type="item",
                        entity_id=iid,
                        score=40,
                        evidence={"q_cur": q_cur, "q_prev": q_prev},
                    )
                )
            elif q_prev >= 3 and q_cur <= q_prev * 0.35:
                out.append(
                    MemoryInsight(
                        key=f"item:drop:{iid}",
                        kind="volume_shift",
                        severity="warning",
                        title=f"تراجع مبيعات «{name}»",
                        body=(
                            f"هذا الأسبوع {q_cur:.0f} فقط مقابل {q_prev:.0f} سابقاً. "
                            "راجع السعر أو العرض."
                        ),
                        action_label="فتح المواد",
                        action_target="items",
                        entity_type="item",
                        entity_id=iid,
                        score=38,
                        evidence={"q_cur": q_cur, "q_prev": q_prev},
                    )
                )
        return out[:3]

    def _quiet_period_warning(self) -> list[MemoryInsight]:
        """No sales in the last N days while history shows activity."""
        try:
            with self.db.connect() as conn:
                last = conn.execute(
                    """SELECT MAX(invoice_date) AS d FROM invoices
                       WHERE type='sale' AND status='posted'"""
                ).fetchone()
                count_30 = conn.execute(
                    """SELECT COUNT(*) FROM invoices
                       WHERE type='sale' AND status='posted'
                         AND invoice_date >= date('now','-30 days')"""
                ).fetchone()
        except Exception:
            return []

        if not last or not last[0]:
            return []
        try:
            last_d = date.fromisoformat(str(last[0])[:10])
        except Exception:
            return []
        gap = (date.today() - last_d).days
        hist = int(count_30[0] or 0) if count_30 else 0
        if gap >= 3 and hist >= 5:
            return [
                MemoryInsight(
                    key=f"quiet:{last_d.isoformat()}",
                    kind="volume_shift",
                    severity="urgent" if gap >= 5 else "warning",
                    title="لا مبيعات منذ عدة أيام",
                    body=(
                        f"آخر فاتورة بيع بتاريخ {last_d.isoformat()} (منذ {gap} أيام)، "
                        f"بينما سُجّلت {hist} فاتورة خلال آخر ٣٠ يوماً."
                    ),
                    action_label="فتح نقطة البيع",
                    action_target="pos",
                    score=70 + min(gap * 3, 25),
                    evidence={"last_sale": last_d.isoformat(), "gap_days": gap},
                )
            ]
        return []

    def _fmt(self, amount: float) -> str:
        try:
            return currency.format_amount(amount, self.settings)
        except Exception:
            return f"{amount:,.0f}"


__all__ = ["BusinessMemoryService", "MemoryInsight"]
