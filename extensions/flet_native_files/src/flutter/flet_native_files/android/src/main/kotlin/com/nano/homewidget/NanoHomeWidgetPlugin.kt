package com.nano.homewidget

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * FIX_0.9.1: same channel contract as PHASE10 ("nano/home_widget" with
 * "push" and "diagnose", identical JSON), but the widget state now lives in
 * a single SharedPreferences key and rendering is done by
 * NanoWidgetReceiver (plain AppWidgetProvider) instead of Glance -- see
 * NanoWidgetReceiver.kt for why. Nothing on the Python or Dart side of the
 * bridge needed to change.
 *
 * Both PHASE10 update paths still funnel through "push":
 *   1. Immediate -- native_files.py's push_home_widget() after a sale or
 *      voucher save while the app is open.
 *   2. Periodic fallback -- native_files.dart's _pushHomeWidgetSnapshot
 *      from the same WorkManager isolate PHASE9 already uses.
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
                NanoWidgetReceiver.saveMerged(context, incoming)
                NanoWidgetReceiver.updateAll(context)
                NanoWidgetDiagnostics.lastPushOk = true
                NanoWidgetDiagnostics.lastPushError = null
                withContext(Dispatchers.Main) { result.success(null) }
            } catch (error: Exception) {
                // Never surface a widget failure back into the Python
                // sale/receipt flow that triggered the push (matches the
                // push_home_widget() swallow-everything contract). It is
                // still recorded for "diagnose" instead of vanishing.
                NanoWidgetDiagnostics.lastPushOk = false
                NanoWidgetDiagnostics.lastPushError = error.toString()
                withContext(Dispatchers.Main) { result.success(null) }
            } finally {
                NanoWidgetDiagnostics.lastPushAt = System.currentTimeMillis()
            }
        }
    }

    /** Backs the admin widget diagnostics panel (admin_view.py), mirroring
     *  diagnose_sound's contract: a plain JSON object, no swallowing on
     *  this side -- callers that cannot reach the channel at all already
     *  report that as their own diagnosis line on the Dart/Python side. */
    private fun handleDiagnose(result: MethodChannel.Result) {
        CoroutineScope(Dispatchers.IO).launch {
            val widgetCount = try {
                AppWidgetManager.getInstance(context).getAppWidgetIds(
                    ComponentName(context, NanoWidgetReceiver::class.java)
                ).size
            } catch (_: Exception) {
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
