"""Property-based tests for core/money.py (no DB needed).
These lock the *contract* the accounting services rely on: every value that
passes through money.* is a clean cent value, quantizing is idempotent, and the
integer-cents view round-trips exactly. They are the safety net that makes a
future integer-cents storage migration safe to attempt.
"""
from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings, strategies as st

from nano_offline.core import money

_AMOUNTS = st.floats(
    min_value=-1_000_000_000, max_value=1_000_000_000, allow_nan=False, allow_infinity=False
)
_CENTS = st.integers(min_value=-10**11, max_value=10**11)


@settings(max_examples=300, deadline=None)
@given(_AMOUNTS)
def test_quantize_is_idempotent(value):
    once = money.quantize(value)
    assert money.quantize(once) == once


@settings(max_examples=300, deadline=None)
@given(_AMOUNTS)
def test_quantized_is_always_clean_cents(value):
    # Checked in Decimal, not float: scaling a large value by 100 in binary
    # floating point introduces noise (e.g. 536870912.69 * 100) that would
    # look like a money bug when it is only a representation artifact.
    scaled = money.quantize(value).scaleb(money.MONEY_DECIMALS)
    assert scaled == scaled.to_integral_value()


@settings(max_examples=300, deadline=None)
@given(_CENTS)
def test_int_cents_roundtrip(cents):
    assert money.to_cents(money.from_cents(cents)) == cents


@settings(max_examples=200, deadline=None)
@given(st.lists(_AMOUNTS, min_size=0, max_size=40))
def test_quantize_sum_equals_sum_of_quantized_addends(values):
    expected = money.quantize(sum((money.quantize(v) for v in values), Decimal(0)))
    assert money.quantize_sum(values) == expected


@settings(max_examples=200, deadline=None)
@given(st.lists(_AMOUNTS, min_size=0, max_size=40))
def test_quantize_sum_never_drifts_over_repeats(values):
    # Re-quantizing an already-quantized sum must not change it -- the property
    # that stops cents from "walking" when balances are recomputed every rebuild.
    total = money.quantize_sum(values)
    assert money.quantize(total) == total


def test_half_up_is_used_not_bankers():
    # The accounting convention here is half-up; banker's rounding would turn
    # 0.005 -> 0.00 and 0.015 -> 0.02 inconsistently.
    assert money.quantize(Decimal("0.0000005")) == Decimal("0.000001")
    assert money.quantize(Decimal("0.0000015")) == Decimal("0.000002")
    assert money.quantize(Decimal("0.0000025")) == Decimal("0.000003")
    assert money.quantize(Decimal("-0.0000005")) == Decimal("-0.000001")
