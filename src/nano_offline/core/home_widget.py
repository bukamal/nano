from __future__ import annotations

"""FIX_0.9.2: home screen widget bridge -- app-open refresh path
plus post-restore synchronization helpers.

Only ``sales_today`` and ``cash_balance`` are pushed from the immediate
Python path. ``overdue_count`` / ``low_stock_count`` are owned by the
periodic WorkManager pass in extensions/flet_native_files/.../native_files.dart
(_pushHomeWidgetSnapshot), which already implements the exact "overdue after
N days" / "low stock threshold" rules from the user's notification config
(see notification_service.py) -- duplicating that logic here would risk the
two sides disagreeing about what counts as overdue.

After a backup restore, ``refresh_home_widget`` (formerly enough) is not
enough on its own: the widget's SharedPreferences (``nano_widget_state`` in
the [NanoWidgetReceiver] Kotlin module) still holds a snapshot from the
pre-restore days. ``clear_home_widget`` wipes that snapshot, and
``force_refresh_home_widget`` re-renders every placed instance immediately
without waiting for the next periodic tick. ``refresh_home_widget_after_restore``
chains those two with a fresh push so the user-visible numbers come from
the just-restored database -- which is the only thing that addresses the
FIX_0.9.2 bug report ("الودجت فارغ رغم نجاح الاسترجاع")."""


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


def _fire(page, native_files, method: str, *args) -> None:
    """Dispatch a single fire-and-forget call onto the native_files Flet
    control. Swallows ``None`` (desktop/dev runs without the Android
    bridge) and never raises back into the caller -- the widget is a
    nice-to-have surface, not a critical path."""
    if native_files is None or getattr(native_files, method, None) is None:
        return
    page.run_task(getattr(native_files, method), *args)


def refresh_home_widget(page, native_files, dashboard) -> None:
    """Immediate, app-open refresh -- a sale or voucher just posted, and
    DashboardService has fresh numbers in memory. Fire-and-forget so a
    slow/failed push never blocks the save flow that triggered it."""
    snapshot = home_widget_snapshot(dashboard)
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


def refresh_home_widget_after_restore(page, native_files, dashboard) -> None:
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
    snapshot = home_widget_snapshot(dashboard)
    _fire(page, native_files, "push_home_widget", snapshot)
