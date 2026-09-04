from __future__ import annotations

"""Centralized, admin-configurable settings for the point-of-sale screen.

Same pattern as ``core/barcode_settings.py`` and ``core/invoice_settings.py``:
values live in the open-ended ``settings`` key/value table, read fresh on
every POS session with sane defaults, and written only from the admin
"نقطة البيع" tab (views/admin_view.py).
"""

# --- Payment sheet -------------------------------------------------------#
AUTO_PRINT_DEFAULT_KEY = "pos_auto_print_default"

# --- Quick cash buttons ----------------------------------------------------#
QUICK_CASH_COUNT_KEY = "pos_quick_cash_count"

DEFAULT_AUTO_PRINT = False
DEFAULT_QUICK_CASH_COUNT = 3

VALID_QUICK_CASH_COUNT = (2, 3, 4, 5)


def _flag(settings, key: str, default: bool) -> bool:
    raw = settings.get(key, "1" if default else "0")
    return str(raw).strip() == "1"


def auto_print_default(settings) -> bool:
    """Whether the \"طباعة تلقائية بعد الدفع\" switch starts on each time
    the payment sheet opens. Cashiers can still flip it per-sale -- this
    only sets the starting state, so a shop that always prints receipts
    doesn't need to remember to tap it on every single sale."""
    return _flag(settings, AUTO_PRINT_DEFAULT_KEY, DEFAULT_AUTO_PRINT)


def quick_cash_count(settings) -> int:
    """How many rounded quick-cash suggestion buttons (beyond \"المبلغ
    بالتمام\") appear above the numpad. A busy counter shop typically wants
    fewer taps to scan past; a shop taking odd cash amounts benefits from
    more choices."""
    try:
        value = int(settings.get(QUICK_CASH_COUNT_KEY, str(DEFAULT_QUICK_CASH_COUNT)))
    except (TypeError, ValueError):
        return DEFAULT_QUICK_CASH_COUNT
    return value if value in VALID_QUICK_CASH_COUNT else DEFAULT_QUICK_CASH_COUNT


__all__ = [
    "AUTO_PRINT_DEFAULT_KEY", "QUICK_CASH_COUNT_KEY",
    "DEFAULT_AUTO_PRINT", "DEFAULT_QUICK_CASH_COUNT", "VALID_QUICK_CASH_COUNT",
    "auto_print_default", "quick_cash_count",
]
