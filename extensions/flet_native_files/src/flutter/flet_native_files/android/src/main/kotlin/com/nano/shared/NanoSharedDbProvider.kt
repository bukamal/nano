package com.nano.shared

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.UriMatcher
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.util.Log
import java.io.File
import java.io.FileNotFoundException

/**
 * Exposes the shared Nano SQLite database to other suite APKs signed with the
 * same certificate (signature-level permission).
 *
 * Authority: com.nano.shared.db
 *
 * URIs:
 *   content://com.nano.shared.db/database          → openFile (rwt) on nano.db
 *   content://com.nano.shared.db/info              → cursor with path/size metadata
 *   content://com.nano.shared.db/wal               → openFile on nano.db-wal (if any)
 *   content://com.nano.shared.db/shm               → openFile on nano.db-shm (if any)
 *
 * Only one package should *host* the provider (typically the accounting APK).
 * Client apps open the URI and either:
 *   - copy bytes into their private storage (simple, eventual consistency), or
 *   - prefer the shared-directory strategy from [NanoSharedStorage] for true
 *     concurrent WAL access.
 *
 * This provider is the safety net when external shared dirs are unavailable.
 */
class NanoSharedDbProvider : ContentProvider() {

    companion object {
        const val AUTHORITY = "com.nano.shared.db"
        const val PATH_DATABASE = "database"
        const val PATH_INFO = "info"
        const val PATH_WAL = "wal"
        const val PATH_SHM = "shm"

        private const val CODE_DATABASE = 1
        private const val CODE_INFO = 2
        private const val CODE_WAL = 3
        private const val CODE_SHM = 4

        private const val TAG = "NanoSharedDbProvider"

        val CONTENT_URI: Uri = Uri.parse("content://$AUTHORITY/$PATH_DATABASE")
        val INFO_URI: Uri = Uri.parse("content://$AUTHORITY/$PATH_INFO")

        private val matcher = UriMatcher(UriMatcher.NO_MATCH).apply {
            addURI(AUTHORITY, PATH_DATABASE, CODE_DATABASE)
            addURI(AUTHORITY, PATH_INFO, CODE_INFO)
            addURI(AUTHORITY, PATH_WAL, CODE_WAL)
            addURI(AUTHORITY, PATH_SHM, CODE_SHM)
        }

        fun dbFile(context: Context): File = NanoSharedStorage.databaseFile(context)
    }

    override fun onCreate(): Boolean {
        val ctx = context ?: return false
        try {
            NanoSharedStorage.resolveDir(ctx)
            Log.i(TAG, "Provider ready, db=${dbFile(ctx).absolutePath}")
        } catch (e: Exception) {
            Log.e(TAG, "Provider init failed", e)
        }
        return true
    }

    override fun getType(uri: Uri): String? {
        return when (matcher.match(uri)) {
            CODE_DATABASE, CODE_WAL, CODE_SHM -> "application/x-sqlite3"
            CODE_INFO -> "vnd.android.cursor.item/vnd.com.nano.shared.info"
            else -> null
        }
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?
    ): Cursor? {
        val ctx = context ?: return null
        if (matcher.match(uri) != CODE_INFO) return null
        val file = dbFile(ctx)
        val cols = arrayOf("path", "size", "exists", "dir", "truly_shared")
        val cursor = MatrixCursor(cols)
        cursor.addRow(
            arrayOf(
                file.absolutePath,
                if (file.exists()) file.length() else 0L,
                if (file.exists()) 1 else 0,
                file.parent ?: "",
                if (NanoSharedStorage.isTrulyShared(file.absolutePath)) 1 else 0
            )
        )
        return cursor
    }

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor? {
        val ctx = context ?: throw FileNotFoundException("no context")
        val file = when (matcher.match(uri)) {
            CODE_DATABASE -> dbFile(ctx)
            CODE_WAL -> File(dbFile(ctx).path + "-wal")
            CODE_SHM -> File(dbFile(ctx).path + "-shm")
            else -> throw FileNotFoundException("Unsupported URI: $uri")
        }

        if (matcher.match(uri) == CODE_DATABASE) {
            file.parentFile?.mkdirs()
            if (!file.exists()) {
                // Create empty file so clients can open rwt
                file.createNewFile()
            }
        } else if (!file.exists()) {
            throw FileNotFoundException("Missing ${file.name}")
        }

        val pfdMode = when {
            mode.contains("w") && mode.contains("r") ->
                ParcelFileDescriptor.MODE_READ_WRITE or
                    ParcelFileDescriptor.MODE_CREATE
            mode.contains("w") ->
                ParcelFileDescriptor.MODE_WRITE_ONLY or
                    ParcelFileDescriptor.MODE_CREATE
            else ->
                ParcelFileDescriptor.MODE_READ_ONLY
        }
        return ParcelFileDescriptor.open(file, pfdMode)
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?
    ): Int = 0
}
