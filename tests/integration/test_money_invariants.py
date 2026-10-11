"""Property-based accounting invariants over a real AppContext/SQLite.
These are the executable definition of "the money discipline holds". They drive
the real services (invoice + accounting rebuilder) with randomly generated
invoices and assert, on every example, the invariants a bookkeeping system must
never violate:
* an invoice total is exactly the cent-sum of its own lines;
* paid never exceeds total, and remaining is exact;
* party balances equal invoices minus payments;
* inventory quantities are conserved (opening + purchases - sales);
* every ledger source balances debit vs credit (double entry);
* the tamper-evident audit chain stays valid.
They exist so any change to how money is stored (e.g. moving from ``REAL`` to
integer cents) can be proven not to break the accounting core.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from nano_offline.app_context import AppContext
from nano_offline.core import money
from nano_offline.core.audit_chain import verify_audit_chain
from nano_offline.core.money_consistency import run_checks
from nano_offline.services.invoice_service import InvoiceLineInput

_SETTINGS = settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

_OPENING_QTY = 100_000
_PRICES = st.integers(min_value=100, max_value=20_000).map(lambda cents: cents / 100)
_QUANTITIES = st.integers(min_value=1, max_value=50)
_SPECS = st.lists(st.tuples(_QUANTITIES, _PRICES), min_size=1, max_size=5)
# Bounded so that paid <= every generated invoice total (min total is $1.00).
_PAID_CENTS = st.integers(min_value=0, max_value=100)


def _open_ctx():
    tmp = tempfile.TemporaryDirectory(prefix="nano-money-")
    ctx = AppContext.create(Path(tmp.name) / "nano.db")
    return ctx, tmp


def _seed(ctx) -> tuple[int, int, int]:
    ctx.definitions.create_unit("قطعة", "ق")
    customer_id = ctx.customers.create("عميل")
    supplier_id = ctx.suppliers.create("مورد")
    item_id = ctx.items.create(
        name="مادة", purchase_price=10, selling_price=15, quantity=_OPENING_QTY
    )
    return customer_id, supplier_id, item_id


def _lines(item_id: int, specs) -> list[InvoiceLineInput]:
    return [
        InvoiceLineInput(description="", item_id=item_id, quantity=q, unit_price=p)
        for q, p in specs
    ]


def _expected_total_cents(specs) -> int:
    return sum(money.to_cents(money.quantized(q * p)) for q, p in specs)


def _total_base_qty(specs):
    return sum(q for q, _p in specs)


def _assert_ledger_and_audit_clean(ctx) -> None:
    with ctx.db.connect() as conn:
        issues = run_checks(conn)
    assert issues == [], issues
    assert verify_audit_chain(ctx.db)["valid"] is True


@_SETTINGS
@given(specs=_SPECS, paid_cents=_PAID_CENTS)
def test_sale_invoice_money_invariants(specs, paid_cents):
    ctx, tmp = _open_ctx()
    try:
        customer_id, _supplier_id, item_id = _seed(ctx)
        paid = paid_cents / 100
        invoice_id = ctx.invoices.create_invoice(
            invoice_type="sale",
            customer_id=customer_id,
            paid_amount=paid,
            lines=_lines(item_id, specs),
        )
        inv = ctx.invoices.get_invoice(invoice_id)

        # total is the cent-exact sum of its own lines
        assert money.to_cents(inv["total"]) == _expected_total_cents(specs)
        assert money.to_cents(inv["total"]) == sum(
            money.to_cents(line["total"]) for line in inv["lines"]
        )

        # paid <= total, and remaining is exact
        assert money.to_cents(inv["paid_amount"]) <= money.to_cents(inv["total"])
        assert money.to_cents(inv["total"] - inv["paid_amount"]) == (
            money.to_cents(inv["total"]) - money.to_cents(inv["paid_amount"])
        )
        assert inv["paid_amount"] == money.quantized(paid)

        # customer receivable == total - paid
        balance = ctx.customers.get(customer_id)["balance"]
        assert money.to_cents(balance) == (
            money.to_cents(inv["total"]) - money.to_cents(inv["paid_amount"])
        )

        # inventory conservation
        remaining = ctx.items.get(item_id)["quantity"]
        assert abs(remaining - (_OPENING_QTY - _total_base_qty(specs))) < 1e-6

        _assert_ledger_and_audit_clean(ctx)
    finally:
        tmp.cleanup()


@_SETTINGS
@given(specs=_SPECS, paid_cents=_PAID_CENTS)
def test_purchase_invoice_money_invariants(specs, paid_cents):
    ctx, tmp = _open_ctx()
    try:
        _customer_id, supplier_id, item_id = _seed(ctx)
        paid = paid_cents / 100
        invoice_id = ctx.invoices.create_invoice(
            invoice_type="purchase",
            supplier_id=supplier_id,
            paid_amount=paid,
            lines=_lines(item_id, specs),
        )
        inv = ctx.invoices.get_invoice(invoice_id)

        assert money.to_cents(inv["total"]) == _expected_total_cents(specs)
        assert money.to_cents(inv["paid_amount"]) <= money.to_cents(inv["total"])
        balance = ctx.suppliers.get(supplier_id)["balance"]
        assert money.to_cents(balance) == (
            money.to_cents(inv["total"]) - money.to_cents(inv["paid_amount"])
        )
        quantity = ctx.items.get(item_id)["quantity"]
        assert abs(quantity - (_OPENING_QTY + _total_base_qty(specs))) < 1e-6

        _assert_ledger_and_audit_clean(ctx)
    finally:
        tmp.cleanup()


@_SETTINGS
@given(specs=_SPECS)
def test_overpayment_is_rejected(specs):
    ctx, tmp = _open_ctx()
    try:
        customer_id, _supplier_id, item_id = _seed(ctx)
        over = (_expected_total_cents(specs) + 1) / 100
        with pytest.raises(ValueError):
            ctx.invoices.create_invoice(
                invoice_type="sale",
                customer_id=customer_id,
                paid_amount=over,
                lines=_lines(item_id, specs),
            )
    finally:
        tmp.cleanup()


@_SETTINGS
@given(paid_cents=st.integers(min_value=0, max_value=1_000))
def test_anonymous_sale_is_cash_settled(paid_cents):
    """A sale with no customer is fully settled even when less is passed as paid.

    The passed amount stays within the total (an overpayment is rejected by the
    normal validation); what matters is that a customerless sale can never end
    up as a receivable -- the service forces paid == total.
    """
    ctx, tmp = _open_ctx()
    try:
        _customer_id, _supplier_id, item_id = _seed(ctx)
        invoice_id = ctx.invoices.create_invoice(
            invoice_type="sale",
            customer_id=None,
            paid_amount=paid_cents / 100,
            lines=[InvoiceLineInput(description="", item_id=item_id, quantity=1, unit_price=10)],
        )
        inv = ctx.invoices.get_invoice(invoice_id)
        assert money.to_cents(inv["paid_amount"]) == money.to_cents(inv["total"])
        _assert_ledger_and_audit_clean(ctx)
    finally:
        tmp.cleanup()
