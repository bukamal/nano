package com.nano.homewidget

import android.app.Activity
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.view.View
import android.widget.RemoteViews
import org.json.JSONObject

/**
 * FIX_0.9.1: the PHASE10 home-screen widget, rebuilt on the plain Android
 * framework instead of Jetpack Glance.
 *
 * Why the swap (full trail in FIX_0.9.1_HOME_WIDGET_APPPROVIDER_AR.md):
 * fixes 0.8.2 -> 0.8.5 hardened every line of the Glance implementation --
 * exported receiver, preview image, try/catch around getAppWidgetState(),
 * around the tap-to-open reflection and around the whole render -- yet the
 * widget still showed Android's "يتعذّر عرض المحتوى" placeholder. The
 * in-app diagnostics added in 0.8.4 proved the decisive fact: widget_count=1
 * and pushes kept merging into stored state, but provideGlance() was NEVER
 * invoked a single time. A failure that deep sits inside Glance's own
 * session machinery (GlanceAppWidgetReceiver -> AppWidgetSession ->
 * RemoteViewsService, a library layer no project try/catch can reach) and
 * cannot be fixed from the app's side of that library.
 *
 * An AppWidgetProvider + RemoteViews implementation has none of that
 * machinery: rendering happens in onUpdate() with framework APIs only
 * (android.appwidget / android.widget), synchronously and deterministically
 * -- if onUpdate runs, the widget renders. The bridge contract is
 * unchanged: channel "nano/home_widget", methods "push"/"diagnose", and the
 * same JSON keys (sales_today / cash_balance / overdue_count /
 * low_stock_count), so core/home_widget.py, native_files.py and
 * native_files.dart do not move at all.
 */

/** In-memory breadcrumbs for the plugin's "diagnose" method, kept on the
 *  same JSON keys as 0.8.5 so any existing admin-panel consumer keeps
 *  working unchanged. */
object NanoWidgetDiagnostics {
    @Volatile var lastProvideGlanceAt: Long = 0L
    @Volatile var lastStateReadError: String? = null
    @Volatile var lastRenderError: String? = null
    @Volatile var lastSnapshotJson: String? = null
    @Volatile var lastPushAt: Long = 0L
    @Volatile var lastPushOk: Boolean? = null
    @Volatile var lastPushError: String? = null
}

class NanoWidgetReceiver : AppWidgetProvider() {

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        refresh(context.applicationContext, appWidgetManager, appWidgetIds)
    }

    companion object {
        const val PREFS_NAME = "nano_widget_state"
        const val KEY_SNAPSHOT = "snapshot_json"

        fun loadSnapshot(context: Context): JSONObject {
            val raw = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getString(KEY_SNAPSHOT, null) ?: return JSONObject()
            return try {
                JSONObject(raw)
            } catch (_: Exception) {
                JSONObject()
            }
        }

        /** Merges an incoming push into the stored snapshot -- the same
         *  per-key merge semantics the Glance plugin used, never a full
         *  overwrite, so an instant sales/cash push cannot blank the
         *  overdue/low-stock fields the periodic pass stored. */
        fun saveMerged(context: Context, incomingJson: String) {
            val merged = loadSnapshot(context)
            val incoming = try {
                JSONObject(incomingJson)
            } catch (_: Exception) {
                JSONObject()
            }
            incoming.keys().forEach { key -> merged.put(key, incoming.get(key)) }
            val stored = merged.toString()
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit().putString(KEY_SNAPSHOT, stored).apply()
            NanoWidgetDiagnostics.lastSnapshotJson = stored
        }

        /** Renders every given widget id from the current shared state and
         *  records the outcome for "diagnose". A failing single id never
         *  takes the rest down: each update is caught individually. */
        fun refresh(context: Context, manager: AppWidgetManager, ids: IntArray) {
            if (ids.isEmpty()) return
            val data = loadSnapshot(context)
            var error: String? = null
            for (id in ids) {
                try {
                    manager.updateAppWidget(id, buildViews(context, data))
                } catch (caught: Exception) {
                    error = caught.toString()
                }
            }
            NanoWidgetDiagnostics.lastStateReadError = null
            NanoWidgetDiagnostics.lastRenderError = error
            NanoWidgetDiagnostics.lastProvideGlanceAt = System.currentTimeMillis()
        }

        /** Re-renders every placed instance from the current shared state
         *  (invoked by NanoHomeWidgetPlugin right after a push). */
        fun updateAll(context: Context) {
            val ctx = context.applicationContext
            val manager = AppWidgetManager.getInstance(ctx)
            val ids = manager.getAppWidgetIds(ComponentName(ctx, NanoWidgetReceiver::class.java))
            refresh(ctx, manager, ids)
        }

        fun buildViews(context: Context, data: JSONObject): RemoteViews {
            val views = RemoteViews(context.packageName, R.layout.nano_widget)
            views.setTextViewText(R.id.nano_widget_sales_value, formatMoney(data.optDouble("sales_today", 0.0)))
            views.setTextViewText(R.id.nano_widget_cash_value, formatMoney(data.optDouble("cash_balance", 0.0)))

            val alert = alertLine(data.optInt("overdue_count", 0), data.optInt("low_stock_count", 0))
            if (alert.isNotEmpty()) {
                views.setTextViewText(R.id.nano_widget_alert, alert)
                views.setViewVisibility(R.id.nano_widget_alert, View.VISIBLE)
            } else {
                views.setViewVisibility(R.id.nano_widget_alert, View.GONE)
            }

            // First placement before any push/periodic pass: show a legible
            // hint instead of a blank panel -- never the system's
            // "يتعذّر عرض المحتوى" placeholder.
            val hasData = data.has("sales_today") || data.has("cash_balance")
            views.setViewVisibility(R.id.nano_widget_hint, if (hasData) View.GONE else View.VISIBLE)

            // Tap-to-open the app (reflection on the generated launcher
            // Activity, guarded): if it ever fails the widget still renders,
            // just without the shortcut -- degrading beats vanishing.
            try {
                val launchIntent = Intent(context, mainActivityClass(context)).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                }
                val flags = if (android.os.Build.VERSION.SDK_INT >= 23) {
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                } else {
                    PendingIntent.FLAG_UPDATE_CURRENT
                }
                val pendingIntent = PendingIntent.getActivity(context, 0, launchIntent, flags)
                views.setOnClickPendingIntent(R.id.nano_widget_root, pendingIntent)
            } catch (_: Exception) {
                // degrade silently
            }
            return views
        }
    }
}

/**
 * Flet's generated MainActivity always lives at <applicationId>.MainActivity
 * (com.nano here, per [tool.flet] org/product in pyproject.toml) -- resolved
 * by name so this plugin module never needs a compile-time dependency on
 * the generated app module.
 */
@Suppress("UNCHECKED_CAST")
internal fun mainActivityClass(context: Context): Class<out Activity> =
    Class.forName("${context.packageName}.MainActivity") as Class<out Activity>

private fun formatMoney(v: Double): String {
    val n = v.toLong()
    val sign = if (n < 0) "-" else ""
    val grouped = kotlin.math.abs(n).toString().reversed().chunked(3).joinToString(",")
    return sign + grouped.reversed()
}

private fun alertLine(overdue: Int, lowStock: Int): String = when {
    overdue > 0 && lowStock > 0 -> "$overdue ذمم متأخرة · $lowStock صنف منخفض"
    overdue > 0 -> "$overdue فواتير آجلة متأخرة"
    lowStock > 0 -> "$lowStock صنف وصل الحد الأدنى"
    else -> ""
}
