"""Unit tests for the money-consistency audit's amount-vs-ratio distinction.
The audit must flag sub-cent noise in money *amounts* while accepting derived
per-unit costs (weighted averages, value/quantity) which are ratios and have no
cent invariant. This is the regression guard for a false positive the
property-based suite surfaced on valid weighted-average costing.
"""
from __future__ import annotations

import sqlite3

from nano_offline.core import money_consistency

_SCHEMA = """
CREATE TABLE items(
    id INTEGER PRIMARY KEY, selling_price REAL, purchase_price REAL,
    average_cost REAL, opening_unit_cost REAL
);
CREATE TABLE item_units(id INTEGER PRIMARY KEY, selling_price REAL, purchase_price REAL);
CREATE TABLE invoice_lines(
    id INTEGER PRIMARY KEY, invoice_id INTEGER, unit_price REAL, quantity REAL,
    total REAL, unit_cost REAL, cost_amount REAL
);
CREATE TABLE invoices(
    id INTEGER PRIMARY KEY, total REAL, paid_amount REAL, initial_paid_amount REAL
);
CREATE TABLE ledger_entries(source_type TEXT, source_id INTEGER, debit REAL, credit REAL);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _subject(issues, kind, prefix):
    return [i for i in issues if i["kind"] == kind and i["subject"].startswith(prefix)]


def test_weighted_average_unit_costs_are_not_flagged():
    conn = _conn()
    # $10 / 3 units = 3.3333...: a legitimate, non-round unit cost.
    avg = 10 / 3
    conn.execute(
        "INSERT INTO items(id, selling_price, purchase_price, average_cost, opening_unit_cost)"
        " VALUES(1, 5.0, ?, ?, ?)",
        (avg, avg, avg),
    )
    conn.execute(
        "INSERT INTO invoice_lines(id, invoice_id, unit_price, quantity, total, unit_cost, cost_amount)"
        " VALUES(1, 1, 5.0, 1, 5.0, ?, 5.0)",
        (avg,),
    )
    conn.execute("INSERT INTO invoices(id, total, paid_amount, initial_paid_amount) VALUES(1, 5.0, 5.0, 5.0)")
    assert money_consistency.run_checks(conn) == []


def test_sub_cent_noise_in_an_amount_is_still_flagged():
    conn = _conn()
    conn.execute(
        "INSERT INTO items(id, selling_price, purchase_price, average_cost, opening_unit_cost)"
        " VALUES(1, 5.00000123, 0, 0, 0)"
    )
    conn.execute(
        "INSERT INTO invoice_lines(id, invoice_id, unit_price, quantity, total, unit_cost, cost_amount)"
        " VALUES(1, 1, 5.0, 1, 5.00000123, 0, 0)"
    )
    conn.execute("INSERT INTO invoices(id, total, paid_amount, initial_paid_amount) VALUES(1, 5.0, 5.0, 5.0)")
    issues = money_consistency.run_checks(conn)
    assert _subject(issues, "storage_clean", "items.selling_price")
    assert _subject(issues, "storage_clean", "invoice_lines.total")
