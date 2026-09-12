package com.nano.shared

import android.Manifest
import android.app.Activity
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
 * Strategy (first writable match wins):
 *  1. Public Documents/NanoShared  — works across packages when storage
 *     permission is granted (or on older Android with legacy storage).
 *  2. External storage root /NanoShared (fallback).
 *  3. App-specific external files dir (last resort — NOT shared across APKs).
 *
 * Call [ensureWritable] before opening the database. On Android 11+ the user
 * may need to grant "All files access" for true cross-app sharing; the
 * ContentProvider path is the cleaner long-term alternative.
 */
object NanoSharedStorage {
    private const val TAG = "NanoSharedStorage"
    const val FOLDER_NAME = "NanoShared"
    const val DB_FILE_NAME = "nano.db"

    fun resolveDir(context: Context): File {
        val candidates = mutableListOf<File>()

        // 1) Documents/NanoShared (preferred cross-app location)
        try {
            val docs = Environment.getExternalStoragePublicDirectory(
                Environment.DIRECTORY_DOCUMENTS
            )
            if (docs != null) {
                candidates.add(File(docs, FOLDER_NAME))
            }
        } catch (_: Exception) {
        }

        // 2) /storage/emulated/0/NanoShared
        try {
            val ext = Environment.getExternalStorageDirectory()
            if (ext != null) {
                candidates.add(File(ext, FOLDER_NAME))
            }
        } catch (_: Exception) {
        }

        // 3) App-specific external (NOT shared — last resort so the app still runs)
        try {
            val appExt = context.getExternalFilesDir(null)
            if (appExt != null) {
                candidates.add(File(appExt, FOLDER_NAME))
            }
        } catch (_: Exception) {
        }

        // 4) Internal files dir
        candidates.add(File(context.filesDir, FOLDER_NAME))

        for (dir in candidates) {
            try {
                if (!dir.exists()) {
                    dir.mkdirs()
                }
                if (dir.exists() && dir.canWrite()) {
                    // Probe write
                    val probe = File(dir, ".nano_write_probe")
                    probe.writeText("ok")
                    probe.delete()
                    Log.i(TAG, "Using shared dir: ${dir.absolutePath}")
                    return dir
                }
            } catch (e: Exception) {
                Log.w(TAG, "Candidate failed ${dir.absolutePath}: $e")
            }
        }

        // Absolute last resort
        val fallback = File(context.filesDir, FOLDER_NAME)
        fallback.mkdirs()
        Log.w(TAG, "Falling back to private dir: ${fallback.absolutePath}")
        return fallback
    }

    fun databaseFile(context: Context): File {
        return File(resolveDir(context), DB_FILE_NAME)
    }

    fun isTrulyShared(path: String): Boolean {
        // Private app dirs contain the package name or "files" under Android/data
        val p = path.lowercase()
        return !p.contains("/android/data/") && !p.contains("/data/user/")
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
        return json.toString()
    }
}
