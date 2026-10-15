package com.flowdictation.android

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo

/**
 * Explicitly enabled by the user in Android settings. Observes the focused input only,
 * and modifies it only for a captured bubble dictation session. No clicks, submit actions,
 * clipboard writes, gesture injection, or automatic permission changes.
 */
class TypingAccessibilityService : AccessibilityService() {
    private data class Target(val id: Long, val node: AccessibilityNodeInfo, val snapshot: InputSnapshot)
    private var target: Target? = null
    private var invalidatedId: Long? = null
    private val main = Handler(Looper.getMainLooper())
    private val monitor = object : Runnable {
        override fun run() {
            refresh()
            if (target != null) main.postDelayed(this, 250)
        }
    }

    override fun onServiceConnected() {
        AutoInputBridge.attach(this)
        refresh()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        // Detect transient edits/focus moves too, even if the field returns to its
        // old value before the next scan. Ignore nonfocusable overlay/IME sources.
        val held = target
        if (held != null) {
            val source = event.source
            try {
                when (event.eventType) {
                    AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                        // A node refresh can already expose restored text. The
                        // change event itself invalidates the snapshot permanently.
                        if (source != null && source == held.node) invalidate()
                    }
                    AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED -> {
                        if (source != null && source == held.node &&
                            (snapshot(source) != held.snapshot ||
                                event.fromIndex != held.snapshot.selectionStart ||
                                event.toIndex != held.snapshot.selectionEnd)) invalidate()
                    }
                    AccessibilityEvent.TYPE_VIEW_FOCUSED -> {
                        if (source != null && source != held.node) invalidate()
                    }
                    AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                        val eventWindows = windows
                        try {
                            if (event.packageName != null && event.packageName.toString() != held.snapshot.packageName &&
                                eventWindows.any { it.id == event.windowId && it.type == AccessibilityWindowInfo.TYPE_APPLICATION }) invalidate()
                        } finally { eventWindows.forEach { it.recycle() } }
                    }
                }
            } finally { source?.recycle() }
        }
        refresh()
    }

    override fun onInterrupt() {
        invalidate()
        AutoInputBridge.publish(this, false, null)
    }

    override fun onDestroy() {
        clearTarget()
        AutoInputBridge.detach(this)
        super.onDestroy()
    }

    internal fun refresh() {
        // Do not inspect fields until both opt-ins are enabled. The service's system
        // toggle alone grants permission, but does not activate the product feature.
        val prefs = Prefs(this)
        if (!prefs.autoInputEnabled || !prefs.bubbleEnabled) {
            invalidate()
            AutoInputBridge.publish(this, false, null)
            return
        }
        val focused = focusedInput()
        try {
            val held = target
            if (held != null && (focused == null || focused != held.node ||
                    !held.node.refresh() || !safe(held.node) || snapshot(held.node) != held.snapshot)) {
                invalidate()
            }
            AutoInputBridge.publish(this, focused != null && safe(focused), keyboardTop())
        } catch (_: IllegalStateException) {
            invalidate()
            AutoInputBridge.publish(this, false, null)
        } finally { focused?.recycle() }
    }

    internal fun captureTarget(): Long? {
        clearTarget()
        refresh()
        if (!AutoInputBridge.eligible) return null
        val node = focusedInput() ?: return null
        if (!safe(node)) { node.recycle(); return null }
        val state = snapshot(node)
        if (AutoInputPolicy.replacement(state, state, "x") == null) { node.recycle(); return null }
        val id = ++sequence
        target = Target(id, node, state)
        main.postDelayed(monitor, 250)
        return id
    }

    internal fun insertTranscript(id: Long, transcript: String): AutoInputResult {
        refresh()
        val held = target
        if (held == null || held.id != id) {
            return if (invalidatedId == id) AutoInputResult.TARGET_CHANGED else AutoInputResult.NO_TARGET
        }
        if (transcript.isBlank()) { clearTarget(id); return AutoInputResult.EMPTY_TRANSCRIPT }
        val current = snapshot(held.node)
        val replacement = AutoInputPolicy.replacement(held.snapshot, current, transcript)
            ?: return AutoInputResult.TARGET_CHANGED.also { invalidate() }
        if (held.node.maxTextLength >= 0 && replacement.text.length > held.node.maxTextLength) {
            clearTarget(id)
            return AutoInputResult.UNSUPPORTED
        }
        // Retain the original node only for this action; events produced by our own
        // write cannot invalidate a completed session. Never restore or force focus.
        target = null
        main.removeCallbacks(monitor)
        var delivered = false
        var confirmed = false
        try {
            val changed = held.node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, replacement.text)
            })
            if (!changed) return AutoInputResult.UNSUPPORTED
            delivered = true
            // A widget may acknowledge SET_TEXT asynchronously. Never retry/replace
            // again: that could duplicate output or overwrite subsequent user edits.
            if (!held.node.refresh() || fieldText(held.node) != replacement.text) {
                return AutoInputResult.INSERTION_UNCONFIRMED
            }
            confirmed = true
            if (!held.node.isFocused) return AutoInputResult.INSERTED_CURSOR_UNCONFIRMED
            // Native EditText's SET_TEXT already moves the cursor to the end.
            // SET_SELECTION returns false for a no-op even when that cursor is correct.
            if (held.node.textSelectionStart == replacement.cursor &&
                held.node.textSelectionEnd == replacement.cursor) return AutoInputResult.INSERTED
            held.node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, Bundle().apply {
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, replacement.cursor)
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, replacement.cursor)
            })
            if (!held.node.refresh()) return AutoInputResult.INSERTED_CURSOR_UNCONFIRMED
            if (fieldText(held.node) != replacement.text) return AutoInputResult.INSERTION_UNCONFIRMED
            return if (held.node.isFocused && held.node.textSelectionStart == replacement.cursor &&
                held.node.textSelectionEnd == replacement.cursor) AutoInputResult.INSERTED
            else AutoInputResult.INSERTED_CURSOR_UNCONFIRMED
        } catch (_: RuntimeException) {
            return when {
                confirmed -> AutoInputResult.INSERTED_CURSOR_UNCONFIRMED
                delivered -> AutoInputResult.INSERTION_UNCONFIRMED
                else -> AutoInputResult.UNSUPPORTED
            }
        } finally { held.node.recycle() }
    }

    internal fun clearTarget(id: Long? = null) {
        if (id != null && target?.id != id) return
        target?.node?.recycle()
        target = null
        invalidatedId = null
        main.removeCallbacks(monitor)
    }

    private fun invalidate() {
        val held = target ?: return
        invalidatedId = held.id
        held.node.recycle()
        target = null
        main.removeCallbacks(monitor)
    }

    private fun snapshot(node: AccessibilityNodeInfo) = InputSnapshot(
        node.packageName?.toString().orEmpty(), node.windowId,
        fieldText(node), node.textSelectionStart, node.textSelectionEnd,
        node.className?.toString() == "android.widget.EditText",
    )

    private fun fieldText(node: AccessibilityNodeInfo): String =
        AutoInputPolicy.fieldText(node.text?.toString(), node.isShowingHintText)

    private fun safe(node: AccessibilityNodeInfo): Boolean =
        node.packageName != null && node.packageName.toString() != packageName &&
            node.packageName.toString() != "com.flowdictation.android" &&
            node.packageName.toString() != "com.flowdictation.android.preview" &&
            node.isEditable && node.isEnabled && node.isVisibleToUser && node.isFocused &&
            !node.isPassword && AutoInputPolicy.safeInputType(node.inputType) &&
            !(Build.VERSION.SDK_INT >= 34 && node.isAccessibilityDataSensitive) &&
            AutoInputPolicy.supportsTextActions(
                fieldText(node), node.textSelectionStart, node.textSelectionEnd,
                node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_SET_TEXT },
                node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_SET_SELECTION },
                node.className?.toString() == "android.widget.EditText",
            )

    /** Read only the active application window's input focus, never all screen text. */
    private fun focusedInput(): AccessibilityNodeInfo? {
        val windowList = windows
        try {
            val application = windowList.firstOrNull {
                it.type == AccessibilityWindowInfo.TYPE_APPLICATION && it.isFocused
            } ?: windowList.firstOrNull {
                it.type == AccessibilityWindowInfo.TYPE_APPLICATION && it.isActive
            } ?: return null
            val root = application.root ?: return null
            try { return root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }
            finally { root.recycle() }
        } finally { windowList.forEach { it.recycle() } }
    }

    private fun keyboardTop(): Int? {
        val windowList = windows
        try {
            val keyboard = windowList.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }
                ?: return null
            return Rect().also { keyboard.getBoundsInScreen(it) }.takeUnless { it.isEmpty }?.top
        } finally { windowList.forEach { it.recycle() } }
    }

    companion object {
        // Unique across accessibility service reconnections in this process.
        private var sequence = 0L
    }
}
