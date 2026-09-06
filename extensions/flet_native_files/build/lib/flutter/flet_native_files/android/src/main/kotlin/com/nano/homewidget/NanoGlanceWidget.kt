package com.nano.homewidget

import android.app.Activity
import android.content.Context
import androidx.compose.ui.unit.dp
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.glance.color.ColorProvider
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.state.getAppWidgetState
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
import androidx.glance.state.PreferencesGlanceStateDefinition
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

/**
 * In-memory diagnostic breadcrumbs, read back by NanoHomeWidgetPlugin's
 * "diagnose" method (see admin_view.py's widget diagnostics panel).
 *
 * This exists because 0.8.3's two try/catch layers inside provideContent
 * made *render* failures recoverable and visible on the widget itself
 * ("تعذّر تحميل الأرقام"), but a failure in getAppWidgetState() -- which
 * runs *before* provideContent, reading the DataStore off disk -- still
 * took provideGlance down with no trace anywhere, reproducing the exact
 * same opaque "يتعذّر عرض المحتوى" placeholder 0.8.3 was meant to end.
 * Every field here is written from provideGlance/onMethodCall only and
 * merely read by the admin panel -- never anything the widget itself
 * depends on to render.
 */
object NanoWidgetDiagnostics {
    @Volatile var lastProvideGlanceAt: Long = 0L
    @Volatile var lastStateReadError: String? = null
    @Volatile var lastRenderError: String? = null
    @Volatile var lastSnapshotJson: String? = null
    @Volatile var lastPushAt: Long = 0L
    @Volatile var lastPushOk: Boolean? = null
    @Volatile var lastPushError: String? = null
}

class NanoGlanceWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        // NOTE: deliberately NOT using the `currentState<Preferences>()`
        // composable here. That helper is `inline fun <reified T>`, and the
        // Kotlin 1.9.22 JVM (K1) backend has a known bug inlining reified
        // Compose/Glance functions pulled from a precompiled AAR: the
        // release build crashes with "Internal compiler error: Couldn't
        // inline method call ... couldn't find inline method
        // Landroidx/glance/CompositionLocalsKt;.currentState()" in
        // :flet_native_files:compileReleaseKotlin. getAppWidgetState() is a
        // plain (non-inline) suspend function that reads the exact same
        // PreferencesGlanceStateDefinition state, so this is behaviourally
        // identical and avoids the inliner entirely.
        //
        // This call itself was, until now, the one unprotected step in the
        // whole provideGlance path: it reads the Preferences DataStore off
        // disk, and any failure there (corrupt file, I/O error, first read
        // racing a concurrent write) threw straight out of provideGlance
        // before provideContent's two try/catch layers ever ran -- an
        // uncaught exception here reproduces the identical "يتعذّر عرض
        // المحتوى" placeholder the 0.8.3 fix targeted, just one call
        // earlier than where that fix looked.
        val snapshotJson: String? = try {
            val prefs = getAppWidgetState(context, PreferencesGlanceStateDefinition, id)
            NanoWidgetDiagnostics.lastStateReadError = null
            prefs[KEY_SNAPSHOT]
        } catch (error: Exception) {
            NanoWidgetDiagnostics.lastStateReadError = error.toString()
            null
        }
        NanoWidgetDiagnostics.lastSnapshotJson = snapshotJson
        provideContent {
            try {
                val data = try {
                    JSONObject(snapshotJson ?: "{}")
                } catch (_: Exception) {
                    JSONObject()
                }
                val salesToday = data.optDouble("sales_today", 0.0)
                val cashBalance = data.optDouble("cash_balance", 0.0)
                val overdueCount = data.optInt("overdue_count", 0)
                val lowStockCount = data.optInt("low_stock_count", 0)

                // mainActivityClass() resolves the generated app's launcher
                // Activity by name via reflection (see its own doc comment
                // below for why). That reflection call runs on *every*
                // provideGlance recomposition -- not lazily on tap -- so if
                // it ever throws (ClassNotFoundException from a renamed/
                // missing class, a SecurityException from a restricted
                // ClassLoader, etc.) it previously took the whole
                // `provideContent` block down with it. An uncaught
                // exception here is exactly what makes Android fall back to
                // its generic "يتعذّر عرض المحتوى" / "Couldn't load widget"
                // placeholder -- indistinguishable from a real crash, and
                // it would repeat identically on every recomposition
                // (periodic tick, app-open push, or a fresh delete +
                // re-add), which matches a failure that persists across
                // re-adding the widget rather than a one-off stale bind.
                // Losing the tap-to-open shortcut is a far better outcome
                // than losing the entire widget, so this degrades instead
                // of propagating.
                val baseModifier = GlanceModifier.fillMaxSize().padding(12.dp)
                val modifier = try {
                    baseModifier.clickable(actionStartActivity(activity = mainActivityClass(context)))
                } catch (_: Exception) {
                    baseModifier
                }

                Column(modifier = modifier) {
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
                NanoWidgetDiagnostics.lastRenderError = null
            } catch (error: Exception) {
                // Absolute last resort. Anything unexpected here must still
                // leave legible content on the home screen instead of
                // Android's placeholder -- a widget that only ever shows
                // "تعذّر تحميل الأرقام" is diagnosable and recoverable (open
                // the app, wait for the next periodic tick); one that shows
                // the system's opaque error is neither.
                NanoWidgetDiagnostics.lastRenderError = error.toString()
                Column(modifier = GlanceModifier.fillMaxSize().padding(12.dp)) {
                    Text("Nano | نانو", style = TextStyle(fontWeight = FontWeight.Medium))
                    Spacer(modifier = GlanceModifier.height(8.dp))
                    Text("تعذّر تحميل الأرقام، افتح التطبيق للتحديث", style = TextStyle(color = MutedColor))
                }
            } finally {
                NanoWidgetDiagnostics.lastProvideGlanceAt = System.currentTimeMillis()
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
@Suppress("UNCHECKED_CAST")
internal fun mainActivityClass(context: Context): Class<out Activity> =
    Class.forName("${context.packageName}.MainActivity") as Class<out Activity>

private fun formatMoney(v: Double): String {
    val n = v.toLong()
    val sign = if (n < 0) "-" else ""
    val grouped = kotlin.math.abs(n).toString().reversed().chunked(3).joinToString(",").reversed()
    return sign + grouped
}

private fun alertLine(overdue: Int, lowStock: Int): String = when {
    overdue > 0 && lowStock > 0 -> "$overdue ذمم متأخرة \u00b7 $lowStock صنف منخفض"
    overdue > 0 -> "$overdue فواتير آجلة متأخرة"
    else -> "$lowStock صنف وصل الحد الأدنى"
}
