"""Owner Pulse — natural-language 15-second summary for the business owner.

Produces a single human-readable card that answers:
«What is the state of my business right now, and what should I do next?»

All data is read from the local database. No network, no external AI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nano_offline.core.database import Database
    from nano_offline.services.dashboard_service import DashboardService
    from nano_offline.services.smart_assistant_service import SmartAssistantService, Decision
    from nano_offline.repositories.settings_repository import SettingsRepository

from nano_offline.core import currency


@dataclass(slots=True, frozen=True)
class OwnerPulse:
    """Everything the dashboard needs to render the pulse card."""

    headline: str          # one short sentence
    body: str              # 2–4 sentences in plain Arabic
    severity: str          # urgent | warning | info | good
    metrics: dict          # raw numbers for the UI chips
    primary_decision: "Decision | None"
    generated_at: str


class OwnerPulseService:
    def __init__(
        self,
        db: "Database",
        *,
        dashboard: "DashboardService",
        smart_assistant: "SmartAssistantService",
        settings: "SettingsRepository",
        business_memory=None,
    ) -> None:
        self.db = db
        self.dashboard = dashboard
        self.smart_assistant = smart_assistant
        self.settings = settings
        self.business_memory = business_memory

    def generate(self) -> OwnerPulse:
        """Build the pulse from live local data."""
        weekly = {}
        try:
            weekly = self.dashboard.weekly_owner_summary() or {}
        except Exception:
            weekly = {}

        sales = float(weekly.get("sales") or 0)
        prev_sales = float(weekly.get("prev_sales") or 0)
        profit = float(weekly.get("approx_profit") or 0)
        receivables = float(weekly.get("receivables") or 0)
        low_stock = int(weekly.get("low_stock_count") or 0)
        change_pct = weekly.get("sales_change_pct")

        # Cash position (simple)
        cash = 0.0
        try:
            with self.db.connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(CASE WHEN type='in' THEN amount ELSE -amount END),0) FROM vouchers"
                ).fetchone()
                # Fallback: many installs track cash via payments + expenses
                if row is None or float(row[0] or 0) == 0:
                    row = conn.execute(
                        """SELECT
                             COALESCE((SELECT SUM(amount) FROM payments WHERE payment_type='receipt'),0)
                           - COALESCE((SELECT SUM(amount) FROM payments WHERE payment_type='payment'),0)
                           - COALESCE((SELECT SUM(amount) FROM expenses),0)
                        """
                    ).fetchone()
                cash = float(row[0] or 0) if row else 0.0
        except Exception:
            cash = 0.0

        # Primary decision from smart assistant
        primary = None
        try:
            primary = self.smart_assistant.decision_of_the_day()
            if primary and primary.key == "all_clear":
                primary = None
        except Exception:
            primary = None

        # Build narrative
        parts: list[str] = []
        severity = "good"

        # Sales trend sentence
        if change_pct is None:
            parts.append(f"مبيعات آخر ٧ أيام: {self._fmt(sales)}.")
        elif change_pct >= 15:
            parts.append(f"مبيعاتك هذا الأسبوع أعلى بنسبة {change_pct:.0f}% عن الأسبوع السابق — أداء قوي.")
            severity = "good"
        elif change_pct >= 0:
            parts.append(f"مبيعاتك مستقرة نسبيًا (+{change_pct:.0f}% عن الأسبوع السابق).")
        elif change_pct > -20:
            parts.append(f"مبيعاتك انخفضت {abs(change_pct):.0f}% عن الأسبوع السابق.")
            severity = "warning"
        else:
            parts.append(f"انخفاض ملحوظ في المبيعات ({abs(change_pct):.0f}%). راجع العروض أو التحصيل.")
            severity = "urgent"

        # Profit
        if profit > 0:
            parts.append(f"الربح التقريبي للأسبوع: {self._fmt(profit)}.")
        elif profit < 0:
            parts.append(f"خسارة تقريبية هذا الأسبوع: {self._fmt(abs(profit))}.")
            severity = "urgent" if severity != "urgent" else severity

        # Receivables
        if receivables > 0:
            if receivables > sales * 0.8 and sales > 0:
                parts.append(f"الذمم المدينة مرتفعة ({self._fmt(receivables)}) — ركّز على التحصيل.")
                if severity == "good":
                    severity = "warning"
            else:
                parts.append(f"عندك ذمم مدينة بقيمة {self._fmt(receivables)}.")

        # Stock
        if low_stock > 0:
            parts.append(f"{low_stock} مادة وصلت لحد المخزون المنخفض.")
            if severity == "good":
                severity = "warning"

        # Cash warning
        if cash < 0:
            parts.append("رصيد الصندوق يبدو سالبًا — راجع الحركات النقدية.")
            severity = "urgent"
        elif cash > 0 and receivables > cash * 3:
            parts.append("معظم أموالك عند العملاء — خطط للتحصيل قريبًا.")

        # Crisis mode note
        if self._crisis_active():
            parts.append("⚠ وضع الطوارئ الاقتصادي مفعّل — سعر الصرف مجمّد.")
            severity = "urgent"

        # Business memory story (one line if available)
        memory_title = None
        try:
            if self.business_memory is not None:
                story = self.business_memory.story_of_the_day()
                if story is not None:
                    memory_title = story.title
                    parts.append(story.body)
                    if story.severity == "urgent" and severity != "urgent":
                        severity = "urgent"
                    elif story.severity == "warning" and severity == "good":
                        severity = "warning"
        except Exception:
            pass

        body = " ".join(parts) if parts else "لا توجد بيانات كافية لبناء ملخص. ابدأ بتسجيل المبيعات اليومية."

        # Headline
        if severity == "urgent":
            headline = "يحتاج انتباهك الآن"
        elif severity == "warning":
            headline = "وضع يحتاج متابعة"
        elif severity == "good":
            headline = "الأمور تسير بشكل جيد"
        else:
            headline = "ملخص سريع لعملك"

        metrics = {
            "sales_7d": sales,
            "prev_sales_7d": prev_sales,
            "sales_change_pct": change_pct,
            "approx_profit_7d": profit,
            "receivables": receivables,
            "low_stock_count": low_stock,
            "cash_approx": cash,
            "crisis_active": self._crisis_active(),
        }

        return OwnerPulse(
            headline=headline,
            body=body,
            severity=severity,
            metrics=metrics,
            primary_decision=primary,
            generated_at=datetime.now().isoformat(timespec="seconds"),
        )

    def _crisis_active(self) -> bool:
        return (self.settings.get("crisis_mode_enabled") or "").strip().lower() in ("1", "true", "yes", "on")

    def _fmt(self, amount: float) -> str:
        try:
            # Stored values are USD; convert + format for current display currency
            return currency.format_amount(amount, self.settings)
        except Exception:
            return f"{amount:,.0f}"


__all__ = ["OwnerPulseService", "OwnerPulse"]
