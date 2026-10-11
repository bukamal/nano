"""Process-level tests for the central logging + crash capture.
Run in subprocesses because ``setup_logging`` is deliberately idempotent
(first call wins) and installs global excepthooks -- exactly the behavior we
want to verify end-to-end without leaking handlers into the pytest process.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _run(code: str, data_dir: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "NANO_DATA_DIR": str(data_dir),
    }
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env=env
    )


def test_setup_logging_writes_rotating_log_file(tmp_path):
    data_dir = tmp_path / "data"
    code = (
        "from nano_offline.core.logging_config import setup_logging, get_logger, log_file_path\n"
        "setup_logging(console=False)\n"
        "get_logger('nano.test').warning('hello-from-test')\n"
        "print(log_file_path())\n"
    )
    result = _run(code, data_dir)
    assert result.returncode == 0, result.stderr
    log_path = Path(result.stdout.strip().splitlines()[-1])
    assert log_path.is_file()
    assert "hello-from-test" in log_path.read_text(encoding="utf-8")
    assert log_path.parent == data_dir / "logs"


def test_setup_logging_is_idempotent(tmp_path):
    code = (
        "from nano_offline.core.logging_config import setup_logging\n"
        "import logging\n"
        "setup_logging(console=False)\n"
        "n = len(logging.getLogger().handlers)\n"
        "setup_logging(console=False)\n"
        "print(len(logging.getLogger().handlers) == n)\n"
    )
    result = _run(code, tmp_path / "data")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "True"


def test_uncaught_exception_is_captured_to_crash_log(tmp_path):
    data_dir = tmp_path / "data"
    code = (
        "from nano_offline.core.logging_config import setup_logging, crash_file_path\n"
        "setup_logging(console=False)\n"
        "raise ValueError('boom-marker')\n"
    )
    result = _run(code, data_dir)
    # The original excepthook still runs, so the process exits non-zero.
    assert result.returncode != 0
    crash = data_dir / "logs" / "crash.log"
    assert crash.is_file()
    text = crash.read_text(encoding="utf-8")
    assert "boom-marker" in text
    assert "ValueError" in text
