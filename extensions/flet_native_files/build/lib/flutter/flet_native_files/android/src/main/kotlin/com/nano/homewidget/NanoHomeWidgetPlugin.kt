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
        if (call.method != "push") {
            result.notImplemented()
            return
        }
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
                withContext(Dispatchers.Main) { result.success(null) }
            } catch (error: Exception) {
                // A widget that isn't currently placed on any home screen
                // (ids empty) is not an error -- but a genuine failure here
                // must never surface back into the Python/sale flow that
                // triggered it, matching push_home_widget()'s own
                // swallow-everything contract on the Python side.
                withContext(Dispatchers.Main) { result.success(null) }
            }
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {}
}
