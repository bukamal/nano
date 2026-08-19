from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
database = (ROOT / "src/nano_offline/core/database.py").read_text(encoding="utf-8")
all_source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))

version = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', pyproject, re.M)
assert version and tuple(map(int, version.groups())) >= (0, 3, 0)
build = re.search(r'^build_number\s*=\s*(\d+)', pyproject, re.M)
assert build and int(build.group(1)) >= 3
assert "SCHEMA_VERSION = " in database
assert int(database.split("SCHEMA_VERSION = ", 1)[1].splitlines()[0].strip()) >= 3
for table in ["payment_allocations", "vouchers", "expense_categories"]:
    assert f"CREATE TABLE IF NOT EXISTS {table}" in database

# Offline accounting path: no web/database SDKs are dependencies or imported by app source.
for forbidden in ["supabase", "telegram", "vercel", "requests", "httpx", "firebase"]:
    assert forbidden.lower() not in all_source.lower(), forbidden

assert re.search(r'dependencies\s*=\s*\[\s*"flet==0\.28\.3"', pyproject, re.S)
print("phase3_project_contract_smoke_test passed")
