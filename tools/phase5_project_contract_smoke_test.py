from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
database = (root / "src/qeid_offline/core/database.py").read_text(encoding="utf-8")
license_code = (root / "src/qeid_offline/services/license_service.py").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', pyproject, re.M)
assert match and tuple(map(int, match.groups())) >= (0, 5, 0)
build = re.search(r'^build_number\s*=\s*(\d+)', pyproject, re.M)
assert build and int(build.group(1)) >= 5
schema = re.search(r'^SCHEMA_VERSION\s*=\s*(\d+)', database, re.M)
assert schema and int(schema.group(1)) >= 4
assert "CREATE TABLE IF NOT EXISTS users" in database
# Phase-5 signed-token verifier remains for compatibility even though Phase 6
# uses the Hawaa activation Worker in production.
assert "RSASSA-PKCS1-v1_5" in license_code
all_code = "\n".join(p.read_text(encoding="utf-8", errors="ignore").lower() for p in (root / "src").rglob("*.py"))
for forbidden in ["telegram.webapp", "supabase", "vercel", "requests.get", "httpx"]:
    assert forbidden not in all_code, forbidden
print("phase5_project_contract_smoke_test passed")
