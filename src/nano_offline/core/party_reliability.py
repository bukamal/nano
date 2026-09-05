"""Customer/supplier payment reliability scoring (offline, from open invoices)."""

from __future__ import annotations

from datetime import date
from typing import Literal

Grade = Literal["clear", "regular", "late", "risk"]

_GRADE_META = {
    "clear": ("بدون ذمم", "SUCCESS", "SUCCESS_BG"),
    "regular": ("منتظم", "PRIMARY", "PRIMARY_BG"),
    "late": ("متأخر", "WARNING_DARK", "WARNING_BG"),
    "risk": ("خطر", "DANGER", "DANGER_BG"),
}


def grade_party(
    *,
    balance: float,
    outstanding_rows: list[dict] | None = None,
    overdue_after_days: int = 30,
    risk_after_days: int = 60,
    today: date | None = None,
) -> dict:
    """Return grade metadata for a party.

    ``outstanding_rows`` items need ``remaining_amount`` and ``invoice_date``.
    For suppliers the same logic applies to payables.
    """
    today = today or date.today()
    balance = float(balance or 0)
    rows = outstanding_rows or []
    open_rows = [r for r in rows if float(r.get("remaining_amount") or 0) > 1e-9]
    if abs(balance) <= 1e-9 and not open_rows:
        grade: Grade = "clear"
        max_age = 0
        total_open = 0.0
    else:
        total_open = sum(float(r.get("remaining_amount") or 0) for r in open_rows) or abs(balance)
        max_age = 0
        for r in open_rows:
            raw = str(r.get("invoice_date") or "")[:10]
            try:
                inv_d = date.fromisoformat(raw)
                max_age = max(max_age, (today - inv_d).days)
            except ValueError:
                continue
        if max_age >= risk_after_days:
            grade = "risk"
        elif max_age >= overdue_after_days:
            grade = "late"
        else:
            grade = "regular"

    label, color_token, bg_token = _GRADE_META[grade]
    return {
        "grade": grade,
        "label": label,
        "color_token": color_token,
        "bg_token": bg_token,
        "max_age_days": max_age,
        "open_total": total_open,
        "open_count": len(open_rows),
    }


def grade_label_ar(grade: str) -> str:
    return _GRADE_META.get(grade, _GRADE_META["regular"])[0]


__all__ = ["grade_party", "grade_label_ar", "Grade"]
