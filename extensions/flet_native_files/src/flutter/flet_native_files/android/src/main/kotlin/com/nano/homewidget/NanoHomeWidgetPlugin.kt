package com.nano.homewidget

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import com.nano.shared.NanoSharedStorage
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Registers three channels:
 *   - nano/home_widget     (widget push/clear/refresh/diagnose)
 *   - nano/speech          (on-device SpeechRecognizer for Arabic commands)
 *   - nano/shared_storage  (cross-APK shared DB directory + diagnostics)
 */
class NanoHomeWidgetPlugin : FlutterPlugin, MethodChannel.MethodCallHandler, ActivityAware {
    private lateinit var channel: MethodChannel
    private lateinit var speechChannel: MethodChannel
    private lateinit var sharedStorageChannel: MethodChannel
    private lateinit var context: Context
    private var speechHandler: NanoSpeechHandler? = null
    private var activity: android.app.Activity? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        channel = MethodChannel(binding.binaryMessenger, "nano/home_widget")
        channel.setMethodCallHandler(this)

        sharedStorageChannel = MethodChannel(binding.binaryMessenger, "nano/shared_storage")
        sharedStorageChannel.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "get_shared_dir" ->
                        result.success(NanoSharedStorage.resolveDir(context).absolutePath)
                    "get_db_path" ->
                        result.success(NanoSharedStorage.databaseFile(context).absolutePath)
                    "diagnose" ->
                        result.success(NanoSharedStorage.diagnose(context))
                    "has_manage_storage" ->
                        result.success(
                            if (NanoSharedStorage.hasLegacyStoragePermission(context)) "true" else "false"
                        )
                    "request_manage_storage" -> {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                            val act = activity
                            if (act == null) {
                                result.error("no_activity", "Activity required", null)
                            } else {
                                try {
                                    val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                                    intent.data = Uri.parse("package:${context.packageName}")
                                    act.startActivity(intent)
                                    result.success("opened")
                                } catch (_: Exception) {
                                    try {
                                        act.startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                                        result.success("opened_general")
                                    } catch (e2: Exception) {
                                        result.error("intent_failed", e2.message, null)
                                    }
                                }
                            }
                        } else {
                            result.success("not_required")
                        }
                    }
                    else -> result.notImplemented()
                }
            } catch (e: Exception) {
                result.error("error", e.message, null)
            }
        }

        speechHandler = NanoSpeechHandler(context)
        speechChannel = MethodChannel(binding.binaryMessenger, NanoSpeechHandler.CHANNEL)
        speechChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "is_available" -> {
                    result.success(if (speechHandler?.isAvailable() == true) "1" else "0")
                }
                "listen" -> {
                    val args = call.arguments as? Map<*, *>
                    val language = (args?.get("language") as? String)?.ifBlank { null } ?: "ar-SY"
                    val timeoutMs = when (val t = args?.get("timeout_ms")) {
                        is Int -> t
                        is Number -> t.toInt()
                        is String -> t.toIntOrNull() ?: 8000
                        else -> 8000
                    }
                    speechHandler?.listen(language, timeoutMs, result)
                        ?: result.error("unavailable", "محرك الكلام غير مهيأ", null)
                }
                "cancel" -> {
                    speechHandler?.cancel()
                    result.success(null)
                }
                "speak" -> {
                    val args = call.arguments as? Map<*, *>
                    val textArg = (args?.get("text") as? String).orEmpty()
                    val language = (args?.get("language") as? String)?.ifBlank { null } ?: "ar"
                    speechHandler?.speak(textArg, language, result)
                        ?: result.error("unavailable", "محرك النطق غير مهيأ", null)
                }
                "stop_speak" -> {
                    speechHandler?.stopSpeak()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
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
                put("speech_available", speechHandler?.isAvailable() == true)
            }
            withContext(Dispatchers.Main) { result.success(json.toString()) }
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        speechHandler?.dispose()
        speechHandler = null
        try {
            channel.setMethodCallHandler(null)
            speechChannel.setMethodCallHandler(null)
            sharedStorageChannel.setMethodCallHandler(null)
        } catch (_: Exception) {
        }
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
        speechHandler?.attachActivity(binding.activity)
    }

    override fun onDetachedFromActivityForConfigChanges() {
        activity = null
        speechHandler?.attachActivity(null)
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        activity = binding.activity
        speechHandler?.attachActivity(binding.activity)
    }

    override fun onDetachedFromActivity() {
        activity = null
        speechHandler?.attachActivity(null)
    }
}
