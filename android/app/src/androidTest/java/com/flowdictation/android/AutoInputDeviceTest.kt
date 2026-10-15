package com.flowdictation.android

import android.app.UiAutomation
import android.content.ComponentName
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Before
import org.junit.After
import org.junit.Test
import org.junit.Rule
import org.junit.rules.TestName
import android.view.accessibility.AccessibilityNodeInfo
import android.accessibilityservice.AccessibilityServiceInfo
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.atomic.AtomicReference

/**
 * Real emulator accessibility/overlay tests. Recognized text is supplied directly
 * to the production bridge; microphone capture and speech accuracy are NOT tested.
 * No result-injection entry point is added to the shipping APK.
 */
@Suppress("DEPRECATION")
class AutoInputDeviceTest {
    @get:Rule val testName = TestName()
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private lateinit var automation: UiAutomation
    private val target get() = instrumentation.targetContext
    private val fixturePackage get() = instrumentation.context.packageName
    private val serviceComponent get() = ComponentName(target, TypingAccessibilityService::class.java).flattenToString()

    @Before
    fun setUp() {
        // Default UiAutomation suppresses the very accessibility service under test.
        automation = instrumentation.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
        automation.serviceInfo = automation.serviceInfo.apply {
            flags = flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
        }
        try {
            assertEquals("Accessibility test permission changes require a disposable emulator", "1",
                shell("getprop ro.kernel.qemu").trim())
            // am instrument kills the target process. Android may retain its enabled
            // component while marking the previous accessibility connection crashed.
            // Removing it first clears that temporary state; putting the same value
            // alone may not trigger a Settings observer or reconnect the service.
            val enabled = shell("settings get secure enabled_accessibility_services").trim()
            val otherServices = enabled.takeUnless { it == "null" }.orEmpty()
                .split(':').filter { it.isNotBlank() && it != serviceComponent }
            setEnabledServices(otherServices)
            waitFor("old accessibility connection disabled before rebinding") {
                !main { AutoInputBridge.connected } && !AutoInputBridge.isServiceEnabled(target)
            }
            // Wait for the asynchronous secure-settings observer to remove crashed/
            // binding state before enabling again, even if the old binder was dead.
            SystemClock.sleep(250)
            setEnabledServices(otherServices + serviceComponent)
            shell("settings put secure accessibility_enabled 1")
            main {
                Prefs(target).apply { bubbleEnabled = true; autoInputEnabled = true }
                DictationEvents.emitState(DictState.IDLE)
            }
            waitFor("accessibility service connected") { main { AutoInputBridge.connected } }
            launchFixture(clearTask = true)
            target.startForegroundService(DictationService.refreshAutoBubbleIntent(target))
        } catch (failure: Throwable) {
            try {
                val directory = File(target.getExternalFilesDir(null), "auto-input-tests").apply { mkdirs() }
                File(directory, "setup-failure-${testName.methodName}-diagnostics.txt").writeText(
                    "${failure.javaClass.name}: ${failure.message}\n" +
                    "Expected service: $serviceComponent\n" +
                    "Secure enabled services: ${shell("settings get secure enabled_accessibility_services").trim()}\n" +
                    "Bridge connected: ${main { AutoInputBridge.connected }}\n" +
                    "Service enabled: ${AutoInputBridge.isServiceEnabled(target)}\n" +
                    shell("dumpsys accessibility"))
                screenshot("setup-failure-${testName.methodName}")
            } catch (diagnosticFailure: Throwable) { failure.addSuppressed(diagnosticFailure) }
            throw failure
        }
    }

    @After
    fun tearDown() {
        main {
            AutoInputBridge.clearTarget()
            Prefs(target).apply { autoInputEnabled = false; bubbleEnabled = false }
            DictationEvents.emitState(DictState.IDLE)
        }
        target.stopService(Intent(target, DictationService::class.java))
        automation.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_HOME)
        waitFor("fixture leaves screen after Home cleanup") { node("First field") == null }
    }

    @Test
    fun testAvailabilityKeyboardAndDismissal() = verified {
        assertFalse("No field initially focused", main { AutoInputBridge.eligible })
        focus("First field")
        waitFor("IME bounds") { main { AutoInputBridge.keyboardTop != null } }
        waitFor("automatic microphone overlay") { bubble() != null }
        assertEquals("Focusing a field never starts recording", DictState.IDLE, DictationEvents.state)
        val micBounds = Rect().also { bubble()!!.getBoundsInScreen(it) }
        val keyboardTop = main { AutoInputBridge.keyboardTop!! }
        val keyboardGap = (12 * target.resources.displayMetrics.density).toInt()
        assertTrue("Microphone remains above IME ($micBounds, top=$keyboardTop)", micBounds.bottom <= keyboardTop)
        screenshot("01-focused-field-keyboard-bubble")
        dragBubbleTowardKeyboard(micBounds, keyboardTop)
        waitFor("drag moves bubble to keyboard boundary") {
            bubble()?.let { node ->
                val moved = Rect().also { node.getBoundsInScreen(it) }
                moved.top > micBounds.top && moved.bottom <= keyboardTop - keyboardGap
            } == true
        }
        val draggedBounds = Rect().also { bubble()!!.getBoundsInScreen(it) }
        assertTrue("Dragged mic stays above actual IME ($draggedBounds, top=$keyboardTop)", draggedBounds.bottom <= keyboardTop - keyboardGap)
        assertEquals("Dragging does not trigger dictation", DictState.IDLE, DictationEvents.state)
        screenshot("01b-dragged-bubble-clamped-above-keyboard")
        automation.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK)
        waitFor("IME hidden with editable field still focused") {
            main { AutoInputBridge.keyboardTop == null && AutoInputBridge.eligible } && bubble() != null
        }
        dragBubbleTowardKeyboard(draggedBounds, target.resources.displayMetrics.heightPixels)
        waitFor("bubble dragged below previous keyboard boundary") {
            bubble()?.let { node -> Rect().also { node.getBoundsInScreen(it) }.bottom > keyboardTop } == true
        }
        click("First field")
        waitFor("IME reappears and clamps existing bubble") {
            val top = main { AutoInputBridge.keyboardTop } ?: return@waitFor false
            bubble()?.let { node -> Rect().also { node.getBoundsInScreen(it) }.bottom <= top - keyboardGap } == true
        }
        assertEquals("Showing keyboard after drag does not record", DictState.IDLE, DictationEvents.state)
        screenshot("01c-keyboard-appears-after-drag-bubble-clamped")
        click("Dismiss input")
        waitFor("focus loss hides automatic bubble") { !main { AutoInputBridge.eligible } && bubble() == null }
        waitFor("dismissed IME bounds cleared") { main { AutoInputBridge.keyboardTop == null } }
        assertNotNull("Dismissing input keeps the external activity alive", node("Dismiss input"))
        screenshot("02-dismissed-input-no-bubble")
    }

    @Test
    fun testInsertAtOriginalSelectionAndNoResultPanel() = verified {
        focus("First field")
        select("First field", 6, 9)
        // Allow selection events to reach the service before taking its snapshot.
        SystemClock.sleep(350)
        val token = main { AutoInputBridge.captureTarget() }
        assertNotNull("Capture original external field", token)
        val result = main { AutoInputBridge.insertTranscript(token!!, "new") }
        assertEquals(AutoInputResult.INSERTED, result)
        waitFor("replacement delivered to external app") { node("First field")?.text?.toString() == "Hello new world" }
        val first = node("First field")!!
        assertEquals(9, first.textSelectionStart)
        assertEquals(9, first.textSelectionEnd)
        assertEquals("Other field untouched", node("Second field")!!.text.toString())
        // Exercise actual bubble result-event handling, without a main-APK backdoor.
        main { DictationEvents.emitAutoResult("new", 1200L, true) }
        instrumentation.waitForIdleSync()
        waitFor("bubble remains collapsed") { bubble() != null }
        assertNoResultPanel()
        screenshot("03-inserted-original-selection-no-panel")
        assertEquals("Consumed token cannot insert twice", AutoInputResult.NO_TARGET,
            main { AutoInputBridge.insertTranscript(token!!, "duplicate") })

        // Android exposes a native EditText placeholder as node.text on some versions.
        // It must never be treated as existing user text or included in a dictation.
        focus("Empty field")
        fieldDiagnostics("03b-empty-field-before-insertion")
        assertTrue("Fixture exposes a placeholder, not user text", node("Empty field")!!.isShowingHintText)
        assertEquals("Type a message", node("Empty field")!!.hintText?.toString())
        val emptyToken = main { AutoInputBridge.captureTarget() }
        assertNotNull("Empty field with hint is eligible", emptyToken)
        assertEquals(AutoInputResult.INSERTED, main { AutoInputBridge.insertTranscript(emptyToken!!, "Hello") })
        waitFor("first phrase replaces empty content without hint") {
            node("Empty field")?.let { !it.isShowingHintText && it.text?.toString() == "Hello" && it.textSelectionStart == 5 && it.textSelectionEnd == 5 } == true
        }
        SystemClock.sleep(350)
        val secondToken = main { AutoInputBridge.captureTarget() }
        assertNotNull("Capture consecutive dictation at collapsed cursor", secondToken)
        assertEquals(AutoInputResult.INSERTED, main { AutoInputBridge.insertTranscript(secondToken!!, "world") })
        waitFor("consecutive dictation adds word separation and moves cursor") {
            node("Empty field")?.let { it.text?.toString() == "Hello world" && it.textSelectionStart == 11 && it.textSelectionEnd == 11 } == true
        }
        assertEquals("First field unchanged by empty-field dictation", "Hello new world", node("First field")!!.text.toString())
        assertNoResultPanel()
        screenshot("03b-empty-hint-field-two-phrases")
    }

    @Test
    fun testPasswordIsExcluded() = verified {
        focus("First field")
        click("Password field")
        waitFor("password excluded and bubble hidden") { !main { AutoInputBridge.eligible } && bubble() == null }
        assertNull(main { AutoInputBridge.captureTarget() })
        screenshot("04-password-no-bubble")
    }

    @Test
    fun testFocusChangeInvalidatesOriginalEvenWhenReturning() = verified {
        focus("First field")
        val token = main { AutoInputBridge.captureTarget() }!!
        focus("Second field")
        SystemClock.sleep(350)
        focus("First field")
        val result = main { AutoInputBridge.insertTranscript(token, "unexpected") }
        assertTrue("Changed focus must fail safely: $result", result == AutoInputResult.TARGET_CHANGED || result == AutoInputResult.NO_TARGET)
        assertEquals("Hello old world", node("First field")!!.text.toString())
        assertEquals("Other field untouched", node("Second field")!!.text.toString())
        val selectionToken = main { AutoInputBridge.captureTarget() }!!
        val initialCursor = node("First field")!!.textSelectionStart
        val movedCursor = if (initialCursor == 0) 1 else 0
        select("First field", movedCursor, movedCursor)
        SystemClock.sleep(350)
        select("First field", initialCursor, initialCursor)
        SystemClock.sleep(350)
        val changedSelection = main { AutoInputBridge.insertTranscript(selectionToken, "unexpected") }
        assertTrue("Selection movement and restoration invalidate token", changedSelection == AutoInputResult.TARGET_CHANGED || changedSelection == AutoInputResult.NO_TARGET)
        assertEquals("Hello old world", node("First field")!!.text.toString())
    }

    @Test
    fun testUserEditInvalidatesTranscriptAndFailureHasNoResultPanel() = verified {
        focus("First field")
        val token = main { AutoInputBridge.captureTarget() }!!
        assertTrue(node("First field")!!.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, "User changed this")
        }))
        waitFor("user edit delivered") { node("First field")?.text?.toString() == "User changed this" }
        SystemClock.sleep(350)
        // Even restoring the exact original text must not revive a stale session.
        assertTrue(node("First field")!!.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, "Hello old world")
        }))
        waitFor("restored user text delivered") { node("First field")?.text?.toString() == "Hello old world" }
        SystemClock.sleep(350)
        val result = main { AutoInputBridge.insertTranscript(token, "unexpected") }
        assertTrue("Changed text must fail safely: $result", result == AutoInputResult.TARGET_CHANGED || result == AutoInputResult.NO_TARGET)
        main { DictationEvents.emitAutoResult("recoverable transcript", 1200L, false) }
        instrumentation.waitForIdleSync()
        assertEquals("Hello old world", node("First field")!!.text.toString())
        assertEquals("recoverable transcript", DictationEvents.peekPendingResult()?.text)
        assertNoResultPanel()
        screenshot("05-user-edit-preserved-failure-no-panel")
    }

    @Test
    fun testSwitchingAppInvalidatesTargetAndHidesBubble() = verified {
        focus("First field")
        val token = main { AutoInputBridge.captureTarget() }!!
        automation.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_HOME)
        waitFor("leaving external field hides bubble") { !main { AutoInputBridge.eligible } && bubble() == null }
        val result = main { AutoInputBridge.insertTranscript(token, "unexpected") }
        assertTrue("Leaving app must fail safely: $result", result == AutoInputResult.TARGET_CHANGED || result == AutoInputResult.NO_TARGET)
        screenshot("06-home-no-bubble")
        launchFixture(clearTask = false)
        focus("First field")
        val returned = main { AutoInputBridge.insertTranscript(token, "unexpected") }
        assertTrue("Returning to original app cannot revive token", returned == AutoInputResult.TARGET_CHANGED || returned == AutoInputResult.NO_TARGET)
        assertEquals("Hello old world", node("First field")!!.text.toString())
    }

    @Test
    fun testDisablingAccessibilityDisconnectsAndHidesBubble() = verified {
        focus("First field")
        waitFor("bubble shown before disabling service") { bubble() != null }
        try {
            setEnabledServices(emptyList())
            shell("settings put secure accessibility_enabled 0")
            waitFor("disabled accessibility service disconnects and hides bubble") {
                !main { AutoInputBridge.connected } && bubble() == null
            }
            assertNull(main { AutoInputBridge.captureTarget() })
            assertFalse(AutoInputBridge.isServiceEnabled(target))
            screenshot("07-accessibility-disabled-no-bubble")
        } finally {
            setEnabledServices(listOf(serviceComponent))
            shell("settings put secure accessibility_enabled 1")
            waitFor("restored accessibility service") { main { AutoInputBridge.connected } }
        }
    }

    private fun verified(block: () -> Unit) {
        try { block() }
        catch (failure: Throwable) {
            // TestWatcher runs after @After; capture here while the failing field
            // still has its original focus, content and accessibility actions.
            try {
                fieldDiagnostics("test-failure-${testName.methodName}", failure)
                screenshot("test-failure-${testName.methodName}")
            } catch (diagnosticFailure: Throwable) { failure.addSuppressed(diagnosticFailure) }
            throw failure
        }
    }

    private fun fieldDiagnostics(name: String, failure: Throwable? = null) {
        val directory = File(target.getExternalFilesDir(null), "auto-input-tests").apply { mkdirs() }
        val state = main {
            val prefs = Prefs(target)
            "connected=${AutoInputBridge.connected}, eligible=${AutoInputBridge.eligible}, " +
                "keyboardTop=${AutoInputBridge.keyboardTop}, bubbleEnabled=${prefs.bubbleEnabled}, " +
                "autoInputEnabled=${prefs.autoInputEnabled}, dictationState=${DictationEvents.state}"
        }
        val fields = allNodes().filter { it.packageName?.toString() == fixturePackage && it.isEditable }
        val descriptions = fields.joinToString("\n") { node ->
            val secret = node.isPassword || !AutoInputPolicy.safeInputType(node.inputType) || node.isAccessibilityDataSensitive
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            "label=${node.contentDescription}, class=${node.className}, bounds=$bounds, " +
                "focused=${node.isFocused}, enabled=${node.isEnabled}, visible=${node.isVisibleToUser}, " +
                "editable=${node.isEditable}, password=${node.isPassword}, sensitive=${node.isAccessibilityDataSensitive}, " +
                "inputType=${node.inputType}, showingHint=${node.isShowingHintText}, " +
                "text=${if (secret) "<redacted>" else node.text}, hint=${if (secret) "<redacted>" else node.hintText}, " +
                "selection=${node.textSelectionStart},${node.textSelectionEnd}, " +
                "actionIds=${node.actionList.map { it.id }}"
        }
        File(directory, "$name-diagnostics.txt").writeText(
            "${failure?.let { "${it.javaClass.name}: ${it.message}\n" }.orEmpty()}" +
            "Bridge: $state\nService enabled=${AutoInputBridge.isServiceEnabled(target)}\n" +
            "Secure enabled services=${shell("settings get secure enabled_accessibility_services").trim()}\n" +
            "Editable fixture fields:\n$descriptions\n")
    }

    private fun launchFixture(clearTask: Boolean) {
        // Test-only shell launch waits for Android's activity-start result, then
        // the real accessibility destination. This avoids racing asynchronous Home
        // transitions and never retries a test or dismisses an app/system error.
        val flags = if (clearTask) "0x10008000" else "0x10000000"
        val result = shell("am start -W -n $fixturePackage/${AutoInputFixtureActivity::class.java.name} -f $flags")
        assertTrue("Android must launch the external fixture: $result", result.contains("Status: ok") && !result.contains("Error:"))
        waitFor("external native fixture visible after activity launch") { node("First field") != null }
    }

    private fun focus(label: String) {
        click(label)
        waitFor("$label focused and eligible") {
            node(label)?.isFocused == true && main { AutoInputBridge.eligible }
        }
    }

    private fun click(label: String) {
        val field = node(label) ?: throw AssertionError("Missing fixture control: $label")
        // Actual touch displays the system IME (ACTION_FOCUS alone need not do so).
        val bounds = Rect().also { field.getBoundsInScreen(it) }
        val now = SystemClock.uptimeMillis()
        listOf(android.view.MotionEvent.ACTION_DOWN, android.view.MotionEvent.ACTION_UP).forEach { action ->
            val event = android.view.MotionEvent.obtain(now, SystemClock.uptimeMillis(), action,
                bounds.centerX().toFloat(), bounds.centerY().toFloat(), 0)
            event.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            try { assertTrue(automation.injectInputEvent(event, true)) } finally { event.recycle() }
        }
    }

    private fun dragBubbleTowardKeyboard(start: Rect, keyboardTop: Int) {
        val downTime = SystemClock.uptimeMillis()
        val x = start.centerX().toFloat()
        val y = start.centerY().toFloat()
        val destinationY = (keyboardTop + 180).coerceAtMost(target.resources.displayMetrics.heightPixels - 30).toFloat()
        // Move beyond touch slop immediately so the hold-to-record timer is cancelled.
        // The real gesture stays well below the 400 ms hold threshold.
        val events = listOf(
            Triple(android.view.MotionEvent.ACTION_DOWN, y, 0L),
            Triple(android.view.MotionEvent.ACTION_MOVE, y + 60f, 20L),
            Triple(android.view.MotionEvent.ACTION_MOVE, destinationY, 40L),
            Triple(android.view.MotionEvent.ACTION_UP, destinationY, 60L),
        )
        events.forEach { (action, eventY, elapsed) ->
            val event = android.view.MotionEvent.obtain(downTime, downTime + elapsed, action, x, eventY, 0)
            event.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            try { assertTrue("Inject drag event $action", automation.injectInputEvent(event, action != android.view.MotionEvent.ACTION_DOWN && action != android.view.MotionEvent.ACTION_MOVE)) }
            finally { event.recycle() }
        }
    }

    private fun select(label: String, start: Int, end: Int) {
        assertTrue(node(label)!!.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, Bundle().apply {
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, start)
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, end)
        }))
        waitFor("selected range") { node(label)?.let { it.textSelectionStart == start && it.textSelectionEnd == end } == true }
    }

    private fun node(label: String): AccessibilityNodeInfo? = allNodes().firstOrNull {
        it.packageName?.toString() == fixturePackage && (it.contentDescription?.toString() == label || it.text?.toString() == label)
    }
    private fun bubble(): AccessibilityNodeInfo? = allNodes().firstOrNull {
        it.packageName?.toString() == target.packageName && it.viewIdResourceName?.endsWith(":id/bubble_touch_target") == true
    }
    private fun allNodes(): List<AccessibilityNodeInfo> {
        val nodes = mutableListOf<AccessibilityNodeInfo>()
        fun collect(node: AccessibilityNodeInfo?) {
            if (node == null) return
            nodes.add(node)
            for (index in 0 until node.childCount) collect(node.getChild(index))
        }
        automation.windows.forEach { collect(it.root) }
        return nodes
    }
    private fun assertNoResultPanel() {
        val flowNodes = allNodes().filter { it.packageName?.toString() == target.packageName }
        assertFalse("Automatic results must not expand Open Flow/Copy/Close panel", flowNodes.any {
            it.viewIdResourceName?.endsWith(":id/btn_bubble_insert") == true ||
                it.viewIdResourceName?.endsWith(":id/btn_bubble_copy") == true ||
                it.viewIdResourceName?.endsWith(":id/btn_bubble_close") == true
        })
    }
    private fun screenshot(name: String) {
        val directory = File(target.getExternalFilesDir(null), "auto-input-tests").apply { mkdirs() }
        val bitmap = automation.takeScreenshot() ?: throw AssertionError("Screenshot unavailable")
        try { FileOutputStream(File(directory, "$name.png")).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) } }
        finally { bitmap.recycle() }
        File(directory, "$name.txt").writeText(allNodes().joinToString("\n") {
            "${it.packageName} ${it.viewIdResourceName} ${it.contentDescription} ${if (it.isPassword) "<password>" else it.text}"
        })
    }
    private fun setEnabledServices(components: List<String>) {
        // UiAutomation runs Runtime.exec(String), not a shell: quote characters
        // would become literal setting data. Components contain no whitespace.
        assertTrue("Service component identifiers are safe plain arguments",
            components.all { it.matches(Regex("[A-Za-z0-9_.$/:]+")) })
        val value = components.joinToString(":")
        if (value.isEmpty()) shell("settings delete secure enabled_accessibility_services")
        else shell("settings put secure enabled_accessibility_services $value")
        val expected = value.ifEmpty { "null" }
        waitFor("exact enabled-services setting readback ($expected)") {
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
        val deadline = SystemClock.uptimeMillis() + 10000
        while (SystemClock.uptimeMillis() < deadline) {
            if (predicate()) return
            SystemClock.sleep(100)
        }
        throw AssertionError("Timed out: $description")
    }
}
