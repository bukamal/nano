from __future__ import annotations

import json
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage

from nano_offline.core.database import Database
from nano_offline.repositories.settings_repository import SettingsRepository
from nano_offline.services.notification_service import Alert, NotificationService

SETTINGS_KEY = "external_notifications_config"

# Every external channel this build ships. Tokens/secrets are kept out of
# the code: they live either in the stored config (set from the admin side)
# or in environment variables (see _ENV_OVERRIDES), never hard-coded here.
DEFAULT_EXTERNAL_CONFIG: dict = {
    "channels": {
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "username": "",
            "password": "",
            "to_address": "",
            "use_tls": True,
        },
        "webhook": {"enabled": False, "url": ""},
    },
    "rules": {
        # rule_key -> channels to fan that rule out to. A rule missing from
        # this map uses "default" (all enabled channels). Rule *enablement*,
        # thresholds and priorities stay owned by the internal engine
        # (notifications_config) -- this map only routes already-generated
        # alerts to the channels the admin chose, per event type.
        "default": ["telegram", "email", "webhook"],
    },
    "retry": {"max_attempts": 3, "base_delay_seconds": 1.0},
}

# Optional secrets from the environment override stored config (handy for
# desktop dev / CI; the packaged Android app always uses stored config).
_ENV_OVERRIDES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("channels", "telegram", "bot_token"), "TELEGRAM_BOT_TOKEN"),
    (("channels", "telegram", "chat_id"), "TELEGRAM_CHAT_ID"),
    (("channels", "email", "smtp_host"), "SMTP_HOST"),
    (("channels", "email", "smtp_port"), "SMTP_PORT"),
    (("channels", "email", "username"), "SMTP_USERNAME"),
    (("channels", "email", "password"), "SMTP_PASSWORD"),
    (("channels", "email", "to_address"), "SMTP_TO_ADDRESS"),
    (("channels", "webhook", "url"), "NOTIFY_WEBHOOK_URL"),
)


class ChannelError(RuntimeError):
    """Raised by a provider when one delivery attempt definitively failed."""


@dataclass(slots=True, frozen=True)
class DeliveryResult:
    channel: str
    ok: bool
    attempts: int
    error: str = ""


class ChannelProvider:
    """Interface every external channel adapter implements."""

    name: str = "base"

    def send(self, alert: Alert, channel_cfg: dict) -> None:
        raise NotImplementedError


def _merge_external_config(stored: dict) -> dict:
    """Deep-merge a saved config over the defaults (3 levels deep for
    channels/rules). Lets new channels or routing keys ship in later
    builds without breaking an already-customized stored config."""
    merged = json.loads(json.dumps(DEFAULT_EXTERNAL_CONFIG))
    for key, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            inner = merged[key]
            for k2, v2 in value.items():
                if isinstance(v2, dict) and isinstance(inner.get(k2), dict):
                    inner[k2].update(v2)
                else:
                    inner[k2] = v2
        else:
            merged[key] = value
    return merged


class TelegramProvider(ChannelProvider):
    name = "telegram"

    def send(self, alert: Alert, channel_cfg: dict) -> None:
        token = str(channel_cfg.get("bot_token") or "").strip()
        chat_id = str(channel_cfg.get("chat_id") or "").strip()
        if not token or not chat_id:
            raise ChannelError("Telegram: bot_token و chat_id غير مضبوطين")
        text = f"🔔 {alert.title}\n{alert.body}\n\n— نانو ({alert.rule_key} / {alert.severity})"
        payload = json.dumps({"chat_id": chat_id, "text": text}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", "replace")
                data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise ChannelError(
                f"Telegram: HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
            ) from exc
        except Exception as exc:
            raise ChannelError(f"Telegram: {exc}") from exc
        if not data.get("ok"):
            raise ChannelError(f"Telegram refused: {data.get('description') or raw[:200]}")


class SmtpEmailProvider(ChannelProvider):
    name = "email"

    def send(self, alert: Alert, channel_cfg: dict) -> None:
        host = str(channel_cfg.get("smtp_host") or "").strip()
        username = str(channel_cfg.get("username") or "").strip()
        password = str(channel_cfg.get("password") or "").strip()
        to_address = str(channel_cfg.get("to_address") or "").strip()
        if not host or not username or not to_address:
            raise ChannelError("email: smtp_host/username/to_address غير مضبوطين")
        try:
            port = int(channel_cfg.get("smtp_port") or 587)
        except (TypeError, ValueError):
            port = 587
        use_tls = bool(channel_cfg.get("use_tls", True))
        msg = EmailMessage()
        msg["Subject"] = f"[نانو] {alert.title}"
        msg["From"] = username
        msg["To"] = to_address
        msg.set_content(f"{alert.body}\n\n(تنبيه ذكي من نانو — {alert.rule_key} / {alert.severity})")
        try:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if password:
                    smtp.login(username, password)
                smtp.send_message(msg)
        except Exception as exc:
            raise ChannelError(f"email: {exc}") from exc


class WebhookProvider(ChannelProvider):
    name = "webhook"

    def send(self, alert: Alert, channel_cfg: dict) -> None:
        url = str(channel_cfg.get("url") or "").strip()
        if not url:
            raise ChannelError("webhook: url غير مضبوط")
        payload = json.dumps(
            {
                "app": "nano",
                "dedupe_key": alert.dedupe_key,
                "rule_key": alert.rule_key,
                "severity": alert.severity,
                "title": alert.title,
                "body": alert.body,
                "entity_type": alert.entity_type,
                "entity_id": alert.entity_id,
                "sent_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    raise ChannelError(f"webhook: HTTP {resp.status}")
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(f"webhook: {exc}") from exc


class ExternalNotificationService:
    """PHASE11: the shared dispatch layer between the internal smart-alert
    engine (NotificationService) and external delivery channels.

    The internal engine stays the single source of truth: exactly the same
    alerts the bell panel shows (same rules, thresholds, priorities,
    dedupe keys, quiet hours) are what this service fans out to Telegram /
    email / a generic webhook. Nothing is recomputed here and nothing new
    is invented -- this layer only routes already-generated alerts, applies
    per-rule channel routing, retries failed sends with exponential backoff,
    and keeps an audit trail in notification_delivery_log so a given alert
    is never delivered twice to the same channel.
    """

    def __init__(
        self,
        db: Database,
        settings: SettingsRepository,
        notifications: NotificationService,
    ) -> None:
        self.db = db
        self.settings = settings
        self.notifications = notifications
        self._providers: dict[str, ChannelProvider] = {
            TelegramProvider.name: TelegramProvider(),
            SmtpEmailProvider.name: SmtpEmailProvider(),
            WebhookProvider.name: WebhookProvider(),
        }

    def register_provider(self, provider: ChannelProvider) -> None:
        """Add/replace a channel adapter (used by tests and future channels)."""
        self._providers[provider.name] = provider

    # -- configuration ------------------------------------------------------
    def get_config(self) -> dict:
        raw = self.settings.get(SETTINGS_KEY, "")
        try:
            stored = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            stored = {}
        merged = _merge_external_config(stored)
        for path, env_name in _ENV_OVERRIDES:
            value = os.environ.get(env_name, "").strip()
            if value:
                node = merged
                for part in path[:-1]:
                    node = node[part]
                node[path[-1]] = value
        return merged

    def save_config(self, config: dict) -> None:
        self.settings.set(SETTINGS_KEY, json.dumps(_merge_external_config(config), ensure_ascii=False))

    def set_channel(self, channel: str, **fields) -> None:
        """Enable/configure one channel, e.g.
        set_channel("telegram", enabled=True, bot_token=..., chat_id=...)"""
        cfg = self.get_config()
        cfg["channels"].setdefault(channel, {})
        cfg["channels"][channel].update(fields)
        self.save_config(cfg)

    # -- quiet hours (shared semantics with the in-app engine + Dart) -------
    @staticmethod
    def _in_quiet_hours(cfg: dict) -> bool:
        quiet = cfg.get("quiet_hours") or {}
        if quiet.get("enabled") is not True:
            return False
        try:
            start = int(quiet.get("start_hour", 22)) % 24
            end = int(quiet.get("end_hour", 8)) % 24
        except (TypeError, ValueError):
            return False
        if start == end:
            return False
        hour = datetime.now().hour
        return (start < end and start <= hour < end) or (start > end and (hour >= start or hour < end))

    # -- routing / delivery ---------------------------------------------------
    def _resolve_channels(self, cfg: dict, alert: Alert) -> list[str]:
        rules = cfg.get("rules") or {}
        # An explicit per-rule entry wins even when it is an empty list
        # (the admin intentionally muted that rule type) -- only fall back
        # to "default" when the rule key is absent entirely. `or` cannot
        # be used here: [] is falsy and would wrongly fall through.
        routing = rules.get(alert.rule_key)
        if routing is None:
            routing = rules.get("default") or []
        channels = cfg.get("channels") or {}
        return [name for name in routing if (channels.get(name) or {}).get("enabled")]

    def _send_with_retry(self, provider: ChannelProvider, alert: Alert, cfg: dict, channel: str) -> tuple[int, str, bool]:
        retry = cfg.get("retry") or {}
        try:
            max_attempts = max(1, int(retry.get("max_attempts", 3)))
        except (TypeError, ValueError):
            max_attempts = 3
        try:
            base_delay = max(0.0, float(retry.get("base_delay_seconds", 1.0)))
        except (TypeError, ValueError):
            base_delay = 1.0
        last_error = "لم تُعرَّف القناة"
        provider_cfg = (cfg.get("channels") or {}).get(channel) or {}
        for attempt in range(1, max_attempts + 1):
            try:
                provider.send(alert, provider_cfg)
                return attempt, "", True
            except Exception as exc:  # noqa: BLE001 -- a failing channel must never break the loop
                last_error = str(exc)
                if attempt < max_attempts:
                    time.sleep(base_delay * (2 ** (attempt - 1)))
        return max_attempts, last_error[:500], False

    def _record(self, conn, alert: Alert, channel: str, attempts: int, error: str, ok: bool) -> None:
        conn.execute(
            """INSERT INTO notification_delivery_log
               (dedupe_key, channel, rule_key, severity, title, body, status, attempts, error, sent_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(dedupe_key, channel) DO UPDATE SET
                 status=excluded.status, attempts=excluded.attempts, error=excluded.error,
                 sent_at=excluded.sent_at, title=excluded.title, body=excluded.body,
                 severity=excluded.severity, rule_key=excluded.rule_key""",
            (
                alert.dedupe_key,
                channel,
                alert.rule_key,
                alert.severity,
                alert.title,
                alert.body,
                "sent" if ok else "failed",
                attempts,
                error or None,
                datetime.now().isoformat(timespec="seconds") if ok else None,
            ),
        )

    def dispatch(self, alerts: list[Alert] | None = None, *, force: bool = False) -> list[DeliveryResult]:
        """Send every pending generated alert once per enabled channel.

        Uses the SAME dedupe_key convention as the internal engine and the
        Dart background isolate ('<rule>:<yyyy-mm-dd>'), so a condition
        already delivered today is never sent again by any path. Returns
        per-channel DeliveryResult records for callers that want to surface
        failures. ``force=True`` bypasses quiet hours (tests / manual probe).
        """
        cfg_ext = self.get_config()
        if not force and self._in_quiet_hours(self.notifications.get_config()):
            return []
        if not any((c or {}).get("enabled") for c in (cfg_ext.get("channels") or {}).values()):
            return []
        alerts = list(alerts) if alerts is not None else self.notifications.generate_alerts()
        results: list[DeliveryResult] = []
        with self.db.transaction() as conn:
            for alert in alerts:
                for channel in self._resolve_channels(cfg_ext, alert):
                    existing = conn.execute(
                        "SELECT status FROM notification_delivery_log WHERE dedupe_key=? AND channel=?",
                        (alert.dedupe_key, channel),
                    ).fetchone()
                    if existing is not None and existing["status"] == "sent":
                        continue
                    provider = self._providers.get(channel)
                    if provider is None:
                        continue
                    attempts, error, ok = self._send_with_retry(provider, alert, cfg_ext, channel)
                    self._record(conn, alert, channel, attempts, error, ok)
                    results.append(DeliveryResult(channel=channel, ok=ok, attempts=attempts, error=error))
        return results

    async def dispatch_async(self, **kwargs) -> list[DeliveryResult]:
        """Non-blocking variant for Flet's run_task: runs the blocking
        dispatch (network I/O + backoff sleeps) off the UI thread."""
        import asyncio

        return await asyncio.to_thread(self.dispatch, **kwargs)

    def background_dispatch(self, alerts: list[Alert] | None = None, **kwargs) -> None:
        """PHASE11.1: fire-and-forget dispatch from a daemon thread, used as
        the external hook the moment the internal engine generates a NEW
        alert (see NotificationService.sync/set_external_hook). Never blocks
        the caller; quiet hours and the delivery log are still enforced
        inside dispatch(), so at most one delivery per (dedupe_key, channel)."""
        import threading

        threading.Thread(
            target=self.dispatch,
            kwargs={"alerts": alerts, **kwargs},
            daemon=True,
        ).start()

    # -- observability --------------------------------------------------------
    def delivery_log(self, limit: int = 50) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_delivery_log ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def test_channel(self, channel: str) -> DeliveryResult:
        """Send a synthetic probe alert through one channel and record it."""
        probe = Alert(
            rule_key="test_probe",
            dedupe_key=f"test_probe:{datetime.now().strftime('%Y%m%d%H%M%S')}",
            severity="info",
            title="إشعار اختبار من نانو",
            body="وصل هذا الإشعار عبر قناة خارجية — نظام التوصيل يعمل.",
        )
        cfg_ext = self.get_config()
        provider = self._providers.get(channel)
        if provider is None:
            return DeliveryResult(channel=channel, ok=False, attempts=0, error="قناة غير معروفة")
        attempts, error, ok = self._send_with_retry(provider, probe, cfg_ext, channel)
        with self.db.transaction() as conn:
            self._record(conn, probe, channel, attempts, error, ok)
        return DeliveryResult(channel=channel, ok=ok, attempts=attempts, error=error)


__all__ = [
    "ExternalNotificationService",
    "ChannelProvider",
    "ChannelError",
    "DeliveryResult",
    "TelegramProvider",
    "SmtpEmailProvider",
    "WebhookProvider",
    "DEFAULT_EXTERNAL_CONFIG",
    "SETTINGS_KEY",
]
