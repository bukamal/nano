package com.nano.shared

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * MethodChannel: nano/shared_storage
 *
 * Methods:
 *   get_shared_dir   → absolute path string
 *   get_db_path      → absolute path to nano.db
 *   diagnose         → JSON diagnostics
 *   request_manage_storage → opens system settings for "All files access" (API 30+)
 *   has_manage_storage → "true"/"false"
 */
class NanoSharedStoragePlugin : FlutterPlugin, MethodChannel.MethodCallHandler, ActivityAware {
    private var channel: MethodChannel? = null
    private var context: Context? = null
    private var activity: Activity? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        channel = MethodChannel(binding.binaryMessenger, "nano/shared_storage")
        channel?.setMethodCallHandler(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel?.setMethodCallHandler(null)
        channel = null
        context = null
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivity() {
        activity = null
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivityForConfigChanges() {
        activity = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        val ctx = context
        if (ctx == null) {
            result.error("no_context", "Context not ready", null)
            return
        }
        try {
            when (call.method) {
                "get_shared_dir" -> {
                    result.success(NanoSharedStorage.resolveDir(ctx).absolutePath)
                }
                "get_db_path" -> {
                    result.success(NanoSharedStorage.databaseFile(ctx).absolutePath)
                }
                "diagnose" -> {
                    result.success(NanoSharedStorage.diagnose(ctx))
                }
                "has_manage_storage" -> {
                    result.success(
                        if (NanoSharedStorage.hasLegacyStoragePermission(ctx)) "true" else "false"
                    )
                }
                "request_manage_storage" -> {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        val act = activity
                        if (act == null) {
                            result.error("no_activity", "Activity required", null)
                            return
                        }
                        try {
                            val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                            intent.data = Uri.parse("package:${ctx.packageName}")
                            act.startActivity(intent)
                            result.success("opened")
                        } catch (e: Exception) {
                            // Fallback to general manage-all-files settings
                            try {
                                val intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                                act.startActivity(intent)
                                result.success("opened_general")
                            } catch (e2: Exception) {
                                result.error("intent_failed", e2.message, null)
                            }
                        }
                    } else {
                        result.success("not_required")
                    }
                }
                else -> result.notImplemented()
            }
        } catch (e: Exception) {
            Log.e("NanoSharedStoragePlugin", "call failed: ${call.method}", e)
            result.error("error", e.message, null)
        }
    }
}
