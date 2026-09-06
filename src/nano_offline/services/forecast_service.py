from __future__ import annotations

from statistics import mean, pstdev

from nano_offline.core.database import Database

# PHASE10 wave4 (B1): seasonal sales/purchase forecasting. Deliberately pure
# Python over existing tables (invoices only) -- no native extension, no schema
# change, fully offline and deterministic.
MONTH_NAMES_AR = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}
CONFIDENCE_LABELS = {"high": "عالية", "medium": "متوسطة", "low": "منخفضة"}


class ForecastService:
    """Seasonal forecast of sales/purchases from the local database.

    Method (kept intentionally simple and deterministic):
      1. monthly totals = SUM(invoices.total) grouped by YYYY-MM;
      2. seasonal index per calendar month = mean(total of that month) /
         overall monthly average (1.0 when a calendar month has no history);
      3. trend base = mean of the last ``window`` monthly totals (all history
         when there is less than that);
      4. next ``horizon`` months = trend base * that month's seasonal index,
         with a band around it derived from data volatility (never below 10%).

    With fewer than 2 months of history the call returns an ``insufficient``
    result instead of raising, so screens can show an honest empty state.
    Read-only: it never writes to the database.
    """

    def __init__(self, db: Database):
        self.db = db

    def monthly_totals(
        self,
        *,
        invoice_type: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Chronological monthly totals (sum + invoice count) for one direction.

        Columns are named explicitly; only zero-copy aggregates are read.
        """
        if invoice_type not in ("sale", "purchase"):
            raise ValueError("نوع الحركة غير صحيح")
        where = ["type=?"]
        params: list[object] = [invoice_type]
        if (date_from or "").strip():
            where.append("invoice_date>=?")
            params.append((date_from or "").strip())
        if (date_to or "").strip():
            where.append("invoice_date<=?")
            params.append((date_to or "").strip())
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT substr(invoice_date,1,7) AS month,
                           SUM(total) AS total,
                           COUNT(*) AS count
                    FROM invoices
                    WHERE {' AND '.join(where)}
                    GROUP BY substr(invoice_date,1,7)
                    ORDER BY month ASC""",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def seasonal_forecast(
        self,
        *,
        invoice_type: str = "sale",
        horizon: int = 3,
        window: int = 6,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Forecast the next ``horizon`` months for sales or purchases.

        Returns a plain dict (never raises for empty/sparse data -- see
        ``_insufficient``) suitable for both the reports screen and the
        printable HTML mirror.
        """
        if invoice_type not in ("sale", "purchase"):
            raise ValueError("نوع الحركة غير صحيح")
        horizon = min(max(1, int(horizon)), 12)
        history = self.monthly_totals(
            invoice_type=invoice_type, date_from=date_from, date_to=date_to
        )
        if not history:
            return self._insufficient(invoice_type, "لا توجد فواتير في الفترة المحددة لعمل توقعات.")
        totals = [float(h["total"]) for h in history]
        if len(totals) < 2:
            return self._insufficient(invoice_type, "يلزم شهران من البيانات على الأقل لبناء توقع موسمي.")

        overall_avg = mean(totals)
        by_calendar_month: dict[int, list[float]] = {}
        for h in history:
            by_calendar_month.setdefault(int(str(h["month"])[5:7]), []).append(float(h["total"]))
        seasonal: dict[int, float] = {}
        for cal in range(1, 13):
            values = by_calendar_month.get(cal)
            seasonal[cal] = round(mean(values) / overall_avg, 3) if values else 1.0

        trend_base = mean(totals[-window:]) if len(totals) >= window else mean(totals)
        if len(totals) >= 12:
            confidence = "high"
        elif len(totals) >= 6:
            confidence = "medium"
        else:
            confidence = "low"
        cv = (pstdev(totals) / overall_avg) if overall_avg > 1e-9 else 0.5
        band = 0.10 + min(max(cv, 0.0), 0.6) * 0.5

        year, month = int(str(history[-1]["month"])[:4]), int(str(history[-1]["month"])[5:7])
        forecasts: list[dict] = []
        for _ in range(horizon):
            month += 1
            if month > 12:
                month = 1
                year += 1
            index = seasonal.get(month, 1.0)
            forecast = trend_base * index
            forecasts.append(
                {
                    "month": f"{year:04d}-{month:02d}",
                    "month_label": MONTH_NAMES_AR.get(month, str(month)),
                    "seasonal_index": index,
                    "forecast": round(forecast, 2),
                    "low": round(forecast * (1 - band), 2),
                    "high": round(forecast * (1 + band), 2),
                }
            )
        return {
            "invoice_type": invoice_type,
            "insufficient": False,
            "reason": None,
            "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS[confidence],
            "history_months": len(history),
            "monthly_average": round(overall_avg, 2),
            "trend_base": round(trend_base, 2),
            "band_percent": round(band * 100, 1),
            "history": history,
            "seasonal": seasonal,
            "forecasts": forecasts,
        }

    @staticmethod
    def _insufficient(invoice_type: str, reason: str) -> dict:
        return {
            "invoice_type": invoice_type,
            "insufficient": True,
            "reason": reason,
            "confidence": None,
            "confidence_label": "—",
            "history_months": 0,
            "monthly_average": 0.0,
            "trend_base": 0.0,
            "band_percent": 0.0,
            "history": [],
            "seasonal": {},
            "forecasts": [],
        }


__all__ = ["ForecastService", "MONTH_NAMES_AR", "CONFIDENCE_LABELS"]
