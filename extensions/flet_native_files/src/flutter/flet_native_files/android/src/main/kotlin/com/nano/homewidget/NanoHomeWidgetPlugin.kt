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
 * FIX_0.9.2: extends the PHASE10 / 0.9.1 bridge with two new methods
 * specifically to make backup-restore stop leaving a stale snapshot in the
 * widget SharedPreferences:
 *
 *   - "clear": wipe the widget's stored snapshot so a previous install's
 *     or pre-restore data can never be shown against the restored DB.
 *   - "refresh_now": force-update every placed widget instance right now,
 *     independently of the next periodic pass.
 *
 * "push" is unchanged. "diagnose" still returns the same JSON shape (just
 * with two extra fields, last_clear_at / last_refresh_now_at).
 *
 * No Python or Dart surface area moved; admin_view.py reaches these via
 * native_files.clear_home_widget / native_files.force_refresh_home_widget.
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
            "clear" -> handleClear(result)
            "refresh_now" -> handleRefreshNow(result)
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
                NanoWidgetDiagnostics.lastPushOk = false
                NanoWidgetDiagnostics.lastPushError = error.toString()
                withContext(Dispatchers.Main) { result.success(null) }
            } finally {
                NanoWidgetDiagnostics.lastPushAt = System.currentTimeMillis()
            }
        }
    }

    private fun handleClear(result: MethodChannel.Result) {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                NanoWidgetReceiver.clearSnapshot(context)
                NanoWidgetReceiver.refreshAllNow(context)
                withContext(Dispatchers.Main) { result.success(null) }
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { result.success(null) }
            }
        }
    }

    private fun handleRefreshNow(result: MethodChannel.Result) {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                NanoWidgetReceiver.refreshAllNow(context)
                withContext(Dispatchers.Main) { result.success(null) }
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { result.success(null) }
            }
        }
    }

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
                put("last_clear_at", NanoWidgetDiagnostics.lastClearAt)
                put("last_refresh_now_at", NanoWidgetDiagnostics.lastRefreshNowAt)
            }
            withContext(Dispatchers.Main) { result.success(json.toString()) }
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {}
}
