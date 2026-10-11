from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
# Version lives in the single source of truth (version.py); pyproject resolves
# it dynamically, so it has no literal [project].version anymore.
import re

version_py = (ROOT / "src/nano_offline/version.py").read_text(encoding="utf-8")
app_version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', version_py).group(1)
assert tuple(int(x) for x in app_version.split(".")) >= (0, 4, 0)
assert project["tool"]["flet"]["build_number"] >= 4
assert "flet==0.28.3" in project["project"]["dependencies"]

service = (ROOT / "src/nano_offline/services/reporting_service.py").read_text(encoding="utf-8")
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
# Telegram was added legitimately in PHASE11 (optional notification channel);
# the offline-first guard remains for real SaaS SDKs and credential leaks.
for forbidden in ["supabase", "vercel", "requests.", "httpx."]:
    assert forbidden not in combined.lower(), forbidden
print("phase4_project_contract_smoke_test passed")
