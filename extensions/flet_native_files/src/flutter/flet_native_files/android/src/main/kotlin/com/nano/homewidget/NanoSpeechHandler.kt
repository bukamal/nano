package com.nano.homewidget

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.plugin.common.MethodChannel

/**
 * On-device Arabic speech recognition via Android SpeechRecognizer.
 *
 * Channel: nano/speech
 * Methods:
 *   - is_available -> "1" | "0"
 *   - listen { language?: String, timeout_ms?: Int } -> final transcript or error:*
 *   - cancel -> null
 *
 * Permission RECORD_AUDIO is requested at listen-time when an Activity is bound.
 */
class NanoSpeechHandler(
    private val appContext: Context,
) {
    private var activity: Activity? = null
    private var recognizer: SpeechRecognizer? = null
    private var pendingResult: MethodChannel.Result? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var timeoutRunnable: Runnable? = null

    fun attachActivity(activity: Activity?) {
        this.activity = activity
    }

    fun isAvailable(): Boolean {
        return SpeechRecognizer.isRecognitionAvailable(appContext)
    }

    fun listen(language: String, timeoutMs: Int, result: MethodChannel.Result) {
        mainHandler.post {
            if (pendingResult != null) {
                result.error("busy", "استماع قيد التنفيذ بالفعل", null)
                return@post
            }
            if (!isAvailable()) {
                result.error("unavailable", "التعرّف على الكلام غير متاح على هذا الجهاز", null)
                return@post
            }
            val act = activity
            if (act != null &&
                ContextCompat.checkSelfPermission(act, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED
            ) {
                ActivityCompat.requestPermissions(
                    act,
                    arrayOf(Manifest.permission.RECORD_AUDIO),
                    REQ_RECORD_AUDIO,
                )
                // Caller should retry after granting; we fail fast with a clear message.
                result.error("permission", "يلزم السماح باستخدام الميكروفون ثم إعادة المحاولة", null)
                return@post
            }

            pendingResult = result
            try {
                destroyRecognizer()
                val rec = SpeechRecognizer.createSpeechRecognizer(appContext)
                recognizer = rec
                rec.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {}
                    override fun onBeginningOfSpeech() {}
                    override fun onRmsChanged(rmsdB: Float) {}
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {}
                    override fun onEvent(eventType: Int, params: Bundle?) {}

                    override fun onPartialResults(partialResults: Bundle?) {
                        // Final result is enough for command parsing; partials optional later.
                    }

                    override fun onResults(results: Bundle?) {
                        clearTimeout()
                        val texts = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        val best = texts?.firstOrNull()?.trim().orEmpty()
                        finishSuccess(if (best.isNotEmpty()) best else "")
                    }

                    override fun onError(error: Int) {
                        clearTimeout()
                        finishError(errorToMessage(error))
                    }
                })

                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, language.ifBlank { "ar-SY" })
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, language.ifBlank { "ar-SY" })
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                    putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                    putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, appContext.packageName)
                }
                rec.startListening(intent)

                val timeout = timeoutMs.coerceIn(3000, 20000)
                timeoutRunnable = Runnable {
                    try {
                        recognizer?.stopListening()
                    } catch (_: Exception) {
                    }
                    // If still pending after stop, surface timeout
                    mainHandler.postDelayed({
                        if (pendingResult != null) {
                            finishError("انتهى وقت الاستماع دون نتيجة واضحة")
                        }
                    }, 800)
                }
                mainHandler.postDelayed(timeoutRunnable!!, timeout.toLong())
            } catch (e: Exception) {
                finishError(e.message ?: "تعذّر بدء التعرّف على الكلام")
            }
        }
    }

    fun cancel() {
        mainHandler.post {
            clearTimeout()
            try {
                recognizer?.cancel()
            } catch (_: Exception) {
            }
            destroyRecognizer()
            val r = pendingResult
            pendingResult = null
            r?.success("") // empty = cancelled
        }
    }

    fun dispose() {
        cancel()
        activity = null
    }

    private fun finishSuccess(text: String) {
        val r = pendingResult ?: return
        pendingResult = null
        destroyRecognizer()
        r.success(text)
    }

    private fun finishError(message: String) {
        val r = pendingResult ?: return
        pendingResult = null
        destroyRecognizer()
        r.error("speech_error", message, null)
    }

    private fun clearTimeout() {
        timeoutRunnable?.let { mainHandler.removeCallbacks(it) }
        timeoutRunnable = null
    }

    private fun destroyRecognizer() {
        try {
            recognizer?.destroy()
        } catch (_: Exception) {
        }
        recognizer = null
    }

    private fun errorToMessage(code: Int): String {
        return when (code) {
            SpeechRecognizer.ERROR_AUDIO -> "خطأ في تسجيل الصوت"
            SpeechRecognizer.ERROR_CLIENT -> "أُلغي الاستماع"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "لا يوجد إذن للميكروفون"
            SpeechRecognizer.ERROR_NETWORK -> "التعرّف يحتاج مكوّناً غير متاح حالياً"
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "انتهت مهلة الشبكة"
            SpeechRecognizer.ERROR_NO_MATCH -> "لم يُفهم الكلام — أعد المحاولة"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "محرك الكلام مشغول"
            SpeechRecognizer.ERROR_SERVER -> "خدمة التعرّف غير متاحة"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "لم يُلتقط كلام"
            else -> "خطأ تعرّف ($code)"
        }
    }

    companion object {
        const val CHANNEL = "nano/speech"
        const val REQ_RECORD_AUDIO = 48121
    }
}
