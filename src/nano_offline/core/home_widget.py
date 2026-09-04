from __future__ import annotations

"""PHASE10: home screen widget (Glance) -- app-open refresh path.

Only sales_today and cash_balance are pushed from here. overdue_count and
low_stock_count are intentionally left to the periodic WorkManager pass in
extensions/flet_native_files/.../native_files.dart (_pushHomeWidgetSnapshot),
which already implements the exact "overdue after N days" / "low stock
threshold" rules from the user's notification config (see
notification_service.py) -- duplicating that logic here would risk the two
sides disagreeing about what counts as overdue. NanoHomeWidgetPlugin.kt
merges each push into the widget's existing stored state rather than
overwriting it, so an instant sales/cash push never blanks out the alert
row the last periodic pass set.
"""


def home_widget_snapshot(dashboard) -> dict:
    """Build the small snapshot the widget needs from data DashboardService
    already computes elsewhere (today_summary for the POS quick-sale screen,
    summary for the main dashboard) -- no new SQL added for this."""
    today = dashboard.today_summary()
    overall = dashboard.summary()
    return {
        "sales_today": today["total"],
        "cash_balance": overall["cash"],
    }


def refresh_home_widget(page, native_files, dashboard) -> None:
    """Fire-and-forget widget refresh, safe to call from a sync event handler.

    No-op if native_files wasn't wired in (desktop/dev runs without the
    Android bridge). Uses page.run_task, the same fire-and-forget pattern
    already used for sound playback (core/sound.py) and notification
    permission requests (views/notifications_view.py) -- callers never await
    this and a slow/failed push never blocks the save flow that triggered it.
    """
    if native_files is None:
        return
    snapshot = home_widget_snapshot(dashboard)
    page.run_task(native_files.push_home_widget, snapshot)
