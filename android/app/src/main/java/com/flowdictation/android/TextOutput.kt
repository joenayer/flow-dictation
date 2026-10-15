package com.flowdictation.android

import android.app.Activity
import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PersistableBundle
import java.util.UUID

/**
 * Clipboard and system-share output for transcripts. Automatic typing uses
 * [copy] as a fallback when the selected field cannot confirm an insertion.
 *
 * Copies are marked sensitive (hidden from clipboard previews on API 33+)
 * and auto-cleared after 60 s so dictated text does not linger.
 */
object TextOutput {
    private val main = Handler(Looper.getMainLooper())

    /** Copies [text] to the clipboard. Returns false when there is nothing to copy. */
    fun copy(context: Context, text: String): Boolean {
        if (text.isEmpty()) return false
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            ?: return false
        val clip = ClipData.newPlainText("Flow Dictation", text)
        val copyId = UUID.randomUUID().toString()
        clip.description.extras = PersistableBundle().apply {
            putString(COPY_ID, copyId)
            if (Build.VERSION.SDK_INT >= 33) putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true)
        }
        try { cm.setPrimaryClip(clip) } catch (_: Exception) { return false }
        main.postDelayed({
            try {
                // Only clear when our clip is still current: never wipe a
                // newer copy the user made afterwards.
                // Compare our copy identity, without reading clipboard text.
                // Identical words copied again still get a full 60 seconds.
                if (cm.primaryClipDescription?.extras?.getString(COPY_ID) == copyId) {
                    cm.setPrimaryClip(ClipData.newPlainText("", ""))
                }
            } catch (_: Exception) {
            }
        }, CLEAR_AFTER_MS)
        return true
    }

    /** Opens the system share sheet with [text]. Returns false when it cannot open. */
    fun share(context: Context, text: String): Boolean {
        if (text.isEmpty()) return false
        val intent = Intent(Intent.ACTION_SEND)
            .setType("text/plain")
            .putExtra(Intent.EXTRA_TEXT, text)
        val chooser = Intent.createChooser(intent, null)
        if (context !is Activity) {
            chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return try {
            context.startActivity(chooser)
            true
        } catch (_: Exception) {
            false
        }
    }

    private const val COPY_ID = "com.flowdictation.android.copy_id"
    private const val CLEAR_AFTER_MS = 60_000L
}
