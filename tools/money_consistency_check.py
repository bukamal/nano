"""Read-only money-consistency audit for a Nano database.

Usage:
    python tools/money_consistency_check.py path/to/nano.db [--json]

Runs core/money_consistency.run_checks against the database and reports any
violation of the money invariants (sub-cent storage noise, invoice line/total
rounding, ledger double-entry). Exits 0 when the database is clean, 1 when
issues are found -- so it plugs straight into the quality gate / CI.

Safe by construction: the database is opened with ``mode=ro`` whenever the
Python sqlite3 build supports URI mode, so it can never mutate the file under
audit.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.core import money_consistency  # noqa: E402


def open_readonly(path: str) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        # Very old builds without URI support lag the file-name workaround.
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    db_path = argv[0]
    as_json = "--json" in argv[1:]
    if not Path(db_path).exists():
        print(f"no such file: {db_path}", file=sys.stderr)
        return 2
    with open_readonly(db_path) as conn:
        issues = money_consistency.run_checks(conn)
    if as_json:
        print(json.dumps({"issues": issues}, ensure_ascii=False, indent=2))
    else:
        print(money_consistency.summarize(issues))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))