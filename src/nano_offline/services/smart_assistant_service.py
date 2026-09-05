"""Unified smart decisions for the dashboard and future surfaces.

Collects the most actionable signals already available in the app
(notifications rules, restock velocity, cash posture, FX display mode)
into a single ranked list of :class:`Decision` objects — so the UI has one
place to ask «what should the owner do next?» instead of wiring each
source ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nano_offline.core.database import Database
    from nano_offline.services.dashboard_service import DashboardService
    from nano_offline.services.notification_service import NotificationService
    from nano_offline.repositories.settings_repository import SettingsRepository

from nano_offline.core import currency

_SEVERITY_RANK = {"urgent": 3, "warning": 2, "info": 1}


@dataclass(slots=True, frozen=True)
class Decision:
    """One recommended next step for the business owner."""

    key: str
    kind: str  # restock | collect | stock | backup | license | insight | fx | cash
    severity: str  # urgent | warning | info
    title: str
    body: str
    action_label: str | None = None
    action_target: str | None = None  # navigation key: items, invoices, finance, admin, ...
    entity_type: str | None = None
    entity_id: int | None = None
    score: float = 0.0  # higher = more urgent; used for ranking


class SmartAssistantService:
    def __init__(
        self,
        db: "Database",
        *,
        notifications: "NotificationService",
        dashboard: "DashboardService",
        settings: "SettingsRepository",
    ) -> None:
        self.db = db
        self.notifications = notifications
        self.dashboard = dashboard
        self.settings = settings

    # -- public API ----------------------------------------------------------

    def decisions(self, *, limit: int = 12) -> list[Decision]:
        """Ranked decisions, most urgent first."""
        items: list[Decision] = []
        items.extend(self._from_alerts())
        items.extend(self._from_restock())
        items.extend(self._from_cash())
        items.extend(self._from_fx())
        items.extend(self._from_zero_price_items())
        items.sort(key=lambda d: (_SEVERITY_RANK.get(d.severity, 0), d.score), reverse=True)
        # Dedupe by key keeping highest rank
        seen: set[str] = set()
        unique: list[Decision] = []
        for d in items:
            if d.key in seen:
                continue
            seen.add(d.key)
            unique.append(d)
        return unique[: max(1, int(limit))]

    def decision_of_the_day(self) -> Decision:
        """Single headline decision for the dashboard hero card."""
        ranked = self.decisions(limit=1)
        if ranked:
            return ranked[0]
        return Decision(
            key="all_clear",
            kind="insight",
            severity="info",
            title="كل شيء تحت السيطرة",
            body="لا توجد قرارات عاجلة الآن — استمر بالمبيعات اليومية وراجع التقارير أسبوعيًا.",
            action_label="فتح التقارير",
            action_target="reports",
            score=0,
        )

    # -- sources -------------------------------------------------------------

    def _from_alerts(self) -> list[Decision]:
        out: list[Decision] = []
        try:
            alerts = self.notifications.generate_alerts()
        except Exception:
            return out
        target_by_rule = {
            "receivables": "customers",
            "low_stock": "items",
            "backup": "admin",
            "license": "admin",
            "insight": "reports",
        }
        label_by_rule = {
            "receivables": "عرض العملاء",
            "low_stock": "فتح المواد",
            "backup": "النسخ الاحتياطي",
            "license": "الترخيص",
            "insight": "التقارير",
        }
        for a in alerts:
            rule = (a.rule_key or "").split(".")[0] if a.rule_key else ""
            # rule_key often looks like "receivables" or "low_stock"
            base = a.rule_key or "insight"
            for prefix in target_by_rule:
                if base.startswith(prefix) or prefix in base:
                    base = prefix
                    break
            kind_map = {
                "receivables": "collect",
                "low_stock": "stock",
                "backup": "backup",
                "license": "license",
                "insight": "insight",
            }
            sev = a.severity if a.severity in _SEVERITY_RANK else "info"
            out.append(
                Decision(
                    key=f"alert:{a.dedupe_key or a.rule_key or a.title}",
                    kind=kind_map.get(base, "insight"),
                    severity=sev,
                    title=a.title,
                    body=a.body,
                    action_label=label_by_rule.get(base),
                    action_target=target_by_rule.get(base),
                    entity_type=a.entity_type,
                    entity_id=a.entity_id,
                    score=float(_SEVERITY_RANK.get(sev, 0)) * 10,
                )
            )
        return out

    def _from_restock(self) -> list[Decision]:
        out: list[Decision] = []
        try:
            preds = self.dashboard.restock_predictions(limit=8)
        except Exception:
            return out
        for p in preds:
            days = float(p.get("days_left") or 0)
            sev = "urgent" if days <= 3 else "warning" if days <= 7 else "info"
            name = p.get("name") or "مادة"
            out.append(
                Decision(
                    key=f"restock:{p.get('item_id')}",
                    kind="restock",
                    severity=sev,
                    title=f"أعد طلب «{name}»",
                    body=f"المخزون الحالي {float(p.get('quantity') or 0):g} — يكفي حوالي {days:.0f} يوم حسب سرعة البيع الأخيرة.",
                    action_label="قائمة الشراء",
                    action_target="items",
                    entity_type="item",
                    entity_id=int(p["item_id"]) if p.get("item_id") is not None else None,
                    score=100.0 - days,
                )
            )
        return out

    def _from_cash(self) -> list[Decision]:
        try:
            summary = self.dashboard.summary()
            cash = float(summary.get("cash") or 0)
            payables = float(summary.get("payables") or 0)
        except Exception:
            return []
        out: list[Decision] = []
        if cash < 0:
            out.append(
                Decision(
                    key="cash:negative",
                    kind="cash",
                    severity="urgent",
                    title="رصيد الصندوق سالب",
                    body="دفتر الصندوق يُظهر رصيدًا أقل من صفر — راجع السندات والحركات النقدية.",
                    action_label="إغلاق يوم الصندوق",
                    action_target="dashboard",
                    score=95,
                )
            )
        elif payables > 0 and cash > 0 and cash < payables * 0.15:
            out.append(
                Decision(
                    key="cash:tight",
                    kind="cash",
                    severity="warning",
                    title="سيولة مضغوطة مقابل ذمم الموردين",
                    body="نقد الصندوق منخفض نسبيًا مقارنة بما عليك للموردين — خطط للتحصيل أو تأجيل مشتريات غير ضرورية.",
                    action_label="مراجعة الصندوق",
                    action_target="dashboard",
                    score=55,
                )
            )
        return out

    def _from_fx(self) -> list[Decision]:
        try:
            code = currency.get_display_currency(self.settings)
            rate = currency.get_exchange_rate(self.settings)
        except Exception:
            return []
        out: list[Decision] = []
        if code == currency.DISPLAY_CURRENCY_SYP and rate <= 0:
            out.append(
                Decision(
                    key="fx:missing_rate",
                    kind="fx",
                    severity="urgent",
                    title="سعر الصرف غير مضبوط",
                    body="العرض بالليرة يتطلب سعر صرف أكبر من صفر حتى تظهر المبالغ بشكل صحيح.",
                    action_label="ضبط العملة",
                    action_target="dashboard",
                    score=90,
                )
            )
        return out

    def _from_zero_price_items(self) -> list[Decision]:
        """Flag active stock items with zero selling price (data quality)."""
        try:
            with self.db.connect() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) AS c FROM items
                       WHERE item_type='مخزون' AND COALESCE(selling_price,0)<=0"""
                ).fetchone()
                count = int(dict(row)["c"]) if row is not None else 0
        except Exception:
            return []
        if count <= 0:
            return []
        return [
            Decision(
                key="items:zero_price",
                kind="insight",
                severity="warning" if count >= 3 else "info",
                title=f"{count} مادة بدون سعر بيع",
                body="مواد مخزون بسعر بيع صفر أو فارغ — قد تُباع دون مقابل في نقطة البيع.",
                action_label="مراجعة المواد",
                action_target="items",
                score=40 + min(count, 20),
            )
        ]


__all__ = ["SmartAssistantService", "Decision"]
