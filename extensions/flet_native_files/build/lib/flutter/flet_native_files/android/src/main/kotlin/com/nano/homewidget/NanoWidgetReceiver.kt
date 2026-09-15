package com.nano.homewidget

import android.app.Activity
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.view.View
import android.widget.RemoteViews
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * FIX_0.9.3: redesigned into an integrated, smart, modern widget that mirrors
 * the in-app snapshot exactly.
 *
 * Data contract (JSON pushed over "nano/home_widget" => "push"):
 *   sales_today        -> Double  (already converted to the display currency)
 *   sales_count_today  -> Int     (today's sale invoice count)
 *   cash_balance       -> Double  (already converted to the display currency)
 *   overdue_count      -> Int
 *   overdue_total      -> Double  (display currency)
 *   low_stock_count    -> Int
 *   currency_symbol    -> String  (e.g. "ل.س" or "$")
 *   store_name         -> String  (the store/brand name from settings)
 *   updated_at         -> String  (ISO 8601 UTC)
 *
 * Amounts arrive pre-converted (Python home_widget.py and the Dart periodic
 * pass both apply the user's display-currency and exchange-rate settings), so
 * the widget can never drift from what the app shows -- this was the root
 * cause of the "بيانات الودجت سيئة": raw USD floats without a symbol or
 * conversion were pushed while the app displays SYP.
 *
 * The status pill is always visible once a snapshot exists: mint "كل شيء على
 * ما يرام" when there is nothing to flag, amber/red tinted alert lines
 * otherwise -- the widget reads as alive instead of a blank panel.
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

        /** FIX_0.9.2: wipe the persisted snapshot entirely after a restore. */
        fun clearSnapshot(context: Context) {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit().remove(KEY_SNAPSHOT).apply()
            NanoWidgetDiagnostics.lastSnapshotJson = null
            NanoWidgetDiagnostics.lastClearAt = System.currentTimeMillis()
        }

        /** FIX_0.9.2: force re-render without waiting for the next tick. */
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
            val symbol = data.optString("currency_symbol", "ل.س")

            // Header: store name from the project settings, else the default brand.
            val storeName = data.optString("store_name", "").trim()
            views.setTextViewText(
                R.id.nano_widget_title,
                if (storeName.isNotEmpty()) storeName else context.getString(R.string.nano_widget_default_title)
            )

            // KPI values -- already in the display currency, formatted + symbol.
            views.setTextViewText(
                R.id.nano_widget_sales_value,
                formatMoney(data.optDouble("sales_today", 0.0), symbol)
            )
            views.setTextViewText(
                R.id.nano_widget_cash_value,
                formatMoney(data.optDouble("cash_balance", 0.0), symbol)
            )

            // Sales sub-label: today's invoice count.
            if (data.has("sales_count_today")) {
                val count = data.optInt("sales_count_today", 0)
                views.setTextViewText(
                    R.id.nano_widget_sales_sub,
                    if (count > 0) context.getString(R.string.nano_widget_sales_sub_count, count)
                    else context.getString(R.string.nano_widget_sales_sub_none)
                )
                views.setViewVisibility(R.id.nano_widget_sales_sub, View.VISIBLE)
            } else {
                views.setViewVisibility(R.id.nano_widget_sales_sub, View.GONE)
            }

            // Cash sub-label: positive/negative state hint.
            if (data.has("cash_balance")) {
                views.setTextViewText(
                    R.id.nano_widget_cash_sub,
                    if (data.optDouble("cash_balance", 0.0) < 0)
                        context.getString(R.string.nano_widget_cash_sub_negative)
                    else context.getString(R.string.nano_widget_cash_sub_positive)
                )
                views.setViewVisibility(R.id.nano_widget_cash_sub, View.VISIBLE)
            } else {
                views.setViewVisibility(R.id.nano_widget_cash_sub, View.GONE)
            }

            // Smart status pill -- visible once any snapshot key exists.
            val overdue = data.optInt("overdue_count", 0)
            val lowStock = data.optInt("low_stock_count", 0)
            val hasFlags = data.has("overdue_count") || data.has("low_stock_count")
            if (hasFlags) {
                val overdueTotal = data.optDouble("overdue_total", 0.0)
                val (text, tint) = when {
                    overdue > 0 && lowStock > 0 ->
                        context.getString(R.string.nano_widget_status_both, overdue, lowStock) to "#FCA5A5"
                    overdue > 0 ->
                        context.getString(R.string.nano_widget_status_overdue, overdue, formatMoney(overdueTotal, symbol)) to "#FCA5A5"
                    lowStock > 0 ->
                        context.getString(R.string.nano_widget_status_lowstock, lowStock) to "#FCD34D"
                    else ->
                        context.getString(R.string.nano_widget_status_ok) to "#5EEAD4"
                }
                views.setTextViewText(R.id.nano_widget_status, text)
                views.setTextColor(R.id.nano_widget_status, Color.parseColor(tint))
                views.setViewVisibility(R.id.nano_widget_status, View.VISIBLE)
            } else {
                views.setViewVisibility(R.id.nano_widget_status, View.GONE)
            }

            // Freshness footer -- driven by updated_at (ISO 8601, UTC).
            val footer = timeAgo(data.optString("updated_at", ""))
            if (footer.isNotEmpty()) {
                views.setTextViewText(R.id.nano_widget_footer, footer)
                views.setViewVisibility(R.id.nano_widget_footer, View.VISIBLE)
            } else {
                views.setViewVisibility(R.id.nano_widget_footer, View.GONE)
            }

            // First placement before any data -- legible hint, never a blank panel.
            val hasData = data.has("sales_today") || data.has("cash_balance")
            views.setViewVisibility(R.id.nano_widget_hint, if (hasData) View.GONE else View.VISIBLE)

            // Tap-to-open the app, reflection-guarded.
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

/** Integer amount with thousands grouping + the display-currency symbol. */
private fun formatMoney(v: Double, symbol: String): String {
    val n = v.toLong()
    val sign = if (n < 0) "-" else ""
    val grouped = kotlin.math.abs(n).toString().reversed().chunked(3).joinToString(",")
    return sign + grouped.reversed() + " " + symbol
}

// FIX_0.9.2: minimal-allocation ISO 8601 parser that doesn't need java.time.
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
