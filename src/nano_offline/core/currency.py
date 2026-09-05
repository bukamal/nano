"""Dual-currency support: values are always *stored* in USD; the UI, the
printed invoices/receipts and every report *display* the equivalent amount
in whichever currency the user has chosen to see -- Syrian pounds (SYP,
the default) or US dollars (USD).

Nothing about the database schema changes -- every numeric money column
(``selling_price``, ``unit_price``, ``amount`` ...) keeps holding a plain
USD float exactly as before. This module is the single place that knows
how to turn a stored USD number into the figure a user should see (and
back again when a user *types* a figure into a form), for whichever
display currency is currently selected.

Both the exchange rate (how many SYP equal one USD, e.g. ``13500``) and
the *chosen display currency* live in the open-ended ``settings``
key/value table like every other branding/config value, under
:data:`EXCHANGE_RATE_KEY` and :data:`DISPLAY_CURRENCY_KEY` respectively,
so either can be changed from the admin screen without a schema migration
and takes effect immediately everywhere.

When the display currency is SYP, amounts are multiplied by the exchange
rate exactly as before. When it is USD, the display currency *is* the
stored currency, so conversion is the identity (rate=1) -- what you see is
exactly what is stored, just formatted with 2 decimal places instead of 0
(cents matter for dollars; they never did for pounds).
"""

from __future__ import annotations

STORED_CURRENCY_CODE = "USD"
DISPLAY_CURRENCY_CODE = "SYP"  # kept for backward compatibility; prefer get_display_currency()

DISPLAY_CURRENCY_SYP = "SYP"
DISPLAY_CURRENCY_USD = "USD"
SUPPORTED_DISPLAY_CURRENCIES = (DISPLAY_CURRENCY_SYP, DISPLAY_CURRENCY_USD)
DEFAULT_DISPLAY_CURRENCY = DISPLAY_CURRENCY_SYP

DEFAULT_DISPLAY_SYMBOL = "ل.س"
DEFAULT_USD_DISPLAY_SYMBOL = "$"
_DEFAULT_SYMBOL_BY_CURRENCY = {
    DISPLAY_CURRENCY_SYP: DEFAULT_DISPLAY_SYMBOL,
    DISPLAY_CURRENCY_USD: DEFAULT_USD_DISPLAY_SYMBOL,
}
_DEFAULT_DECIMALS_BY_CURRENCY = {
    DISPLAY_CURRENCY_SYP: 0,
    DISPLAY_CURRENCY_USD: 2,
}

EXCHANGE_RATE_KEY = "exchange_rate_syp_per_usd"
DISPLAY_SYMBOL_KEY = "display_currency_symbol"
USD_DISPLAY_SYMBOL_KEY = "display_currency_symbol_usd"
DISPLAY_CURRENCY_KEY = "display_currency_code"
_SYMBOL_KEY_BY_CURRENCY = {
    DISPLAY_CURRENCY_SYP: DISPLAY_SYMBOL_KEY,
    DISPLAY_CURRENCY_USD: USD_DISPLAY_SYMBOL_KEY,
}

DEFAULT_EXCHANGE_RATE = 13500.0


def get_display_currency(settings) -> str:
    """Return which currency amounts should be *displayed* in: ``"SYP"`` or ``"USD"``.

    Falls back to :data:`DEFAULT_DISPLAY_CURRENCY` (SYP) for a fresh database,
    a missing/blank setting, or any unrecognised value -- so old databases
    that predate this setting keep behaving exactly as before.
    """
    raw = settings.get(DISPLAY_CURRENCY_KEY, "") if settings is not None else ""
    code = str(raw or "").strip().upper()
    return code if code in SUPPORTED_DISPLAY_CURRENCIES else DEFAULT_DISPLAY_CURRENCY


def get_exchange_rate(settings) -> float:
    """Return how many SYP equal 1 USD right now (falls back to the default).

    This is the *configured* SYP rate regardless of which currency is
    currently displayed -- it stays remembered/editable even while USD
    display is active, so switching back to SYP display doesn't lose it.
    Use :func:`get_effective_rate` for actual conversions.
    """
    raw = settings.get(EXCHANGE_RATE_KEY, "") if settings is not None else ""
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_EXCHANGE_RATE
    return rate if rate > 0 else DEFAULT_EXCHANGE_RATE


def get_effective_rate(settings) -> float:
    """Return the rate that should actually be used to convert stored USD
    into the *currently displayed* currency.

    ``1.0`` when the display currency is USD (display == stored, no
    conversion), otherwise the configured SYP-per-USD rate.
    """
    if get_display_currency(settings) == DISPLAY_CURRENCY_USD:
        return 1.0
    return get_exchange_rate(settings)


def _default_decimals(settings) -> int:
    return _DEFAULT_DECIMALS_BY_CURRENCY.get(get_display_currency(settings), 0)


def get_display_symbol(settings) -> str:
    """Return the symbol/label to print after amounts, for whichever
    currency is currently displayed (each currency remembers its own
    symbol independently, so switching modes never leaves a stale "ل.س"
    next to a dollar figure or vice versa).
    """
    if settings is None:
        return DEFAULT_DISPLAY_SYMBOL
    display_currency = get_display_currency(settings)
    key = _SYMBOL_KEY_BY_CURRENCY[display_currency]
    return settings.get(key, "") or _DEFAULT_SYMBOL_BY_CURRENCY[display_currency]


def to_display(amount_usd: float | int | None, rate: float) -> float:
    """Convert a stored USD amount into the displayed amount at ``rate``.

    Pass ``1.0`` (or :func:`get_effective_rate` in USD mode) when the
    display currency is USD -- the conversion is then the identity.
    """
    return float(amount_usd or 0) * float(rate or 0)


def to_stored(amount_displayed: float | int | None, rate: float) -> float:
    """Convert a displayed-currency amount a user typed in back into USD for storage."""
    rate = float(rate or 0) or DEFAULT_EXCHANGE_RATE
    return float(amount_displayed or 0) / rate


# NOTE: this used to wrap every "amount symbol" string in U+2066/U+2069
# (LEFT-TO-RIGHT ISOLATE / POP DIRECTIONAL ISOLATE) to pin the amount before
# the symbol regardless of surrounding context. In practice that isolate is
# exactly what causes the symbol to flip sides once the amount is embedded
# inside a longer Arabic sentence (e.g. "دفعة جزئية — سيُسجَّل 1,000 ل.س على
# حساب العميل") -- the Bidi algorithm treats the isolated run as a single
# strongly-LTR unit and reorders it against the Arabic text around it.
# Plain, unwrapped text -- exactly like the dashboard's exchange-rate box
# ("13,500 ل.س"), which never used this wrapping -- renders in the correct
# amount-then-symbol order in every context, so the isolate is dropped
# entirely rather than reworked.
_LRI = ""
_PDI = ""


def _amount_with_symbol(text: str, symbol: str) -> str:
    return f"{text} {symbol}"


def format_amount(
    amount_usd: float | int | None,
    settings=None,
    *,
    rate: float | None = None,
    symbol: str | None = None,
    with_symbol: bool = True,
    decimals: int | None = None,
) -> str:
    """Format a *stored* USD amount as text in the currently displayed currency.

    ``decimals`` defaults to 0 for SYP (amounts are large, so fractional
    pounds carry no useful meaning) and 2 for USD (cents matter). Pass an
    explicit value to override either way.
    """
    if rate is None:
        rate = get_effective_rate(settings)
    if symbol is None:
        symbol = get_display_symbol(settings)
    if decimals is None:
        decimals = _default_decimals(settings)
    value = to_display(amount_usd, rate)
    text = f"{value:,.{decimals}f}"
    return _amount_with_symbol(text, symbol) if with_symbol else text


def _round_for_input(value: float, *, decimals: int = 2) -> str:
    return f"{value:.0f}" if abs(value - round(value)) < 0.005 else f"{value:.{decimals}f}"


def to_input_text(amount_usd: float | int | None, settings=None, *, rate: float | None = None) -> str:
    """Plain (no thousands separator, no symbol) text for an editable field,
    in the currently displayed currency."""
    if rate is None:
        rate = get_effective_rate(settings)
    value = to_display(amount_usd, rate)
    # Whole figures are the common case; keep decimals only when they matter.
    return _round_for_input(value)


def format_plain(value: float | int | None) -> str:
    """Format a value that is *already* in the display currency -- no conversion, no symbol.

    Use this for numbers derived purely from other already-converted, on-screen
    figures (e.g. quantity × an already-converted unit price entered live in a
    form), where converting again would double-convert.
    """
    return _round_for_input(float(value or 0))


def format_display_value(value: float | int | None, settings=None, *, symbol: str | None = None, with_symbol: bool = True, decimals: int | None = None) -> str:
    """Format a value that is *already* in the display currency, with thousands separators."""
    if symbol is None:
        symbol = get_display_symbol(settings)
    if decimals is None:
        decimals = _default_decimals(settings)
    text = f"{float(value or 0):,.{decimals}f}"
    return _amount_with_symbol(text, symbol) if with_symbol else text


def amount_field_label(base_label: str, settings=None) -> str:
    """Build a form-field label that names the currently displayed currency,
    e.g. ``"المبلغ (ل.س)"`` in SYP mode or ``"المبلغ ($)"`` in USD mode.

    Use this instead of hard-coding "(ل.س)" in any label for a field whose
    value is entered/shown in the display currency, so the label stays
    correct when the admin switches the display currency.
    """
    return f"{base_label} ({get_display_symbol(settings)})"


def parse_display_input(text: str | int | float | None, settings=None, *, rate: float | None = None) -> float:
    """Parse a figure a user typed into a field, in the currently displayed
    currency, and return the USD value to store."""
    if rate is None:
        rate = get_effective_rate(settings)
    if text is None or text == "":
        return 0.0
    cleaned = str(text).replace(",", "").strip()
    if not cleaned:
        return 0.0
    try:
        displayed_value = float(cleaned)
    except ValueError:
        raise ValueError(f"قيمة غير صالحة: {text}") from None
    return to_stored(displayed_value, rate)


__all__ = [
    "STORED_CURRENCY_CODE",
    "DISPLAY_CURRENCY_CODE",
    "DISPLAY_CURRENCY_SYP",
    "DISPLAY_CURRENCY_USD",
    "SUPPORTED_DISPLAY_CURRENCIES",
    "DEFAULT_DISPLAY_CURRENCY",
    "DEFAULT_DISPLAY_SYMBOL",
    "DEFAULT_USD_DISPLAY_SYMBOL",
    "EXCHANGE_RATE_KEY",
    "DISPLAY_SYMBOL_KEY",
    "USD_DISPLAY_SYMBOL_KEY",
    "DISPLAY_CURRENCY_KEY",
    "DEFAULT_EXCHANGE_RATE",
    "get_display_currency",
    "get_exchange_rate",
    "get_effective_rate",
    "get_display_symbol",
    "to_display",
    "to_stored",
    "amount_field_label",
    "format_amount",
    "format_plain",
    "format_display_value",
    "to_input_text",
    "parse_display_input",
]
