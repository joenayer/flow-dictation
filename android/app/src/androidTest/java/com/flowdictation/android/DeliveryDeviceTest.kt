package com.flowdictation.android

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.util.concurrent.atomic.AtomicReference

/** Real bridge and system-clipboard checks using only synthetic test phrases. */
class DeliveryDeviceTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val target get() = instrumentation.targetContext
    private val testContext get() = instrumentation.context
    private lateinit var automation: android.app.UiAutomation
    private val component get() = ComponentName(target, TypingAccessibilityService::class.java).flattenToString()
    private var originalServices = "null"
    private var originalEnabled = "null"
    private var originalAutoInput = false
    private var originalBubble = false
    private var originalPreferencesCaptured = false
    private var flowWasBroughtToFront = false

    @Before fun setUp() {
        automation = instrumentation.getUiAutomation(
            android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
        automation.serviceInfo = automation.serviceInfo.apply {
            flags = flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
        }
        assertEquals("Test permission changes require an emulator", "1", shell("getprop ro.kernel.qemu").trim())
        originalServices = shell("settings get secure enabled_accessibility_services").trim()
        originalEnabled = shell("settings get secure accessibility_enabled").trim()
        main {
            val prefs = Prefs(target)
            originalAutoInput = prefs.autoInputEnabled
            originalBubble = prefs.bubbleEnabled
            originalPreferencesCaptured = true
        }
        val otherServices = originalServices.takeUnless { it == "null" }.orEmpty()
            .split(':').filter { it.isNotBlank() && it != component }
        setEnabledServices(otherServices + component)
        shell("settings put secure accessibility_enabled 1")
        main { Prefs(target).apply { autoInputEnabled = true; bubbleEnabled = true } }
        waitFor("accessibility service connects") { main { AutoInputBridge.connected } }
        launchFixture()
    }

    @After fun tearDown() {
        main {
            AutoInputBridge.clearTarget()
            if (originalPreferencesCaptured) Prefs(target).apply {
                autoInputEnabled = originalAutoInput
                bubbleEnabled = originalBubble
            }
            if (flowWasBroughtToFront) {
                runCatching { target.startForegroundService(DictationService.setBubbleIntent(target, originalBubble)) }
            }
        }
        automation.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_HOME)
        restoreSetting("enabled_accessibility_services", originalServices)
        restoreSetting("accessibility_enabled", originalEnabled)
    }

    @Test fun confirmedInsertionLeavesExistingClipboardUntouched() {
        val originalClip = "Synthetic prior clipboard content"
        // Android 14 gates clipboard access for background apps. Establish and
        // verify the sentinel while Flow is the focused app before opening the
        // external field; otherwise this test would confuse access denial with
        // an insertion overwriting the clipboard.
        bringFlowToFront()
        setClipboard(originalClip)
        assertEquals("Flow can read the seeded clipboard while in front", originalClip, clipboardText())
        launchFixture()
        focus("First field")
        selectRange("First field", 6, 9)
        waitFor("selected field is eligible") { main { AutoInputBridge.eligible } }
        val targetId = main { AutoInputBridge.captureTarget() }!!

        val delivery = main { AutoInputDelivery.deliver(target, targetId, "inserted synthetic phrase") }

        assertEquals(AutoInputResult.INSERTED, delivery.result)
        assertTrue(delivery.inserted)
        assertFalse(delivery.copied)
        assertEquals("Hello inserted synthetic phrase world", node("First field")?.text?.toString())
        bringFlowToFront()
        waitFor("clipboard is readable after Flow's window regains focus") {
            flowApplicationWindowFocused() && clipboardText() == originalClip
        }
        assertEquals("Confirmed insertion leaves the actual system clipboard unchanged", originalClip, clipboardText())
    }

    @Test fun changedTargetCopiesTranscriptAndPreservesOriginalFields() {
        focus("First field")
        waitFor("first field is eligible") { main { AutoInputBridge.eligible } }
        val targetId = main { AutoInputBridge.captureTarget() }!!
        focus("Second field")
        waitFor("second field takes focus") { node("Second field")?.isFocused == true }

        val delivery = main { AutoInputDelivery.deliver(target, targetId, "copied synthetic phrase") }

        assertEquals(AutoInputResult.TARGET_CHANGED, delivery.result)
        assertFalse(delivery.inserted)
        assertTrue(delivery.copied)
        assertEquals("Hello old world", node("First field")?.text?.toString())
        assertEquals("Other field untouched", node("Second field")?.text?.toString())
        bringFlowToFront()
        assertEquals("copied synthetic phrase", clipboardText())
    }

    @Test fun disconnectedBridgeCopiesTranscript() {
        focus("First field")
        waitFor("first field is eligible") { main { AutoInputBridge.eligible } }
        val targetId = main { AutoInputBridge.captureTarget() }!!
        setEnabledServices(emptyList())
        shell("settings put secure accessibility_enabled 0")
        waitFor("accessibility service disconnects") { !main { AutoInputBridge.connected } }

        val delivery = main { AutoInputDelivery.deliver(target, targetId, "offline synthetic phrase") }

        assertEquals(AutoInputResult.NOT_CONNECTED, delivery.result)
        assertFalse(delivery.inserted)
        assertTrue(delivery.copied)
        bringFlowToFront()
        assertEquals("offline synthetic phrase", clipboardText())
    }

    private fun launchFixture() {
        testContext.startActivity(Intent().setClassName(testContext.packageName,
            AutoInputFixtureActivity::class.java.name).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        waitFor("external test fixture opens") { node("First field") != null }
    }

    private fun bringFlowToFront() {
        target.startActivity(Intent(target, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
        flowWasBroughtToFront = true
        waitFor("Flow's application window receives focus") { flowApplicationWindowFocused() }
    }

    private fun flowApplicationWindowFocused(): Boolean = automation.windows.any { window ->
        if (window.type != AccessibilityWindowInfo.TYPE_APPLICATION || !window.isFocused) return@any false
        val root = window.root ?: return@any false
        try { root.packageName?.toString() == target.packageName }
        finally { root.recycle() }
    }

    private fun focus(label: String) {
        assertTrue("Field $label is present", node(label)?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true)
        waitFor("field $label receives focus") { node(label)?.isFocused == true }
    }

    private fun selectRange(label: String, start: Int, end: Int) {
        val field = node(label) ?: throw AssertionError("Field $label is missing")
        assertTrue("Selection range is inside $label", start >= 0 && end >= start && end <= (field.text?.length ?: 0))
        assertTrue("Set test selection in $label", field.performAction(
            AccessibilityNodeInfo.ACTION_SET_SELECTION, Bundle().apply {
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, start)
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, end)
            }))
        waitFor("selection is set in $label") { node(label)?.textSelectionStart == start && node(label)?.textSelectionEnd == end }
    }

    private fun node(label: String): AccessibilityNodeInfo? = allNodes().firstOrNull {
        it.packageName?.toString() == testContext.packageName &&
            (it.contentDescription?.toString() == label || it.text?.toString() == label)
    }

    private fun allNodes(): List<AccessibilityNodeInfo> {
        val found = mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo?) {
            if (node == null) return
            found += node
            repeat(node.childCount) { visit(node.getChild(it)) }
        }
        automation.windows.forEach { visit(it.root) }
        return found
    }

    private fun setClipboard(value: String) {
        main { (target.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
            .setPrimaryClip(ClipData.newPlainText("synthetic test", value)) }
    }

    private fun clipboardText(): String? = main {
        (target.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
            .primaryClip?.getItemAt(0)?.coerceToText(target)?.toString()
    }

    private fun restoreSetting(name: String, value: String) {
        val key = if (name == "enabled_accessibility_services" || name == "accessibility_enabled") "secure" else "global"
        if (value == "null") shell("settings delete $key $name") else shell("settings put $key $name $value")
    }

    private fun setEnabledServices(services: List<String>) {
        val value = services.joinToString(":")
        if (value.isEmpty()) shell("settings delete secure enabled_accessibility_services")
        else shell("settings put secure enabled_accessibility_services $value")
        val expected = value.ifEmpty { "null" }
        waitFor("enabled service list is updated") {
            shell("settings get secure enabled_accessibility_services").trim() == expected
        }
    }

    private fun shell(command: String): String =
        ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand(command)).bufferedReader().use { it.readText() }

    private fun <T> main(block: () -> T): T {
        val result = AtomicReference<T>()
        instrumentation.runOnMainSync { result.set(block()) }
        return result.get()
    }

    private fun waitFor(description: String, predicate: () -> Boolean) {
        val until = SystemClock.uptimeMillis() + 10_000
        while (SystemClock.uptimeMillis() < until) {
            if (predicate()) return
            SystemClock.sleep(100)
        }
        throw AssertionError("Timed out waiting for $description")
    }
}
