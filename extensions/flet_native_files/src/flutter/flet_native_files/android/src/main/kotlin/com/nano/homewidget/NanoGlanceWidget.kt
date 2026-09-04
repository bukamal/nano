package com.nano.homewidget

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.provideContent
import androidx.glance.currentState
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import org.json.JSONObject

/**
 * PHASE10 home screen widget. See PHASE10_HOME_WIDGET_GLANCE_AR.md for the
 * full architecture: this class only ever *reads* the snapshot that
 * NanoHomeWidgetPlugin already merged into Glance's own preferences
 * DataStore -- it never touches the app database or the network itself.
 */
val KEY_SNAPSHOT: Preferences.Key<String> = stringPreferencesKey("nano_widget_snapshot")

private val WarningColor = ColorProvider(day = androidx.compose.ui.graphics.Color(0xFF993C1D), night = androidx.compose.ui.graphics.Color(0xFFF0997B))
private val MutedColor = ColorProvider(day = androidx.compose.ui.graphics.Color(0xFF5F5E5A), night = androidx.compose.ui.graphics.Color(0xFFB4B2A9))

class NanoGlanceWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        provideContent {
            val prefs = currentState<Preferences>()
            val data = try {
                JSONObject(prefs[KEY_SNAPSHOT] ?: "{}")
            } catch (_: Exception) {
                JSONObject()
            }
            val salesToday = data.optDouble("sales_today", 0.0)
            val cashBalance = data.optDouble("cash_balance", 0.0)
            val overdueCount = data.optInt("overdue_count", 0)
            val lowStockCount = data.optInt("low_stock_count", 0)

            Column(
                modifier = GlanceModifier
                    .fillMaxSize()
                    .padding(12.dp)
                    .clickable(actionStartActivity(componentClass = mainActivityClass(context)))
            ) {
                Text("Nano | نانو", style = TextStyle(fontWeight = FontWeight.Medium))
                Spacer(modifier = GlanceModifier.height(8.dp))
                Row(modifier = GlanceModifier.fillMaxWidth()) {
                    Column(modifier = GlanceModifier.defaultWeight()) {
                        Text("مبيعات اليوم", style = TextStyle(color = MutedColor))
                        Text(formatMoney(salesToday), style = TextStyle(fontWeight = FontWeight.Medium))
                    }
                    Column(modifier = GlanceModifier.defaultWeight()) {
                        Text("رصيد الصندوق", style = TextStyle(color = MutedColor))
                        Text(formatMoney(cashBalance), style = TextStyle(fontWeight = FontWeight.Medium))
                    }
                }
                if (overdueCount > 0 || lowStockCount > 0) {
                    Spacer(modifier = GlanceModifier.height(6.dp))
                    Text(alertLine(overdueCount, lowStockCount), style = TextStyle(color = WarningColor))
                }
            }
        }
    }
}

/**
 * Flet's generated MainActivity always lives at <applicationId>.MainActivity
 * (com.nano here, per [tool.flet] org/product in pyproject.toml) -- resolved
 * by name instead of a compile-time import so this plugin module doesn't
 * need to depend on the generated app module.
 */
internal fun mainActivityClass(context: Context): Class<*> =
    Class.forName("${context.packageName}.MainActivity")

private fun formatMoney(v: Double): String =
    v.toLong().toString().reversed().chunked(3).joinToString(",").reversed()

private fun alertLine(overdue: Int, lowStock: Int): String = when {
    overdue > 0 && lowStock > 0 -> "$overdue ذمم متأخرة \u00b7 $lowStock صنف منخفض"
    overdue > 0 -> "$overdue فواتير آجلة متأخرة"
    else -> "$lowStock صنف وصل الحد الأدنى"
}
