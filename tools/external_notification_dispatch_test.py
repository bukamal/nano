"""End-to-end test for PHASE11 external notification dispatch.

Runs fully offline: the only registered channel is a RecordingProvider that
never touches the network, so it exercises the real pipeline -- internal
rules engine -> per-rule routing -> retry/backoff wrapper -> per-channel
delivery log -> dedupe -- without needing credentials.

Usage:  PYTHONPATH=src python3 tools/external_notification_dispatch_test.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nano_offline.core.database import Database
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.settings_repository import SettingsRepository
from nano_offline.services.dashboard_service import DashboardService
from nano_offline.services.external_notifications import (
    ChannelError,
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


class BrokenProvider(ChannelProvider):
    name = "broken"

    def send(self, alert: Alert, channel_cfg: dict) -> None:
        raise ChannelError("خطأ محاكى في القناة")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nano_ext_notify_") as td:
        db_path = Path(td) / "nano.db"
        db = Database(db_path)
        db.initialize()

        settings = SettingsRepository(db)
        items = ItemRepository(db)
        reports = ReportingService(db)
        license = LicenseService(db)
        dashboard = DashboardService(db)
        notifications = NotificationService(db, settings, items, reports, license, dashboard)

        # Seed the scenario the internal engine flags: one low-stock item and
        # an unpaid sale invoice well past the 30-day overdue point.
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

        alerts = notifications.generate_alerts()
        assert alerts, "internal engine must raise alerts for the seeded data"
        print(f"[1] internal engine generated {len(alerts)} alert(s):")
        for a in alerts:
            print(f"    - [{a.severity:>7}] {a.rule_key}: {a.title} | {a.body}")

        recorder = RecordingProvider()
        external = ExternalNotificationService(db, settings, notifications)
        external.register_provider(recorder)
        external.save_config(
            {"channels": {"recorder": {"enabled": True}}, "rules": {"default": ["recorder"]}}
        )

        results = external.dispatch(force=True)
        print(f"[2] dispatch returned {len(results)} delivery result(s):")
        for r in results:
            print(f"    - {r.channel}: ok={r.ok} attempts={r.attempts} error={r.error!r}")
        assert recorder.sent, "alerts must be routed to the enabled recorder channel"
        assert len(recorder.sent) == len(results), "one delivery record per successful send"

        with db.connect() as conn:
            rows = conn.execute(
                "SELECT channel, rule_key, status, attempts FROM notification_delivery_log ORDER BY id"
            ).fetchall()
        print(f"[3] delivery log persisted {len(rows)} row(s):")
        for r in rows:
            print(f"    - {r['channel']} | {r['rule_key']} | {r['status']} | attempts={r['attempts']}")
        assert rows, "dispatch must persist delivery-log rows"

        second = external.dispatch(force=True)
        assert second == [], f"second dispatch must be deduped, got {second}"
        print("[4] second dispatch delivered nothing (dedupe via delivery log works)")

        # Per-rule routing: mute low_stock only; the other rules still flow.
        with db.transaction() as conn:
            conn.execute("DELETE FROM notification_delivery_log")
        external.save_config(
            {
                "channels": {"recorder": {"enabled": True}},
                "rules": {"low_stock": [], "default": ["recorder"]},
            }
        )
        recorder.sent.clear()
        routed = external.dispatch(alerts, force=True)
        delivered = {a.rule_key for a in recorder.sent}
        assert delivered and "low_stock" not in delivered, "per-rule routing must mute low_stock"
        print(f"[5] per-rule routing muted low_stock; delivered {sorted(delivered)}")

        # Failure path: a broken channel must be retried with backoff, marked
        # failed in the log, and retried again on the next dispatch.
        broken = BrokenProvider()
        external.register_provider(broken)
        external.save_config(
            {
                "channels": {"recorder": {"enabled": True}, "broken": {"enabled": True}},
                "rules": {"default": ["recorder", "broken"]},
                "retry": {"max_attempts": 2, "base_delay_seconds": 0.0},
            }
        )
        with db.transaction() as conn:
            conn.execute("DELETE FROM notification_delivery_log")
        recorder.sent.clear()
        results = external.dispatch(alerts, force=True)
        broken_results = [r for r in results if r.channel == "broken"]
        assert broken_results, "broken channel must be routed"
        assert all(not r.ok and r.attempts == 2 for r in broken_results), "retry must exhaust attempts"
        with db.connect() as conn:
            failed = conn.execute(
                "SELECT COUNT(*) c FROM notification_delivery_log "
                "WHERE channel='broken' AND status='failed'"
            ).fetchone()["c"]
        assert failed == len(broken_results), "every failed attempt set must be logged"
        print(f"[6] retry/backoff: broken channel failed after 2 attempts x {len(broken_results)} alert(s); "
              f"failed rows={failed}")

        again = external.dispatch(alerts, force=True)
        assert any(r.channel == "broken" for r in again), "failed deliveries must be retried next dispatch"
        print("[7] failed deliveries are retried on the next dispatch")

    print("external_notification_dispatch_test PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
