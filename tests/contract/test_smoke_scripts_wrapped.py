"""Wrap the legacy tools/ smoke+contract scripts as pytest tests.

The 60-odd ``tools/*_smoke_test.py`` scripts are the phase-by-phase
contract authority for this project (schema upgrades, financial workflow,
Android build contracts, RTL print templates, ...). Migrating their bodies
into pytest files by hand would be a large mechanical churn with real risk
of silently dropping an assertion, so the migration keeps each script as
the single source of truth and *wraps* it: pytest runs each script as a
subprocess with the same ``PYTHONPATH=src`` it always required, and any
non-zero exit fails the wrapped test.

Benefits of the wrapper layer (over running quality_gate.py alone):

* per-script pass/fail in pytest output and ``-k``/``--lf`` selection;
* coverage of subprocess work when the gate runs everything under
  ``coverage run`` (the scripts import ``nano_offline`` in-process);
* one place to mark slow / flet-dependent scripts as ``contract``.

``tools/quality_gate.py`` keeps invoking the scripts directly for the
standalone path, so nothing that used to work stops working if pytest is
absent.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"

# Every standalone checker under tools/ except the gate orchestrator and the
# CI helper (verify_flet_native_files_registration takes an argument).
SCRIPTS = sorted(
    p.name
    for p in TOOLS.glob("*_test.py")
    if p.name != "quality_gate.py"
) + ["apk_release_preflight.py", "money_consistency_check.py"]

# Some scripts insert src/ onto sys.path themselves; several others were only
# ever run via quality_gate.py which exports PYTHONPATH=src. Provide the same
# environment so the wrapper matches how the scripts actually run today.
_ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}


@pytest.mark.contract
@pytest.mark.parametrize("script", SCRIPTS)
def test_smoke_script(script):
    path = TOOLS / script
    assert path.is_file(), f"missing {path}"
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        env=_ENV,
    )
    assert result.returncode == 0, f"{script} failed:\n{result.stdout}\n{result.stderr}"
