from __future__ import annotations

"""Centralized, admin-configurable settings for the invoice document system.

Same pattern as ``core/barcode_settings.py`` (see that module's docstring):
everything lives in the open-ended ``settings`` key/value table already used
for currency/branding/barcode, so no schema migration is needed and every
setting takes effect immediately in the invoice list, the invoice editor,
and the printed/PDF invoice document.

This module only knows about *reading* settings with sane defaults. The
admin "الفواتير" tab (views/admin_view.py) is the only place that writes
these keys.
"""

from datetime import date, datetime, timedelta

# --- Numbering ---------------------------------------------------------#
NUMBER_PREFIX_KEY = "invoice_number_prefix"
NUMBER_PADDING_KEY = "invoice_number_padding"

# --- Due date / overdue tracking ---------------------------------------#
DEFAULT_DUE_DAYS_KEY = "invoice_default_due_days"
OVERDUE_DAYS_KEY = "invoice_overdue_days"

# --- Printed document ----------------------------------------------------#
FOOTER_TEXT_KEY = "invoice_footer_text"
SHOW_SIGN_BOXES_KEY = "invoice_show_sign_boxes"
SHOW_VERIFY_QR_KEY = "invoice_show_verify_qr"

DEFAULT_NUMBER_PREFIX = ""
DEFAULT_NUMBER_PADDING = 0
DEFAULT_DUE_DAYS = 0  # 0 == no due-date line printed (cash-style invoices)
DEFAULT_OVERDUE_DAYS = 30
DEFAULT_FOOTER_TEXT = ""
DEFAULT_SHOW_SIGN_BOXES = True
DEFAULT_SHOW_VERIFY_QR = True

VALID_NUMBER_PADDING = (0, 4, 5, 6)


def _flag(settings, key: str, default: bool) -> bool:
    raw = settings.get(key, "1" if default else "0")
    return str(raw).strip() == "1"


def number_prefix(settings) -> str:
    return (settings.get(NUMBER_PREFIX_KEY, DEFAULT_NUMBER_PREFIX) or "").strip()


def number_padding(settings) -> int:
    try:
        value = int(settings.get(NUMBER_PADDING_KEY, str(DEFAULT_NUMBER_PADDING)))
    except (TypeError, ValueError):
        return DEFAULT_NUMBER_PADDING
    return value if value in VALID_NUMBER_PADDING else DEFAULT_NUMBER_PADDING


def format_invoice_number(invoice_id: int, settings) -> str:
    """The display number printed/shown for an invoice id.

    The internal id (used for the barcode, the signature, and every DB
    join) never changes -- this only controls how it is *displayed*, so
    turning padding/prefix on or off is always safe and fully retroactive.
    """
    padding = number_padding(settings)
    digits = str(int(invoice_id)).zfill(padding) if padding else str(int(invoice_id))
    return f"{number_prefix(settings)}{digits}"


def default_due_days(settings) -> int:
    try:
        return max(0, int(settings.get(DEFAULT_DUE_DAYS_KEY, str(DEFAULT_DUE_DAYS))))
    except (TypeError, ValueError):
        return DEFAULT_DUE_DAYS


def overdue_days(settings) -> int:
    try:
        value = int(settings.get(OVERDUE_DAYS_KEY, str(DEFAULT_OVERDUE_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_OVERDUE_DAYS
    return value if value > 0 else DEFAULT_OVERDUE_DAYS


def due_date_for(invoice_date_str: str | None, settings) -> date | None:
    """Return the due date for a credit invoice, or ``None`` when the admin
    hasn't set a default due-days window (cash-only shops leave this at 0
    and never see a due-date line on their invoices)."""
    days = default_due_days(settings)
    if days <= 0 or not invoice_date_str:
        return None
    try:
        issued = datetime.fromisoformat(str(invoice_date_str)[:10]).date()
    except ValueError:
        return None
    return issued + timedelta(days=days)


def footer_text(settings) -> str:
    return (settings.get(FOOTER_TEXT_KEY, DEFAULT_FOOTER_TEXT) or "").strip()


def show_sign_boxes(settings) -> bool:
    return _flag(settings, SHOW_SIGN_BOXES_KEY, DEFAULT_SHOW_SIGN_BOXES)


def show_verify_qr(settings) -> bool:
    return _flag(settings, SHOW_VERIFY_QR_KEY, DEFAULT_SHOW_VERIFY_QR)


__all__ = [
    "NUMBER_PREFIX_KEY", "NUMBER_PADDING_KEY", "DEFAULT_DUE_DAYS_KEY",
    "OVERDUE_DAYS_KEY", "FOOTER_TEXT_KEY", "SHOW_SIGN_BOXES_KEY",
    "SHOW_VERIFY_QR_KEY",
    "DEFAULT_NUMBER_PREFIX", "DEFAULT_NUMBER_PADDING", "DEFAULT_DUE_DAYS",
    "DEFAULT_OVERDUE_DAYS", "DEFAULT_FOOTER_TEXT", "DEFAULT_SHOW_SIGN_BOXES",
    "DEFAULT_SHOW_VERIFY_QR", "VALID_NUMBER_PADDING",
    "number_prefix", "number_padding", "format_invoice_number",
    "default_due_days", "overdue_days", "due_date_for", "footer_text",
    "show_sign_boxes", "show_verify_qr",
]
