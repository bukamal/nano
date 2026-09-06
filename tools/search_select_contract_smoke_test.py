from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Contract: mostly customer-facing screens must use search-select, not raw
# Dropdown. Screens that legitimately still use ft.Dropdown for small fixed
# option lists are pinned as EXEMPT so the intent stays explicit.
EXEMPT = ['admin_view.py', 'finance_view.py', 'items_view.py', 'notifications_view.py', 'reports_view.py']
joined = ""
for p in (ROOT / "src").rglob("*.py"):
    if p.name in EXEMPT:
        continue
    joined += p.read_text(encoding="utf-8")
assert "ft.Dropdown(" not in joined, "ft.Dropdown( outside exempt screens"
print("search_select_contract_smoke_test passed")
