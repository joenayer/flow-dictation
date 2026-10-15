package com.flowdictation.android

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Context
import android.content.Intent
import android.os.Looper
import android.provider.Settings
import android.view.accessibility.AccessibilityManager

/** Recoverable failures leave the transcript with its caller; never retry insertion automatically. */
enum class AutoInputResult(val message: String) {
    INSERTED("Text inserted."),
    INSERTED_CURSOR_UNCONFIRMED("Text inserted. Check the cursor position in this app."),
    INSERTION_UNCONFIRMED("The app accepted typing, but the result could not be confirmed. Check the field; your transcript is available in Flow."),
    NOT_CONNECTED("Automatic typing is unavailable. Your text is available in Flow."),
    NO_TARGET("No supported text field was selected. Your text is available in Flow."),
    TARGET_CHANGED("The text field changed while dictating. Your text is available in Flow."),
    UNSUPPORTED("This app did not accept automatic typing. Your text is available in Flow."),
    EMPTY_TRANSCRIPT("No speech recognized."),
}

/** Process-local main-thread bridge. No field text leaves the accessibility service. */
object AutoInputBridge {
    private var service: TypingAccessibilityService? = null
    private val listeners = linkedSetOf<() -> Unit>()
    var connected: Boolean = false
        private set
    var eligible: Boolean = false
        private set
    var keyboardTop: Int? = null
        private set

    fun addListener(listener: () -> Unit) { checkMain(); listeners.add(listener) }
    fun removeListener(listener: () -> Unit) { checkMain(); listeners.remove(listener) }
    fun captureTarget(): Long? { checkMain(); return service?.captureTarget() }
    fun insertTranscript(targetId: Long, text: String): AutoInputResult {
        checkMain()
        return service?.insertTranscript(targetId, text) ?: AutoInputResult.NOT_CONNECTED
    }
    fun clearTarget(targetId: Long? = null) { checkMain(); service?.clearTarget(targetId) }
    fun refresh() { checkMain(); service?.refresh() }

    fun isServiceEnabled(context: Context): Boolean {
        val manager = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as AccessibilityManager
        return manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK).any {
            it.resolveInfo.serviceInfo.packageName == context.packageName &&
                it.resolveInfo.serviceInfo.name == TypingAccessibilityService::class.java.name
        }
    }
    @Suppress("UNUSED_PARAMETER")
    fun settingsIntent(context: Context): Intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)

    internal fun attach(owner: TypingAccessibilityService) {
        checkMain(); service = owner; publish(owner, false, null)
    }
    internal fun publish(owner: TypingAccessibilityService, available: Boolean, imeTop: Int?) {
        if (service !== owner) return
        val changed = !connected || eligible != available || keyboardTop != imeTop
        connected = true; eligible = available; keyboardTop = imeTop
        if (changed) listeners.toList().forEach { it() }
    }
    internal fun detach(owner: TypingAccessibilityService) {
        if (service !== owner) return
        service = null; connected = false; eligible = false; keyboardTop = null
        listeners.toList().forEach { it() }
    }
    private fun checkMain() { check(Looper.myLooper() == Looper.getMainLooper()) { "Auto input must run on the main thread" } }
}
