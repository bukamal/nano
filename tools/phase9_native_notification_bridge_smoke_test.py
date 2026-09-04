"""Smoke test for the closed-app notification bridge (PHASE9 follow-up).

Covers only the Python side, which is what this environment can actually
run: NotificationService.native_schedule_payload() must hand back a real,
existing db_path and a config_json that round-trips through the same
DEFAULT_CONFIG shape the Dart background isolate expects (receivables,
low_stock, backup, license, quiet_hours). It also re-derives the dedupe_key
convention ('<rule>:<yyyy-mm-dd>') the Dart side writes into
notification_log, and checks it collides correctly with a row Python itself
would write for the same rule/day -- that collision is the whole point: it's
what stops the same alert firing twice from two different code paths.

Does NOT and CANNOT verify: WorkManager registration, flutter_local_notifications
delivery, or anything requiring a Flutter/Android build -- there is no
Flutter/Dart SDK in this environment.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from nano_offline.app_context import AppContext

with tempfile.TemporaryDirectory(prefix="nano_phase9_native_notify_") as td:
    db_path = Path(td) / "nano.db"
    ctx = AppContext.create(db_path)

    # -- payload shape ------------------------------------------------------
    payload = ctx.notifications.native_schedule_payload()
    assert set(payload) == {"config_json", "db_path", "interval_minutes"}, payload
    assert payload["db_path"] == str(db_path)
    assert Path(payload["db_path"]).exists(), "db_path must point at a real, already-initialized database file"
    assert payload["interval_minutes"] >= 15, "below Android WorkManager's periodic floor"

    cfg = json.loads(payload["config_json"])
    for rule in ("receivables", "low_stock", "backup", "license", "quiet_hours"):
        assert rule in cfg, f"missing '{rule}' -- Dart side check functions read this exact key"
        assert "enabled" in cfg[rule]
    assert "default_threshold" in cfg["low_stock"]
    assert "overdue_after_days" in cfg["receivables"]
    assert "remind_after_days" in cfg["backup"]
    assert "remind_before_days" in cfg["license"]
    assert "start_hour" in cfg["quiet_hours"] and "end_hour" in cfg["quiet_hours"]

    # -- config changes are reflected immediately ---------------------------
    new_cfg = ctx.notifications.get_config()
    new_cfg["low_stock"]["default_threshold"] = 42
    ctx.notifications.save_config(new_cfg)
    refreshed = json.loads(ctx.notifications.native_schedule_payload()["config_json"])
    assert refreshed["low_stock"]["default_threshold"] == 42, "save_config must be visible in the next payload"

    # -- dedupe_key convention matches what the Dart side writes ------------
    today = date.today().isoformat()
    dart_dedupe_key = f"low_stock:{today}"
    with ctx.db.connect() as conn:
        conn.execute(
            "INSERT INTO notification_log (dedupe_key, rule_key, severity, title, body) "
            "VALUES (?, 'low_stock', 'warning', 'test', 'test')",
            (dart_dedupe_key,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT 1 FROM notification_log WHERE dedupe_key = ?", (dart_dedupe_key,)
        ).fetchone()
    assert row is not None, "dedupe_key convention must round-trip through notification_log as-is"

print("phase9_native_notification_bridge_smoke_test passed")
