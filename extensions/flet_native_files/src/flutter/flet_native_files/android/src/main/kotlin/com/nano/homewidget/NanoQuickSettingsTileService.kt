package com.nano.homewidget

import android.app.PendingIntent
import android.content.Intent
import android.graphics.drawable.Icon
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import androidx.annotation.RequiresApi

/**
 * PHASE10 Quick Settings tile: a one-tap launcher for Nano from the QS
 * panel, including from a locked device (the panel is reachable from the
 * lock screen without unlocking first; opening the app itself still goes
 * through whatever auth the device/app already enforces).
 *
 * Deliberately self-contained: unlike the home screen widget, this does not
 * read the Glance snapshot (that state lives per widget-instance under
 * PreferencesGlanceStateDefinition and is empty/absent whenever the widget
 * itself isn't placed on a home screen). A plain launcher tile has no such
 * dependency and can never show a stale or blank state.
 *
 * TileService only exists from API 24; this module's minSdk is 23, but the
 * class is safe to ship unconditionally because pre-N devices have no QS
 * tile picker to ever discover, bind, or instantiate it.
 */
@RequiresApi(Build.VERSION_CODES.N)
class NanoQuickSettingsTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        qsTile?.let { tile ->
            tile.label = "نانو"
            tile.contentDescription = "فتح نانو"
            tile.icon = Icon.createWithResource(this, R.drawable.ic_nano_tile)
            tile.state = Tile.STATE_ACTIVE
            tile.updateTile()
        }
    }

    override fun onClick() {
        super.onClick()
        // mainActivityClass() throws if it can't resolve the generated
        // app's launcher Activity by name (see its own doc comment in
        // NanoGlanceWidget.kt). A tile tap is user-initiated and not on any
        // hot rendering path like the widget is, so an uncaught exception
        // here would just crash the System UI process's tile interaction --
        // still worth swallowing rather than letting a resolution failure
        // surface as a crash instead of a silent no-op tap.
        val activityClass = try {
            mainActivityClass(this)
        } catch (_: Exception) {
            return
        }
        val launchIntent = Intent(this, activityClass).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            val pendingIntent = PendingIntent.getActivity(
                this,
                0,
                launchIntent,
                PendingIntent.FLAG_IMMUTABLE
            )
            startActivityAndCollapse(pendingIntent)
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(launchIntent)
        }
    }
}
