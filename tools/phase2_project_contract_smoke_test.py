from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))
database = (ROOT / "src/nano_offline/core/database.py").read_text(encoding="utf-8")

version = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', pyproject, re.M)
assert version and tuple(map(int, version.groups())) >= (0, 2, 0)
build = re.search(r'^build_number\s*=\s*(\d+)', pyproject, re.M)
assert build and int(build.group(1)) >= 2
schema = re.search(r'SCHEMA_VERSION\s*=\s*(\d+)', database)
assert schema and int(schema.group(1)) >= 2
assert '"flet==0.28.3"' in pyproject
# Offline-first: no online SaaS identifiers or mandatory web SDKs in src.
# "telegram" is excluded since PHASE11: it is an optional, user-configured
# notification channel isolated in services/external_notifications.py.
for forbidden in ["supabase", "vercel", "requests", "httpx"]:
    assert forbidden not in source.lower(), forbidden
print("phase2_project_contract_smoke_test passed")
