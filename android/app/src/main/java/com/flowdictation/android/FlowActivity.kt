package com.flowdictation.android

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.snackbar.Snackbar

/** Native system bars and document export shared by the app's screens. */
open class FlowActivity : AppCompatActivity() {
    private var pendingExport = ""
    override fun onCreate(state: Bundle?) {
        AppCompatDelegate.setDefaultNightMode(when (Prefs(this).themeMode) {
            Prefs.THEME_MODE_DARK -> AppCompatDelegate.MODE_NIGHT_YES
            Prefs.THEME_MODE_SYSTEM -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
            else -> AppCompatDelegate.MODE_NIGHT_NO
        })
        super.onCreate(state)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val lightBars = resources.configuration.uiMode and
            android.content.res.Configuration.UI_MODE_NIGHT_MASK != android.content.res.Configuration.UI_MODE_NIGHT_YES
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = lightBars
            isAppearanceLightNavigationBars = lightBars
        }
        pendingExport = state?.getString("export_text") ?: ""
    }
    fun applyInsets() {
        val root = findViewById<View>(android.R.id.content)
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        ViewCompat.requestApplyInsets(root)
    }
    fun message(text: String) {
        if (!isFinishing && !isDestroyed) {
            Snackbar.make(findViewById(android.R.id.content), text, Snackbar.LENGTH_LONG).show()
        }
    }
    @Suppress("DEPRECATION")
    fun exportText(text: String, name: String) {
        if (text.isBlank()) { message("There is no text to export yet."); return }
        pendingExport = text
        try {
            startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("text/plain")
                .putExtra(Intent.EXTRA_TITLE, name), EXPORT)
        } catch (_: Exception) { message("No file picker is available. Use Share instead.") }
    }
    override fun onSaveInstanceState(out: Bundle) {
        out.putString("export_text", pendingExport)
        super.onSaveInstanceState(out)
    }
    @Deprecated("Framework result compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != EXPORT || resultCode != Activity.RESULT_OK) return
        val uri = data?.data ?: return
        val snapshot = pendingExport
        pendingExport = ""
        Thread {
            val ok = runCatching {
                contentResolver.openOutputStream(uri, "wt")?.use {
                    it.write(snapshot.toByteArray(Charsets.UTF_8))
                } ?: error("Cannot open file")
            }.isSuccess
            runOnUiThread { message(if (ok) "Text exported." else "Could not save the file. Try Share instead.") }
        }.start()
    }
    companion object { private const val EXPORT = 90 }
}
