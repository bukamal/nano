package com.nano.homewidget

import android.content.Context
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.state.updateAppWidgetState
import androidx.glance.appwidget.updateAll
import androidx.glance.state.PreferencesGlanceStateDefinition
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Single native sink for both PHASE10 update paths described in
 * PHASE10_HOME_WIDGET_GLANCE_AR.md:
 *   1. Immediate -- native_files.py's push_home_widget(), called from a
 *      view right after a sale/voucher save while the app is open.
 *   2. Periodic fallback -- native_files.dart's _pushHomeWidgetSnapshot,
 *      called from the same WorkManager isolate PHASE9 already uses for
 *      closed-app alerts.
 *
 * Both funnel through channel "nano/home_widget", method "push". Each push
 * is *merged* into the existing stored snapshot rather than replacing it --
 * the instant app-open path only ever sends sales_today/cash_balance (see
 * core/home_widget.py), so a full overwrite would blank out
 * overdue_count/low_stock_count until the next periodic pass.
 */
class NanoHomeWidgetPlugin : FlutterPlugin, MethodChannel.MethodCallHandler {
    private lateinit var channel: MethodChannel
    private lateinit var context: Context

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        channel = MethodChannel(binding.binaryMessenger, "nano/home_widget")
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "push" -> handlePush(call, result)
            "diagnose" -> handleDiagnose(result)
            else -> result.notImplemented()
        }
    }

    private fun handlePush(call: MethodCall, result: MethodChannel.Result) {
        val incoming = call.arguments as? String ?: "{}"
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val manager = GlanceAppWidgetManager(context)
                val ids = manager.getGlanceIds(NanoGlanceWidget::class.java)
                ids.forEach { id ->
                    updateAppWidgetState(context, PreferencesGlanceStateDefinition, id) { prefs ->
                        val merged = try {
                            JSONObject(prefs[KEY_SNAPSHOT] ?: "{}")
                        } catch (_: Exception) {
                            JSONObject()
                        }
                        val incomingJson = try {
                            JSONObject(incoming)
                        } catch (_: Exception) {
                            JSONObject()
                        }
                        incomingJson.keys().forEach { key -> merged.put(key, incomingJson.get(key)) }
                        prefs.toMutablePreferences().apply { this[KEY_SNAPSHOT] = merged.toString() }
                    }
                }
                if (ids.isNotEmpty()) NanoGlanceWidget().updateAll(context)
                NanoWidgetDiagnostics.lastPushOk = true
                NanoWidgetDiagnostics.lastPushError = null
                withContext(Dispatchers.Main) { result.success(null) }
            } catch (error: Exception) {
                // A widget that isn't currently placed on any home screen
                // (ids empty) is not an error -- but a genuine failure here
                // must never surface back into the Python/sale flow that
                // triggered it, matching push_home_widget()'s own
                // swallow-everything contract on the Python side. It is
                // still recorded for "diagnose" to surface in the admin
                // panel instead of vanishing silently.
                NanoWidgetDiagnostics.lastPushOk = false
                NanoWidgetDiagnostics.lastPushError = error.toString()
                withContext(Dispatchers.Main) { result.success(null) }
            } finally {
                NanoWidgetDiagnostics.lastPushAt = System.currentTimeMillis()
            }
        }
    }

    /**
     * Backs the admin "تشخيص ودجت الشاشة الرئيسية" panel (views/admin_view.py),
     * mirroring diagnose_sound's contract: a plain JSON object, no
     * swallow-everything on this side -- callers that can't reach this at
     * all (older APK, no bridge) already get that reported as their own
     * diagnosis line on the Dart/Python side.
     */
    private fun handleDiagnose(result: MethodChannel.Result) {
        CoroutineScope(Dispatchers.IO).launch {
            val widgetCount = try {
                GlanceAppWidgetManager(context).getGlanceIds(NanoGlanceWidget::class.java).size
            } catch (error: Exception) {
                -1
            }
            val json = JSONObject().apply {
                put("widget_count", widgetCount)
                put("last_state_read_error", NanoWidgetDiagnostics.lastStateReadError)
                put("last_render_error", NanoWidgetDiagnostics.lastRenderError)
                put("last_provide_glance_at", NanoWidgetDiagnostics.lastProvideGlanceAt)
                put("last_snapshot_json", NanoWidgetDiagnostics.lastSnapshotJson)
                put("last_push_at", NanoWidgetDiagnostics.lastPushAt)
                put("last_push_ok", NanoWidgetDiagnostics.lastPushOk)
                put("last_push_error", NanoWidgetDiagnostics.lastPushError)
            }
            withContext(Dispatchers.Main) { result.success(json.toString()) }
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {}
}
