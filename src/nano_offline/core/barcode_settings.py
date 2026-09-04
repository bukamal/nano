from __future__ import annotations

"""Centralized, admin-configurable settings for the barcode/QR system.

Everything here lives in the same open-ended ``settings`` key/value table
already used for currency and branding (see core/currency.py for the
identical pattern) -- no schema migration needed, and every setting takes
effect immediately across the item editor, POS scanning, and printed
label sheets.

This module only knows about *reading* settings with sane defaults. The
admin "الباركود" tab (views/admin_view.py) is the only place that writes
these keys.
"""

# --- Generation ------------------------------------------------------- #
KIND_KEY = "barcode_default_kind"
PREFIX_KEY = "barcode_internal_prefix"
AUTO_GENERATE_KEY = "barcode_auto_generate"

# --- Validation --------------------------------------------------------#
SIMILAR_WARNING_KEY = "barcode_similar_warning"
CHECKSUM_WARNING_KEY = "barcode_checksum_warning"

# --- Printed labels ----------------------------------------------------#
LABEL_COLUMNS_KEY = "barcode_label_columns"
LABEL_PRICE_QR_KEY = "barcode_label_price_qr_default"
LABEL_SHOW_TEXT_KEY = "barcode_label_show_text"
LABEL_SIZE_KEY = "barcode_label_size"

# --- Scanning feedback (POS) -------------------------------------------#
SCAN_FEEDBACK_KEY = "pos_scan_feedback"

# --- Stocktake (continuous scan) ---------------------------------------#
STOCKTAKE_COOLDOWN_KEY = "stocktake_scan_cooldown_ms"
STOCKTAKE_SOUND_KEY = "stocktake_sound_feedback"

DEFAULT_KIND = "EAN13"
DEFAULT_PREFIX = ""
DEFAULT_AUTO_GENERATE = False
DEFAULT_SIMILAR_WARNING = True
DEFAULT_CHECKSUM_WARNING = True
DEFAULT_LABEL_COLUMNS = 3
DEFAULT_LABEL_PRICE_QR = False
DEFAULT_LABEL_SHOW_TEXT = True
DEFAULT_LABEL_SIZE = "medium"
DEFAULT_SCAN_FEEDBACK = "detailed"
DEFAULT_STOCKTAKE_COOLDOWN_MS = 1200
DEFAULT_STOCKTAKE_SOUND = True

KIND_LABELS = {"EAN13": "EAN-13", "CODE128": "Code 128", "QR": "QR"}

# (width, height) in the same px units code128b_svg already uses.
LABEL_SIZE_DIMENSIONS = {
    "small": (170, 46),
    "medium": (210, 54),
    "large": (250, 64),
}
LABEL_SIZE_LABELS = {"small": "صغير", "medium": "متوسط", "large": "كبير"}

SCAN_FEEDBACK_LABELS = {"brief": "مختصرة (نغمة نجاح فقط)", "detailed": "مفصّلة (اسم المادة والكمية)"}

VALID_LABEL_COLUMNS = (2, 3, 4)


def _flag(settings, key: str, default: bool) -> bool:
    raw = settings.get(key, "1" if default else "0")
    return str(raw).strip() == "1"


def default_kind(settings) -> str:
    value = (settings.get(KIND_KEY, DEFAULT_KIND) or DEFAULT_KIND).strip()
    return value if value in KIND_LABELS else DEFAULT_KIND


def internal_prefix(settings) -> str:
    """A 0-2 digit prefix baked into freshly-generated EAN-13 codes (the
    20-29 range is conventionally reserved for internal/in-store use, but
    any digits are accepted -- this never touches scanned or manually
    typed codes, only ones this app generates)."""
    return (settings.get(PREFIX_KEY, DEFAULT_PREFIX) or "").strip()


def auto_generate_enabled(settings) -> bool:
    return _flag(settings, AUTO_GENERATE_KEY, DEFAULT_AUTO_GENERATE)


def similar_warning_enabled(settings) -> bool:
    return _flag(settings, SIMILAR_WARNING_KEY, DEFAULT_SIMILAR_WARNING)


def checksum_warning_enabled(settings) -> bool:
    return _flag(settings, CHECKSUM_WARNING_KEY, DEFAULT_CHECKSUM_WARNING)


def label_columns(settings) -> int:
    try:
        value = int(settings.get(LABEL_COLUMNS_KEY, str(DEFAULT_LABEL_COLUMNS)))
    except (TypeError, ValueError):
        return DEFAULT_LABEL_COLUMNS
    return value if value in VALID_LABEL_COLUMNS else DEFAULT_LABEL_COLUMNS


def label_price_qr_default(settings) -> bool:
    return _flag(settings, LABEL_PRICE_QR_KEY, DEFAULT_LABEL_PRICE_QR)


def label_show_text(settings) -> bool:
    return _flag(settings, LABEL_SHOW_TEXT_KEY, DEFAULT_LABEL_SHOW_TEXT)


def label_size(settings) -> str:
    value = (settings.get(LABEL_SIZE_KEY, DEFAULT_LABEL_SIZE) or DEFAULT_LABEL_SIZE).strip()
    return value if value in LABEL_SIZE_DIMENSIONS else DEFAULT_LABEL_SIZE


def label_dimensions(settings) -> tuple[int, int]:
    return LABEL_SIZE_DIMENSIONS[label_size(settings)]


def scan_feedback_mode(settings) -> str:
    value = (settings.get(SCAN_FEEDBACK_KEY, DEFAULT_SCAN_FEEDBACK) or DEFAULT_SCAN_FEEDBACK).strip()
    return value if value in SCAN_FEEDBACK_LABELS else DEFAULT_SCAN_FEEDBACK


def stocktake_cooldown_ms(settings) -> int:
    """Minimum gap between two accepted scans of the *same* code, so a
    shaky hand or a scanner that free-runs for a fraction of a second
    longer than expected doesn't double-count one physical item."""
    try:
        value = int(settings.get(STOCKTAKE_COOLDOWN_KEY, str(DEFAULT_STOCKTAKE_COOLDOWN_MS)))
    except (TypeError, ValueError):
        return DEFAULT_STOCKTAKE_COOLDOWN_MS
    return value if value >= 0 else DEFAULT_STOCKTAKE_COOLDOWN_MS


def stocktake_sound_enabled(settings) -> bool:
    return _flag(settings, STOCKTAKE_SOUND_KEY, DEFAULT_STOCKTAKE_SOUND)


__all__ = [
    "KIND_KEY", "PREFIX_KEY", "AUTO_GENERATE_KEY", "SIMILAR_WARNING_KEY",
    "CHECKSUM_WARNING_KEY", "LABEL_COLUMNS_KEY", "LABEL_PRICE_QR_KEY",
    "LABEL_SHOW_TEXT_KEY", "LABEL_SIZE_KEY", "SCAN_FEEDBACK_KEY",
    "DEFAULT_KIND", "DEFAULT_PREFIX", "DEFAULT_AUTO_GENERATE",
    "DEFAULT_SIMILAR_WARNING", "DEFAULT_CHECKSUM_WARNING",
    "DEFAULT_LABEL_COLUMNS", "DEFAULT_LABEL_PRICE_QR", "DEFAULT_LABEL_SHOW_TEXT",
    "DEFAULT_LABEL_SIZE", "DEFAULT_SCAN_FEEDBACK",
    "KIND_LABELS", "LABEL_SIZE_DIMENSIONS", "LABEL_SIZE_LABELS",
    "SCAN_FEEDBACK_LABELS", "VALID_LABEL_COLUMNS",
    "STOCKTAKE_COOLDOWN_KEY", "STOCKTAKE_SOUND_KEY",
    "DEFAULT_STOCKTAKE_COOLDOWN_MS", "DEFAULT_STOCKTAKE_SOUND",
    "default_kind", "internal_prefix", "auto_generate_enabled",
    "similar_warning_enabled", "checksum_warning_enabled", "label_columns",
    "label_price_qr_default", "label_show_text", "label_size",
    "label_dimensions", "scan_feedback_mode",
    "stocktake_cooldown_ms", "stocktake_sound_enabled",
]
