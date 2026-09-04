from __future__ import annotations

"""Centralized, admin-configurable settings for the reports center.

Same pattern as ``core/barcode_settings.py``, ``core/invoice_settings.py``,
``core/pos_settings.py``, and ``core/backup_settings.py``: values live in
the open-ended ``settings`` key/value table, read fresh with sane defaults,
and written only from the admin "التقارير" tab (views/admin_view.py).
"""

from datetime import date, timedelta

# --- Opened report ---------------------------------------------------------#
DEFAULT_REPORT_KEY = "reports_default_type"

# --- Opened date range -------------------------------------------------------#
DEFAULT_RANGE_KEY = "reports_default_range"

DEFAULT_REPORT_TYPE = "pnl"
DEFAULT_RANGE = "all"

REPORT_TYPE_LABELS = {
    "pnl": "قائمة الدخل والربحية",
    "profitability": "ربحية الفواتير والمواد",
    "inventory": "حركة وتقييم المخزون",
    "balances": "ذمم العملاء والموردين",
    "cash": "حركة الصندوق",
}

RANGE_LABELS = {
    "all": "كل الفترة",
    "today": "اليوم",
    "week": "هذا الأسبوع",
    "month": "هذا الشهر",
}


def default_report(settings) -> str:
    """Which report tab is selected the moment the reports center opens."""
    value = (settings.get(DEFAULT_REPORT_KEY, DEFAULT_REPORT_TYPE) or DEFAULT_REPORT_TYPE).strip()
    return value if value in REPORT_TYPE_LABELS else DEFAULT_REPORT_TYPE


def default_range(settings) -> str:
    value = (settings.get(DEFAULT_RANGE_KEY, DEFAULT_RANGE) or DEFAULT_RANGE).strip()
    return value if value in RANGE_LABELS else DEFAULT_RANGE


def default_range_dates(settings) -> tuple[str | None, str | None]:
    """The (date_from, date_to) the date fields start with when the reports
    center opens, computed fresh from today so it's always current -- never
    a stale pair of dates saved once and left behind. ``(None, None)`` for
    the \"كل الفترة\" choice matches the app's original always-blank
    behavior exactly, so leaving this setting untouched changes nothing."""
    choice = default_range(settings)
    today = date.today()
    if choice == "today":
        iso = today.isoformat()
        return iso, iso
    if choice == "week":
        return (today - timedelta(days=today.weekday())).isoformat(), today.isoformat()
    if choice == "month":
        return today.replace(day=1).isoformat(), today.isoformat()
    return None, None


__all__ = [
    "DEFAULT_REPORT_KEY", "DEFAULT_RANGE_KEY", "DEFAULT_REPORT_TYPE",
    "DEFAULT_RANGE", "REPORT_TYPE_LABELS", "RANGE_LABELS",
    "default_report", "default_range", "default_range_dates",
]
