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
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * FIX_0.9.2: rebuilt on the plain Android framework (was Jetpack Glance, dropped
 * in 0.9.1 because provideGlance() never fired) -- and now also blends into
 * Nano's theme tokens (theme.py: #0F766E / #115E59 / #5EEAD4 / #C7E5E0 /
 * #FFD9C2 / #FFFFFF) so the widget reads as part of the app rather than a
 * generic card from another vendor.
 *
 * Contract vs 0.8.x: same channel "nano/home_widget", same methods
 * "push"/"diagnose"/"clear"/"refresh_now", same JSON keys (sales_today,
 * cash_balance, overdue_count, low_stock_count, updated_at). Adding "clear"
 * and "refresh_now" is purely additive -- 0.9.x callers that don't use them
 * still work.
 */
object NanoWidgetDiagnostics {
    @Volatile var lastProvideGlanceAt: Long = 0L
    @Volatile var lastStateReadError: String? = null
    @Volatile var lastRenderError: String? = null
    @Volatile var lastSnapshotJson: String? = null
    @Volatile var lastPushAt: Long = 0L
    @Volatile var lastPushOk: Boolean? = null
    @Volatile var lastPushError: String? = null
    @Volatile var lastClearAt: Long = 0L
    @Volatile var lastRefreshNowAt: Long = 0L
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

        /**
         * FIX_0.9.2: wipe the persisted snapshot entirely so a stale pre-restore
         * snapshot (or a snapshot from a previous install) cannot survive a
         * backup restore and keep showing numbers that don't belong in the
         * freshly restored database. After clear(), the next push overwrites
         * from scratch.
         */
        fun clearSnapshot(context: Context) {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit().remove(KEY_SNAPSHOT).apply()
            NanoWidgetDiagnostics.lastSnapshotJson = null
            NanoWidgetDiagnostics.lastClearAt = System.currentTimeMillis()
        }

        /**
         * FIX_0.9.2: belt-and-braces refresh entry point called by the plugin
         * immediately after a clear()/push(). updateAppWidget() always rebuilds
         * the RemoteViews tree even when the underlying snapshot is identical
         * to what was just rendered, which is exactly what's needed to force
         * the launcher to drop the cached frame after a restore.
         */
        fun refreshAllNow(context: Context) {
            val ctx = context.applicationContext
            val manager = AppWidgetManager.getInstance(ctx)
            val ids = manager.getAppWidgetIds(ComponentName(ctx, NanoWidgetReceiver::class.java))
            refresh(ctx, manager, ids)
            NanoWidgetDiagnostics.lastRefreshNowAt = System.currentTimeMillis()
        }

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

        fun updateAll(context: Context) {
            val ctx = context.applicationContext
            val manager = AppWidgetManager.getInstance(ctx)
            val ids = manager.getAppWidgetIds(ComponentName(ctx, NanoWidgetReceiver::class.java))
            refresh(ctx, manager, ids)
        }

        fun buildViews(context: Context, data: JSONObject): RemoteViews {
            val views = RemoteViews(context.packageName, R.layout.nano_widget)

            // KPIs -- values formatted with thousands grouping, large bold white.
            views.setTextViewText(
                R.id.nano_widget_sales_value,
                formatMoney(data.optDouble("sales_today", 0.0)),
            )
            views.setTextViewText(
                R.id.nano_widget_cash_value,
                formatMoney(data.optDouble("cash_balance", 0.0)),
            )

            // Alert pill -- collapsed when there's nothing to flag.
            val alert = alertLine(
                data.optInt("overdue_count", 0),
                data.optInt("low_stock_count", 0),
            )
            if (alert.isNotEmpty()) {
                views.setTextViewText(R.id.nano_widget_alert, alert)
                views.setViewVisibility(R.id.nano_widget_alert, View.VISIBLE)
            } else {
                views.setViewVisibility(R.id.nano_widget_alert, View.GONE)
            }

            // Freshness footer -- "تم التحديث قبل X" / "قبل لحظة".
            // Driven by updated_at (ISO 8601, UTC) pushed by both Dart paths.
            val footer = timeAgo(data.optString("updated_at", ""))
            if (footer.isNotEmpty()) {
                views.setTextViewText(R.id.nano_widget_footer, footer)
                views.setViewVisibility(R.id.nano_widget_footer, View.VISIBLE)
            } else {
                views.setViewVisibility(R.id.nano_widget_footer, View.GONE)
            }

            // First placement before any data -- show a legible hint instead of
            // a blank panel, never Android's "Couldn't load widget" placeholder.
            val hasData = data.has("sales_today") || data.has("cash_balance")
            views.setViewVisibility(R.id.nano_widget_hint, if (hasData) View.GONE else View.VISIBLE)

            // Tap-to-open the app, reflection-guarded -- degrading beats vanishing.
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

// FIX_0.9.2: minimal-allocation ISO 8601 parser that doesn't need java.time
// (avoids the API 26 requirement and a desugaring dependency).
private val FOOTER_FORMATS = arrayOf(
    "yyyy-MM-dd'T'HH:mm:ssXXX",
    "yyyy-MM-dd'T'HH:mm:ssZ",
    "yyyy-MM-dd'T'HH:mm:ss",
)

private fun parsePushedAt(iso: String): Long? {
    if (iso.isBlank()) return null
    for (pattern in FOOTER_FORMATS) {
        try {
            val sdf = SimpleDateFormat(pattern, Locale.US)
            sdf.timeZone = TimeZone.getTimeZone("UTC")
            return sdf.parse(iso)?.time
        } catch (_: Exception) { continue }
    }
    return null
}

private fun timeAgo(iso: String): String {
    val pushed = parsePushedAt(iso) ?: return ""
    val ageMs = System.currentTimeMillis() - pushed
    if (ageMs < 0) return ""
    val minutes = ageMs / 60_000L
    return when {
        minutes < 1L -> "تم التحديث قبل لحظة"
        minutes < 2L -> "تم التحديث قبل دقيقة"
        minutes < 60L -> "تم التحديث قبل $minutes دقيقة"
        ageMs < 24L * 3_600_000L -> "تم التحديث قبل ${ageMs / 3_600_000L} ساعة"
        else -> {
            val sdf = SimpleDateFormat("HH:mm", Locale("ar"))
            sdf.timeZone = TimeZone.getDefault()
            "تم التحديث ${sdf.format(java.util.Date(pushed))}"
        }
    }
}
