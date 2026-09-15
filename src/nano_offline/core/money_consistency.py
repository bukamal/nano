"""Money-consistency audit over a Nano database (read-only).

Stage-1 money discipline (see ``core/money.py``): every money value written by
the accounting services is quantized to cents (2dp, round-half-up) *before* it
hits a ``REAL`` column, so storage never accumulates binary-float noise.

This module audits whether an existing database already obeys the invariants
that discipline protects:

- ``storage_clean``      -- every money column holds values with no sub-cent noise.
- ``invoice_line_total`` -- ``invoice_lines.total`` is exactly
  ``cents(unit_price * quantity)`` for that line.
- ``invoice_total``      -- ``invoices.total`` is exactly the sum of the cents
  of its own lines.
- ``invoice_paid_clean`` -- ``paid_amount`` / ``initial_paid_amount`` are clean
  cents (they are user-entered, but must still be stored cleanly).
- ``double_entry``       -- for every ledger source (invoice/payment/expense),
  ``sum(debit) == sum(credit)`` (to half a cent), the fundamental accounting
  invariant.

Everything here is read-only; it only reports. The CLI wrapper
``tools/money_consistency_check.py`` runs it against a database path and exits
non-zero when issues are found, so it can be wired into the quality gate / CI
as a regression net while the app itself keeps running.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from nano_offline.core import money

# Money-bearing columns per table. Exchange rates are deliberately excluded:
# they are conversion ratios, not amounts, and have no cent invariant.
MONEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": ("balance",),
    "suppliers": ("balance",),
    "items": ("purchase_price", "selling_price", "average_cost", "opening_unit_cost"),
    "item_units": ("selling_price", "purchase_price"),
    "invoices": ("total", "initial_paid_amount", "paid_amount"),
    "invoice_lines": ("unit_price", "total", "unit_cost", "cost_amount"),
    "payments": ("amount",),
    "payment_allocations": ("amount",),
    "vouchers": ("amount",),
    "inventory_movements": ("unit_cost", "value_delta"),
    "ledger_entries": ("debit", "credit"),
    "expenses": ("amount",),
}

_STORAGE_TOLERANCE_CENTS = 1e-6  # abs(value*100 - round(value*100)) must stay under this
_UNQUIET_PENNY = Decimal("0.005")  # flags sums more than half a cent apart


def _exact(value) -> Decimal:
    """The exact decimal the float actually stores (keeps binary noise visible)."""
    return Decimal(repr(float(value)))


def _is_dirty_cents(value) -> bool:
    scaled = float(value) * 100.0
    return abs(scaled - round(scaled)) > _STORAGE_TOLERANCE_CENTS


def run_checks(conn: sqlite3.Connection) -> list[dict]:
    """Audit ``conn`` and return a list of issue dicts. Empty means clean.

    Each issue: ``{"kind", "subject", "expected", "actual", "diff"}`` where
    ``expected``/``actual``/``diff`` are decimal strings.
    """
    issues: list[dict] = []

    # 1) storage_clean -- sub-cent garbage anywhere a money value lives.
    for table, columns in MONEY_COLUMNS.items():
        try:
            rows = conn.execute(f"SELECT id, {', '.join(columns)} FROM {table}").fetchall()
        except sqlite3.OperationalError:
            # Table may legitimately not exist on a fresh/partial schema.
            continue
        for row in rows:
            for column in columns:
                raw = row[column]
                if raw is None:
                    continue
                if _is_dirty_cents(raw):
                    issues.append(
                        {
                            "kind": "storage_clean",
                            "subject": f"{table}.{column}=#{row['id']}",
                            "expected": str(money.quantized(raw)),
                            "actual": str(_exact(raw)),
                            "diff": str(_exact(raw) - money.quantize(raw)),
                        }
                    )

    # 2) invoice_line_total -- each line total is exactly cents(price * qty).
    for row in conn.execute(
        "SELECT id, invoice_id, unit_price, quantity, total FROM invoice_lines"
    ):
        expected = money.to_cents(float(row["unit_price"] or 0) * float(row["quantity"] or 0))
        actual = money.to_cents(float(row["total"]))
        if actual != expected:
            issues.append(
                {
                    "kind": "invoice_line_total",
                    "subject": f"invoice_lines.total=#{row['id']} (inv #{row['invoice_id']})",
                    "expected": str(money.from_cents(expected)),
                    "actual": str(money.from_cents(actual)),
                    "diff": str(money.from_cents(actual - expected)),
                }
            )

    # 3) invoice_total -- totals equal the cents-sum of their own lines.
    lines_per_invoice: dict[int, Decimal] = {}
    for row in conn.execute("SELECT invoice_id, total FROM invoice_lines"):
        lines_per_invoice[int(row["invoice_id"])] = (
            lines_per_invoice.get(int(row["invoice_id"]), Decimal(0))
            + money.quantize(float(row["total"]))
        )
    for inv in conn.execute("SELECT id, total FROM invoices"):
        expected = money.to_cents(lines_per_invoice.get(int(inv["id"]), Decimal(0)))
        actual = money.to_cents(float(inv["total"]))
        if actual != expected:
            issues.append(
                {
                    "kind": "invoice_total",
                    "subject": f"invoices.total=#{inv['id']}",
                    "expected": str(money.from_cents(expected)),
                    "actual": str(money.from_cents(actual)),
                    "diff": str(money.from_cents(actual - expected)),
                }
            )

    # 4) invoice_paid_clean -- entered-paid amounts must still store cleanly.
    for row in conn.execute("SELECT id, paid_amount, initial_paid_amount FROM invoices"):
        for column in ("paid_amount", "initial_paid_amount"):
            raw = row[column]
            if raw is None:
                continue
            if _is_dirty_cents(raw):
                issues.append(
                    {
                        "kind": "invoice_paid_clean",
                        "subject": f"invoices.{column}=#{row['id']}",
                        "expected": str(money.quantized(raw)),
                        "actual": str(_exact(raw)),
                        "diff": str(_exact(raw) - money.quantize(raw)),
                    }
                )

    # 5) double_entry -- every ledger source balances debit vs credit.
    ledger = conn.execute(
        """SELECT source_type, source_id,
                  SUM(debit) AS debit, SUM(credit) AS credit
           FROM ledger_entries
           GROUP BY source_type, source_id"""
    ).fetchall()
    for row in ledger:
        debit = _exact(row["debit"] or 0)
        credit = _exact(row["credit"] or 0)
        diff = money.quantize(debit) - money.quantize(credit)
        if abs(diff) > _UNQUIET_PENNY:
            issues.append(
                {
                    "kind": "double_entry",
                    "subject": f"ledger {row['source_type']}=#{row['source_id']}",
                    "expected": str(money.quantize(credit)),
                    "actual": str(money.quantize(debit)),
                    "diff": str(money.quantize(diff)),
                }
            )

    return issues


def summarize(issues: list[dict]) -> str:
    if not issues:
        return "money-consistency: OK (no issues)"
    lines = [f"money-consistency: {len(issues)} issue(s)"]
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["kind"]] = counts.get(issue["kind"], 0) + 1
    lines.append("  " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for issue in issues[:20]:
        lines.append(
            f"  - {issue['kind']} | {issue['subject']} | "
            f"expected={issue['expected']} actual={issue['actual']} diff={issue['diff']}"
        )
    if len(issues) > 20:
        lines.append(f"  ... and {len(issues) - 20} more")
    return "\n".join(lines)


__all__ = ["MONEY_COLUMNS", "run_checks", "summarize"]