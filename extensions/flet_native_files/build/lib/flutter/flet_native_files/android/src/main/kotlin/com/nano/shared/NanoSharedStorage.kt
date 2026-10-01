package com.nano.shared

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Environment
import android.util.Log
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.io.File

/**
 * Resolves a directory that *all* Nano suite APKs (accounting / inventory / POS)
 * can read and write, so they share one SQLite file.
 *
 * Strategy:
 *  1. Public Documents/NanoShared  — preferred cross-app location
 *  2. External storage root /NanoShared
 *  3. App-specific external / internal (last resort — NOT shared across APKs)
 *
 * On Android 11+ the user **must** grant "All files access"
 * (MANAGE_EXTERNAL_STORAGE) for steps 1–2 to succeed across packages.
 * Without it every APK falls back to its private dir → each app sees a
 * different (often empty) database. That is the root cause of
 * "التطبيقات لا تقرأ قاعدة البيانات".
 *
 * Authority conflicts are avoided by using per-applicationId providers;
 * this class only cares about the shared *file path*.
 */
object NanoSharedStorage {
    private const val TAG = "NanoSharedStorage"
    const val FOLDER_NAME = "NanoShared"
    const val DB_FILE_NAME = "nano.db"

    private fun tryWritable(dir: File): File? {
        return try {
            if (!dir.exists()) {
                dir.mkdirs()
            }
            if (!dir.exists() || !dir.canWrite()) return null
            val probe = File(dir, ".nano_write_probe")
            probe.writeText("ok")
            probe.delete()
            dir
        } catch (e: Exception) {
            Log.w(TAG, "Candidate failed ${dir.absolutePath}: $e")
            null
        }
    }

    fun resolveDir(context: Context): File {
        val publicCandidates = mutableListOf<File>()
        val privateCandidates = mutableListOf<File>()

        // --- Public (truly shared) candidates first ---
        try {
            val docs = Environment.getExternalStoragePublicDirectory(
                Environment.DIRECTORY_DOCUMENTS
            )
            if (docs != null) {
                publicCandidates.add(File(docs, FOLDER_NAME))
            }
        } catch (_: Exception) {
        }

        try {
            val ext = Environment.getExternalStorageDirectory()
            if (ext != null) {
                publicCandidates.add(File(ext, FOLDER_NAME))
            }
        } catch (_: Exception) {
        }

        for (dir in publicCandidates) {
            val ok = tryWritable(dir)
            if (ok != null) {
                Log.i(TAG, "Using SHARED dir: ${ok.absolutePath}")
                return ok
            }
        }

        // --- Private fallback (app still runs, but data is NOT shared) ---
        try {
            val appExt = context.getExternalFilesDir(null)
            if (appExt != null) {
                privateCandidates.add(File(appExt, FOLDER_NAME))
            }
        } catch (_: Exception) {
        }
        privateCandidates.add(File(context.filesDir, FOLDER_NAME))

        for (dir in privateCandidates) {
            val ok = tryWritable(dir)
            if (ok != null) {
                Log.w(
                    TAG,
                    "Falling back to PRIVATE dir (other suite APKs will NOT see this DB): ${ok.absolutePath}. " +
                        "Grant All files access and restart."
                )
                return ok
            }
        }

        val fallback = File(context.filesDir, FOLDER_NAME)
        fallback.mkdirs()
        Log.e(TAG, "Absolute private fallback: ${fallback.absolutePath}")
        return fallback
    }

    fun databaseFile(context: Context): File {
        return File(resolveDir(context), DB_FILE_NAME)
    }

    fun isTrulyShared(path: String): Boolean {
        val p = path.lowercase()
        return !p.contains("/android/data/") &&
            !p.contains("/data/user/") &&
            !p.contains("/data/data/")
    }

    fun hasLegacyStoragePermission(context: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.WRITE_EXTERNAL_STORAGE
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true
        }
    }

    fun diagnose(context: Context): String {
        val dir = resolveDir(context)
        val db = File(dir, DB_FILE_NAME)
        val json = JSONObject()
        json.put("dir", dir.absolutePath)
        json.put("db_path", db.absolutePath)
        json.put("dir_exists", dir.exists())
        json.put("dir_writable", dir.canWrite())
        json.put("db_exists", db.exists())
        json.put("db_size", if (db.exists()) db.length() else 0)
        json.put("truly_shared", isTrulyShared(dir.absolutePath))
        json.put("has_storage_permission", hasLegacyStoragePermission(context))
        json.put("sdk", Build.VERSION.SDK_INT)
        json.put(
            "hint",
            if (!isTrulyShared(dir.absolutePath) && !hasLegacyStoragePermission(context))
                "grant_all_files_access_then_restart"
            else
                "ok"
        )
        return json.toString()
    }
}
