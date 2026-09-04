from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from nano_offline.core.database import Database
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.settings_repository import SettingsRepository
from nano_offline.services.dashboard_service import DashboardService
from nano_offline.services.license_service import LicenseService
from nano_offline.services.reporting_service import ReportingService

SETTINGS_KEY = "notifications_config"

# Every rule the "everything" scope from PHASE9 covers. Kept as one JSON blob
# under a single settings row (see the comment on notification_log in
# core/database.py) instead of one settings key per field, so the whole
# config reads/writes atomically and adding a new tunable later never needs
# another migration.
DEFAULT_CONFIG: dict = {
    "receivables": {
        "enabled": True,
        "priority": "warning",       # info | warning | urgent
        "remind_before_days": 3,     # start warning this many days before "overdue"
        "overdue_after_days": 30,    # an unpaid sale invoice counts as overdue past this age
    },
    "low_stock": {
        "enabled": True,
        "priority": "warning",
        "default_threshold": 5,      # quantity at/below this triggers an alert
    },
    "backup": {
        "enabled": True,
        "priority": "warning",
        "remind_after_days": 7,
    },
    "license": {
        "enabled": True,
        "priority": "urgent",
        "remind_before_days": 14,
    },
    "insights": {
        "enabled": True,
        "priority": "info",
        "drop_percent": 30,          # flag today's sales if this far below the 7-day average
    },
    "quiet_hours": {
        "enabled": False,
        "start_hour": 22,
        "end_hour": 8,
    },
    "daily_check_hour": 9,
}

_PRIORITY_RANK = {"info": 0, "warning": 1, "urgent": 2}


@dataclass(slots=True, frozen=True)
class Alert:
    rule_key: str
    dedupe_key: str
    severity: str
    title: str
    body: str
    entity_type: str | None = None
    entity_id: int | None = None


def _merge_config(stored: dict) -> dict:
    """Fill in any rule/field missing from a saved config with its default.

    Lets new rule types ship later (e.g. a phase-10 addition) without
    breaking users who already customized and saved an older config.
    """
    merged = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    for key, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


class NotificationService:
    """Rules engine that turns existing accounting/inventory data into
    in-app smart alerts.

    Deliberately reads through the same services/repositories every view
    already uses (``ReportingService.outstanding_invoices``, ``ItemRepository
    .list``, ``LicenseService.status`` ...) instead of duplicating their SQL,
    so an alert can never disagree with what the rest of the app shows.
    Nothing here writes back to accounting or stock data -- the only table
    this service owns is ``notification_log``, and only for dedupe/read state.
    """

    def __init__(
        self,
        db: Database,
        settings: SettingsRepository,
        items: ItemRepository,
        reports: ReportingService,
        license: LicenseService,
        dashboard: DashboardService,
    ):
        self.db = db
        self.settings = settings
        self.items = items
        self.reports = reports
        self.license = license
        self.dashboard = dashboard

    # -- configuration --------------------------------------------------
    def get_config(self) -> dict:
        raw = self.settings.get(SETTINGS_KEY, "")
        try:
            stored = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            stored = {}
        return _merge_config(stored)

    def native_schedule_payload(self) -> dict:
        """Build the args for ``NativeFiles.schedule_notifications``.

        Kept here (next to get_config()) so the background Android check and
        the in-app rules engine always agree on the exact same config and
        never drift apart from having two places that build it. The DB path
        is the real on-disk path (``Database.path``), not anything derived
        independently, so the background isolate is guaranteed to open the
        same file this session is writing to.
        """
        cfg = self.get_config()
        return {
            "config_json": json.dumps(cfg, ensure_ascii=False),
            "db_path": str(self.db.path),
            "interval_minutes": 360,  # 6h -- Android periodic WorkManager floor is 15min anyway
            # Anchors the *first* run of that 6h cycle close to the admin's
            # preferred "داعي الفحص اليومي" hour instead of whatever moment
            # happened to call this (app open, a settings save, a reboot).
            # Every run after that still just follows the fixed interval
            # above -- this only stops the very first alert of the day from
            # landing at a random hour.
            "initial_delay_minutes": self._minutes_until_daily_check_hour(cfg),
        }

    @staticmethod
    def _minutes_until_daily_check_hour(cfg: dict) -> int:
        try:
            target_hour = int(cfg.get("daily_check_hour", 9)) % 24
        except (TypeError, ValueError):
            target_hour = 9
        now = datetime.now()
        target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(0, int((target - now).total_seconds() // 60))

    def save_config(self, config: dict) -> None:
        self.settings.set(SETTINGS_KEY, json.dumps(_merge_config(config), ensure_ascii=False))

    # -- rule evaluation --------------------------------------------------
    def _receivables_alerts(self, cfg: dict, today: date) -> list[Alert]:
        rule = cfg["receivables"]
        if not rule.get("enabled", True):
            return []
        overdue_after = int(rule.get("overdue_after_days", 30))
        remind_before = int(rule.get("remind_before_days", 3))
        try:
            rows = self.reports.outstanding_invoices("customer")
        except Exception:
            return []

        overdue: list[dict] = []
        due_soon: list[dict] = []
        for row in rows:
            raw_date = str(row.get("invoice_date") or "")[:10]
            try:
                invoice_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            age = (today - invoice_date).days
            if age >= overdue_after:
                overdue.append(row)
            elif age >= overdue_after - remind_before:
                due_soon.append(row)

        alerts: list[Alert] = []
        if overdue:
            total = sum(float(r.get("remaining_amount") or 0) for r in overdue)
            alerts.append(
                Alert(
                    rule_key="receivables_overdue",
                    dedupe_key=f"receivables_overdue:{today.isoformat()}",
                    severity="urgent",
                    title=f"{len(overdue)} فاتورة متأخرة السداد",
                    body=f"إجمالي المتأخر {total:,.0f} — أقدمها {self._party_hint(overdue)}",
                    entity_type="customer",
                )
            )
        if due_soon:
            alerts.append(
                Alert(
                    rule_key="receivables_due_soon",
                    dedupe_key=f"receivables_due_soon:{today.isoformat()}",
                    severity=rule.get("priority", "warning"),
                    title=f"{len(due_soon)} فاتورة تقترب من التأخر",
                    body="راجع كشوف الحساب قبل أن تتحول لذمم متأخرة.",
                    entity_type="customer",
                )
            )
        return alerts

    @staticmethod
    def _party_hint(rows: list[dict]) -> str:
        if not rows:
            return ""
        oldest = min(rows, key=lambda r: str(r.get("invoice_date") or ""))
        return str(oldest.get("party_name") or "")

    def _low_stock_alerts(self, cfg: dict) -> list[Alert]:
        rule = cfg["low_stock"]
        if not rule.get("enabled", True):
            return []
        threshold = float(rule.get("default_threshold", 5))
        try:
            all_items = self.items.list()
        except Exception:
            return []
        low = [
            i for i in all_items
            if str(i.get("item_type")) == "مخزون" and float(i.get("quantity") or 0) <= threshold
        ]
        if not low:
            return []
        names = "، ".join(str(i["name"]) for i in low[:4])
        if len(low) > 4:
            names += f" و{len(low) - 4} أخرى"
        return [
            Alert(
                rule_key="low_stock",
                dedupe_key=f"low_stock:{date.today().isoformat()}",
                severity=rule.get("priority", "warning"),
                title=f"{len(low)} صنف بحاجة تزويد",
                body=names,
                entity_type="item",
            )
        ]

    def _backup_alerts(self, cfg: dict, today: date) -> list[Alert]:
        rule = cfg["backup"]
        if not rule.get("enabled", True):
            return []
        remind_after = int(rule.get("remind_after_days", 7))
        last_raw = self.settings.get("last_backup_at", "")
        if not last_raw:
            # Don't nag a brand-new install with nothing to protect yet.
            try:
                has_invoices = bool(self.reports.outstanding_invoices("customer")) or bool(
                    self.reports.outstanding_invoices("supplier")
                )
            except Exception:
                has_invoices = True
            if not has_invoices:
                return []
            return [
                Alert(
                    rule_key="backup_missing",
                    dedupe_key=f"backup_missing:{today.isoformat()}",
                    severity=rule.get("priority", "warning"),
                    title="لا توجد نسخة احتياطية بعد",
                    body="خذ نسخة احتياطية أولى من مركز الإدارة.",
                )
            ]
        try:
            last_dt = datetime.fromisoformat(last_raw)
        except ValueError:
            return []
        days_since = (datetime.now().astimezone() - last_dt.astimezone()).days
        if days_since >= remind_after:
            return [
                Alert(
                    rule_key="backup_due",
                    dedupe_key=f"backup_due:{today.isoformat()}",
                    severity=rule.get("priority", "warning"),
                    title="حان وقت نسخة احتياطية جديدة",
                    body=f"آخر نسخة كانت منذ {days_since} يومًا.",
                )
            ]
        return []

    def _license_alerts(self, cfg: dict, today: date) -> list[Alert]:
        rule = cfg["license"]
        if not rule.get("enabled", True):
            return []
        try:
            status = self.license.status()
        except Exception:
            return []
        expires_raw = getattr(status, "expires_at", None)
        if not expires_raw:
            return []
        try:
            expiry = date.fromisoformat(str(expires_raw)[:10])
        except ValueError:
            return []
        days_left = (expiry - today).days
        remind_before = int(rule.get("remind_before_days", 14))
        if days_left > remind_before:
            return []
        severity = "urgent" if days_left <= 3 else rule.get("priority", "warning")
        title = "الترخيص منتهٍ" if days_left < 0 else f"الترخيص ينتهي خلال {days_left} يوم"
        return [
            Alert(
                rule_key="license_expiry",
                dedupe_key=f"license_expiry:{today.isoformat()}",
                severity=severity,
                title=title,
                body="جدّد الترخيص لتفادي توقف التفعيل.",
            )
        ]

    def _insight_alerts(self, cfg: dict, today: date) -> list[Alert]:
        rule = cfg["insights"]
        if not rule.get("enabled", True):
            return []
        drop_percent = float(rule.get("drop_percent", 30))
        try:
            with self.db.connect() as conn:
                today_sales = float(
                    conn.execute(
                        "SELECT COALESCE(SUM(total),0) FROM invoices WHERE type='sale' AND invoice_date=?",
                        (today.isoformat(),),
                    ).fetchone()[0]
                )
                week_ago = (today - timedelta(days=7)).isoformat()
                yesterday = (today - timedelta(days=1)).isoformat()
                avg_row = conn.execute(
                    "SELECT COALESCE(AVG(daily_total),0) FROM ("
                    "  SELECT invoice_date, SUM(total) AS daily_total FROM invoices"
                    "  WHERE type='sale' AND invoice_date BETWEEN ? AND ?"
                    "  GROUP BY invoice_date"
                    ")",
                    (week_ago, yesterday),
                ).fetchone()
                avg_sales = float(avg_row[0] or 0)
        except Exception:
            return []
        if avg_sales <= 0:
            return []
        drop = (avg_sales - today_sales) / avg_sales * 100
        if drop >= drop_percent:
            return [
                Alert(
                    rule_key="sales_drop",
                    dedupe_key=f"sales_drop:{today.isoformat()}",
                    severity=rule.get("priority", "info"),
                    title="مبيعات اليوم أقل من المعتاد",
                    body=f"أقل من متوسط آخر 7 أيام بنسبة {drop:.0f}%.",
                )
            ]
        return []

    def generate_alerts(self) -> list[Alert]:
        cfg = self.get_config()
        today = date.today()
        alerts: list[Alert] = []
        alerts += self._receivables_alerts(cfg, today)
        alerts += self._low_stock_alerts(cfg)
        alerts += self._backup_alerts(cfg, today)
        alerts += self._license_alerts(cfg, today)
        alerts += self._insight_alerts(cfg, today)
        alerts.sort(key=lambda a: _PRIORITY_RANK.get(a.severity, 0), reverse=True)
        return alerts

    # -- persistence (dedupe + read state) --------------------------------
    def sync(self) -> None:
        """Recompute alerts and record any new ones in ``notification_log``.

        Uses ``INSERT OR IGNORE`` on the unique ``dedupe_key`` -- an
        already-seen, still-unresolved condition is a no-op here, and only a
        genuinely new day/condition inserts a fresh (unread) row.
        """
        alerts = self.generate_alerts()
        if not alerts:
            return
        with self.db.transaction() as conn:
            for alert in alerts:
                conn.execute(
                    """INSERT OR IGNORE INTO notification_log
                       (dedupe_key, rule_key, severity, title, body, entity_type, entity_id)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        alert.dedupe_key,
                        alert.rule_key,
                        alert.severity,
                        alert.title,
                        alert.body,
                        alert.entity_type,
                        alert.entity_id,
                    ),
                )

    def recent(self, limit: int = 30) -> list[dict]:
        self.sync()
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_log ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def unread_count(self) -> int:
        self.sync()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM notification_log WHERE read_at IS NULL"
            ).fetchone()
            return int(row[0] or 0)

    def unread_summary(self) -> dict:
        """Unread counts broken down by severity (plus a ``total``), so the
        bell badge can reflect *how urgent* the pile-up is at a glance --
        e.g. showing red the moment even one urgent alert is unread -- 
        instead of a plain "something's unread" dot that looks the same
        whether it's one low-priority insight or three overdue invoices."""
        self.sync()
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT severity, COUNT(*) FROM notification_log WHERE read_at IS NULL GROUP BY severity"
            ).fetchall()
        counts = {"urgent": 0, "warning": 0, "info": 0}
        for severity, count in rows:
            if severity in counts:
                counts[severity] = int(count)
        counts["total"] = sum(counts.values())
        return counts

    def mark_read(self, notification_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE notification_log SET read_at=CURRENT_TIMESTAMP WHERE id=? AND read_at IS NULL",
                (notification_id,),
            )

    def mark_all_read(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE notification_log SET read_at=CURRENT_TIMESTAMP WHERE read_at IS NULL")

    def record_backup_completed(self) -> None:
        """Called right after a successful backup so the reminder rule resets."""
        self.settings.set("last_backup_at", datetime.now().astimezone().isoformat(timespec="seconds"))


__all__ = ["NotificationService", "Alert", "DEFAULT_CONFIG"]
