"""Quantized money arithmetic.

Stored amounts are floats everywhere for backward compatibility, but IEEE-754
floats cannot represent most decimal fractions exactly (``0.1 + 0.2`` is
``0.30000000000000004``). Over hundreds or thousands of posted invoices,
payments and allocations that binary noise silently accumulates into phantom
fractions of a cent on balances, totals and COGS.

The fix this module provides is discipline at the *write boundary*: every
money value computed and stored by the accounting services is quantized to 2
decimal places (round-half-up) first, so the database only ever holds clean
cent values. Reads/sums then have nothing exotic left to accumulate.

Helpers:

- :func:`quantize` -- round any amount to cents (half-up). Apply on WRITE,
  per line / per transaction.
- :func:`quantized` -- quantize but return a plain ``float``, the type every
  ``REAL`` column and the whole UI currently use.
- :func:`quantize_sum` -- sum an iterable quantizing at *every* step (not just
  once at the end), mirroring how each stored value is already clean.
- :func:`to_cents` / :func:`from_cents` -- exact integer-cents view of a value,
  the basis of the money-consistency checks and the stepping stone to a full
  integer-typed money migration (see ``tools/money_consistency_check.py``).

``Decimal(str(value))`` is deliberately used over ``Decimal(value)`` so a
stored ``0.1`` is read as the decimal it displays as, not its full binary
expansion; ``ROUND_HALF_UP`` is chosen over banker's rounding because this is
financial data where the convention here (and in most retail/accounting in
Arabic-speaking markets) is half-up.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

MONEY_DECIMALS = 2
CENTS_PER_UNIT = 10**MONEY_DECIMALS
_CENTS_QUANTUM = Decimal(1).scaleb(-MONEY_DECIMALS)


def _as_decimal(value: Decimal | float | int | str | None) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, float):
        # Challenge: the shortest text form of a float is the decimal the
        # user *meant*; the full binary form is what the float actually is.
        # For money we want the former (a stored 0.1 was almost certainly
        # typed/displayed as 0.1).
        if value == int(value):
            return Decimal(int(value))
        return Decimal(repr(value)).quantize(_CENTS_QUANTUM, rounding=ROUND_HALF_UP)
    return Decimal(value)


def quantize(value, /, decimals: int = MONEY_DECIMALS) -> Decimal:
    """Round ``value`` to ``decimals`` places (half-up) as a :class:`Decimal`.

    ``decimals`` is only ever increased from the default; the stored money
    precision is cents and nothing in this app uses sub-cent money.
    """
    quantum = Decimal(1).scaleb(-decimals)
    return _as_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def quantized(value, /, decimals: int = MONEY_DECIMALS) -> float:
    """Quantize ``value`` and return it as a plain ``float`` (the stored type)."""
    return float(quantize(value, decimals=decimals))


def quantize_sum(values: Iterable, /, decimals: int = MONEY_DECIMALS) -> Decimal:
    """Sum an iterable of amounts, quantizing every addend and the result.

    This mirrors the application's write behavior (each stored transaction is
    already a clean cent value) so a recomputation agrees with the stored sum
    instead of drifting away from it.
    """
    total = Decimal(0)
    for value in values:
        total += quantize(value, decimals=decimals)
    return quantize(total, decimals=decimals)


def to_cents(value, /) -> int:
    """Exact integer cents for ``value`` (quantized, half-up)."""
    return int(quantize(value) * CENTS_PER_UNIT)


def from_cents(cents: int, /) -> Decimal:
    """Decode an integer cents count back to a :class:`Decimal` amount."""
    return (Decimal(int(cents)) / CENTS_PER_UNIT).normalize()


__all__ = [
    "MONEY_DECIMALS",
    "CENTS_PER_UNIT",
    "quantize",
    "quantized",
    "quantize_sum",
    "to_cents",
    "from_cents",
]