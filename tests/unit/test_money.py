"""Unit tests for core/money.py quantization discipline."""
from __future__ import annotations

from decimal import Decimal

import pytest

from nano_offline.core import money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.1 + 0.2, 0.3),
        (0.1 * 3, 0.3),
        (1.005, 1.01),  # half-up, not banker's
        (2.675, 2.68),
        ("10.00", 10.0),
        (None, 0.0),
        ("", 0.0),
        (7, 7.0),
        (Decimal("0.1"), 0.1),
    ],
)
def test_quantized_half_up(raw, expected):
    assert money.quantized(raw) == expected


def test_quantize_returns_decimal():
    assert money.quantize("0.005") == Decimal("0.01")
    assert isinstance(money.quantize(1), Decimal)


def test_quantize_sum_steps_every_addend():
    assert float(money.quantize_sum([0.1, 0.2, 0.4])) == 0.7
    assert money.quantize_sum([]) == Decimal("0.00")


def test_cents_roundtrip():
    for value in (0.1, 0.3, 1234.56, 0.0, -4.25):
        assert money.from_cents(money.to_cents(value)) == Decimal(str(value)).quantize(Decimal("0.01"))


def test_to_cents_exact_int():
    assert money.to_cents(0.3) == 30
    assert money.to_cents("1.10") == 110
    assert isinstance(money.to_cents(2.222), int)


def test_higher_decimals_allowed():
    # Note: float inputs are snapped to cents inside _as_decimal first (the
    # module's stated write-boundary discipline), so sub-cent precision only
    # survives via str/Decimal inputs.
    assert money.quantize(Decimal("1.23456"), decimals=4) == Decimal("1.2346")
    assert money.quantize("1.23456", decimals=4) == Decimal("1.2346")
    assert money.quantize(1.23456, decimals=4) == Decimal("1.2300")


def test_float_repr_edge_cases():
    # 2.0 must read as the integer 2, not 1.99999... expansions
    assert money.quantized(2.0) == 2.0
    assert money.to_cents(1000000.01) == 100000001
