from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

print("▶ compileall", flush=True)
subprocess.run([sys.executable, "-m", "compileall", "-q", "src", "tools", "extensions/flet_native_files/src"], check=True, cwd=ROOT)

SCRIPTS = [
    "tools/schema_smoke_test.py",
    "tools/core_smoke_test.py",
    "tools/phase2_schema_upgrade_smoke_test.py",
    "tools/phase2_invoice_editor_core_smoke_test.py",
    "tools/phase2_flet_ui_contract_smoke_test.py",
    "tools/phase2_project_contract_smoke_test.py",
    "tools/phase3_schema_migration_smoke_test.py",
    "tools/phase3_financial_workflow_smoke_test.py",
    "tools/phase3_allocation_edge_cases_smoke_test.py",
    "tools/phase3_flet_ui_contract_smoke_test.py",
    "tools/phase3_project_contract_smoke_test.py",
    "tools/phase4_reporting_core_smoke_test.py",
    "tools/phase4_reporting_historical_smoke_test.py",
    "tools/phase4_flet_ui_contract_smoke_test.py",
    "tools/phase4_project_contract_smoke_test.py",
    "tools/phase5_schema_migration_smoke_test.py",
    "tools/phase5_auth_security_smoke_test.py",
    "tools/phase5_backup_restore_smoke_test.py",
    "tools/phase5_license_offline_smoke_test.py",
    "tools/phase5_admin_ui_contract_smoke_test.py",
    "tools/phase5_project_contract_smoke_test.py",
    "tools/phase6_hawaa_activation_contract_smoke_test.py",
    "tools/phase6_android_storage_smoke_test.py",
    "tools/phase6_activation_ui_contract_smoke_test.py",
    "tools/phase6_android_build_contract_smoke_test.py",
    "tools/phase7_service_cost_smoke_test.py",
    "tools/phase7_document_export_smoke_test.py",
    "tools/phase7_native_extension_packaging_smoke_test.py",
    "tools/phase7_ui_contract_smoke_test.py",
    "tools/phase7_1_android_ci_environment_smoke_test.py",
    "tools/phase7_2_flutter_dependency_alignment_smoke_test.py",
    "tools/phase7_project_contract_smoke_test.py",
    "tools/apk_release_preflight.py",
]

for script in SCRIPTS:
    print("▶", script, flush=True)
    subprocess.run([sys.executable, str(ROOT / script)], check=True, cwd=ROOT)
print("quality_gate passed")
