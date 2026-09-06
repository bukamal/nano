"""Test for PHASE11.1: the immediate-push hook.

Verifies that when the internal rules engine generates a NEW alert
(NotificationService.sync), it is pushed out through the external channel
right away via ExternalNotificationService.background_dispatch -- without
any explicit dispatch() call and without blocking the caller -- and that
a second sync() of the same condition adds nothing (delivery-log dedupe
still holds for the immediate path).

Usage:  PYTHONPATH=src python3 tools/external_immediate_hook_test.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nano_offline.core.database import Database
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.settings_repository import SettingsRepository
from nano_offline.services.dashboard_service import DashboardService
from nano_offline.services.external_notifications import (
    ChannelProvider,
    ExternalNotificationService,
)
from nano_offline.services.license_service import LicenseService
from nano_offline.services.notification_service import Alert, NotificationService
from nano_offline.services.reporting_service import ReportingService


class RecordingProvider(ChannelProvider):
    name = "recorder"

    def __init__(self) -> None:
        self.sent: list[Alert] = []

    def send(self, alert: Alert, channel_cfg: dict) -> None:
        self.sent.append(alert)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nano_ext_hook_") as td:
        db = Database(Path(td) / "nano.db")
        db.initialize()

        settings = SettingsRepository(db)
        items = ItemRepository(db)
        reports = ReportingService(db)
        license = LicenseService(db)
        dashboard = DashboardService(db)
        notifications = NotificationService(db, settings, items, reports, license, dashboard)

        with db.transaction() as conn:
            conn.execute("INSERT INTO categories(name) VALUES (?)", ("مواد",))
            cat_id = conn.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()["id"]
            conn.execute("INSERT INTO units(name) VALUES (?)", ("قطعة",))
            unit_id = conn.execute("SELECT id FROM units ORDER BY id LIMIT 1").fetchone()["id"]
            conn.execute(
                "INSERT INTO items(name, category_id, item_type, purchase_price, selling_price, quantity, base_unit_id) "
                "VALUES (?,?,?,?,?,?,?)",
                ("سكر", cat_id, "مخزون", 100, 150, 1, unit_id),
            )
            conn.execute("INSERT INTO customers(name) VALUES (?)", ("مشتري تجريبي",))
            cust_id = conn.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()["id"]
            overdue = (date.today() - timedelta(days=40)).isoformat()
            conn.execute(
                "INSERT INTO invoices(type, customer_id, invoice_date, reference, total, paid_amount, status) "
                "VALUES ('sale', ?, ?, 'TST-1', 5000, 0, 'posted')",
                (cust_id, overdue),
            )

        recorder = RecordingProvider()
        external = ExternalNotificationService(db, settings, notifications)
        external.register_provider(recorder)
        external.save_config(
            {"channels": {"recorder": {"enabled": True}}, "rules": {"default": ["recorder"]}}
        )
        # Wire the same hook AppContext.create() wires in production.
        notifications.set_external_hook(external.background_dispatch)

        print("[1] calling notifications.sync() (internal engine only)...")
        notifications.sync()
        time.sleep(0.6)  # the hook runs on a daemon thread -- give it a moment
        delivered = {a.rule_key for a in recorder.sent}
        print(f"    -> external channel received {len(recorder.sent)} alert(s) immediately: {sorted(delivered)}")
        assert delivered, "sync() must push NEW alerts through the external hook immediately"

        with db.connect() as conn:
            rows = conn.execute(
                "SELECT channel, rule_key, status FROM notification_delivery_log ORDER BY id"
            ).fetchall()
        print(f"[2] delivery log has {len(rows)} row(s) from the hooked dispatch")
        assert rows, "hooked dispatch must persist delivery-log rows"

        recorder.sent.clear()
        print("[3] calling sync() again with the same condition (still unresolved)...")
        notifications.sync()
        time.sleep(0.6)
        print(f"    -> second sync delivered {len(recorder.sent)} new alert(s)")
        assert not recorder.sent, "a condition already delivered today must not be re-sent"

    print("external_immediate_hook_test PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
