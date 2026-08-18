from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
assert tuple(int(x) for x in project["project"]["version"].split(".")) >= (0, 4, 0)
assert project["tool"]["flet"]["build_number"] >= 4
assert "flet==0.28.3" in project["project"]["dependencies"]

service = (ROOT / "src/qeid_offline/services/reporting_service.py").read_text(encoding="utf-8")
for token in [
    "def income_statement",
    "def invoice_profitability",
    "def item_profitability",
    "def inventory_report",
    "def inventory_valuation",
    "def party_balances",
    "def outstanding_invoices",
    "def cash_movement",
]:
    assert token in service, token

combined = "\n".join(
    p.read_text(encoding="utf-8", errors="ignore")
    for p in (ROOT / "src").rglob("*.py")
)
for forbidden in ["telegram", "supabase", "vercel", "requests.", "httpx."]:
    assert forbidden not in combined.lower(), forbidden
print("phase4_project_contract_smoke_test passed")
