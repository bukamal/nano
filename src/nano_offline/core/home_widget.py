from __future__ import annotations

"""FIX_0.9.3: home widget snapshot is now built from the same services and
settings the in-app screens use, so the widget can never drift from what the
app shows.

Root cause of "الودجت لا يأخذ بياناته جيدًا من المشروع" fixed in 0.9.3:
  - amounts were pushed as raw stored USD, without converting through the
    user's display-currency settings and without a currency symbol, while the
    app displays SYP (or USD) with a symbol;
  - the header was hard-coded to "Nano | نانو" instead of the store name;
  - today's invoice count and overdue totals were never pushed.

home_widget_snapshot() now converts with currency.get_effective_rate() /
get_display_symbol() exactly like DashboardView.money(), reads the store name
from settings (company_name), includes sales_count_today and overdue_total,
and stamps updated_at in UTC ISO 8601. The alert counts use the same rules as
the Dart periodic pass (native_files.dart _pushHomeWidgetSnapshot) so the two
refresh paths never disagree.
"""

from datetime import datetime, timezone

from nano_offline.core import currency


def home_widget_snapshot(dashboard, settings=None) -> dict:
    """Build the snapshot the widget needs.

    Pass the SettingsRepository (``ctx.settings``) when available so the
    widget converts to the user's display currency and shows the store name;
    without it the snapshot falls back to defaults but stays structurally
    identical (old call sites keep working unchanged).
    """
    today = dashboard.today_summary()
    overall = dashboard.summary()
    rate = (
        currency.get_effective_rate(settings)
        if settings is not None
        else currency.DEFAULT_EXCHANGE_RATE
    )
    symbol = (
        currency.get_display_symbol(settings)
        if settings is not None
        else currency.DEFAULT_DISPLAY_SYMBOL
    )
    store_name = ""
    if settings is not None:
        try:
            store_name = (settings.get("company_name") or "").strip()
        except Exception:
            store_name = ""

    snapshot = {
        "sales_today": currency.to_display(today["total"], rate),
        "sales_count_today": int(today["count"]),
        "cash_balance": currency.to_display(overall["cash"], rate),
        "currency_symbol": symbol,
        "store_name": store_name,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    # Alerts -- same queries as the Dart periodic pass so the status pill and
    # the periodic refresh never disagree. Failure here must not block the
    # KPI push, so it is intentionally swallowed.
    try:
        with dashboard.db.connect() as conn:
            overdue = conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(total-paid_amount),0) AS t "
                "FROM invoices WHERE type='sale' AND status!='cancelled' AND (total-paid_amount)>0.01"
            ).fetchone()
            low = conn.execute(
                "SELECT COUNT(*) AS c FROM items WHERE item_type='مخزون' AND quantity<=5"
            ).fetchone()
        snapshot["overdue_count"] = int(overdue["c"])
        snapshot["overdue_total"] = currency.to_display(float(overdue["t"]), rate)
        snapshot["low_stock_count"] = int(low["c"])
    except Exception:
        pass
    return snapshot


def _fire(page, native_files, method: str, *args) -> None:
    """Dispatch a single fire-and-forget call onto the native_files Flet
    control. Swallows ``None`` (desktop/dev runs without the Android
    bridge) and never raises back into the caller -- the widget is a
    nice-to-have surface, not a critical path."""
    if native_files is None or getattr(native_files, method, None) is None:
        return
    page.run_task(getattr(native_files, method), *args)


def refresh_home_widget(page, native_files, dashboard, settings=None) -> None:
    """Immediate, app-open refresh -- a sale or voucher just posted, and
    DashboardService has fresh numbers in memory. Fire-and-forget so a
    slow/failed push never blocks the save flow that triggered it."""
    snapshot = home_widget_snapshot(dashboard, settings)
    _fire(page, native_files, "push_home_widget", snapshot)


def clear_home_widget(page, native_files) -> None:
    """Wipe the widget's stored snapshot. Called after a backup restore
    so stale pre-restore numbers cannot be shown against the restored
    database for the next periodic tick. No-op if the bridge is absent."""
    _fire(page, native_files, "clear_home_widget")


def force_refresh_home_widget(page, native_files) -> None:
    """Ask the platform side to re-render every placed widget instance now
    (without waiting for the next APPWIDGET_UPDATE tick) and without
    changing the underlying snapshot."""
    _fire(page, native_files, "force_refresh_home_widget")


def refresh_home_widget_after_restore(page, native_files, dashboard, settings=None) -> None:
    """The single entry point admin_view.confirm() calls immediately after
    backup_service.restore_backup() succeeds and ctx.reload() repopulates
    the in-memory services.

    Order matters:
      1. clear_home_widget -- empty the stored snapshot so any
         pre-restore overdue_count / low_stock_count written by the
         last periodic pass do not survive.
      2. force_refresh_home_widget -- collapse the cached frame the
         launcher is still showing (a plain LinearLayout update won't
         always force this).
      3. push_home_widget -- write the new snapshot and re-render.
         Re-rendering is idempotent -- even if step (2) already rendered
         an empty card, this one stamps the real numbers on it.
    """
    if native_files is None:
        return
    clear_home_widget(page, native_files)
    force_refresh_home_widget(page, native_files)
    snapshot = home_widget_snapshot(dashboard, settings)
    _fire(page, native_files, "push_home_widget", snapshot)
