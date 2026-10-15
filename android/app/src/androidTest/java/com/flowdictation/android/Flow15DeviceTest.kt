package com.flowdictation.android

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Rect
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.provider.MediaStore
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.RadioButton
import android.widget.ScrollView
import androidx.appcompat.app.AppCompatDelegate
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.slider.Slider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.CopyOnWriteArrayList

/** Native UX regression checks for the Flow 1.5 Android refinement. */
class Flow15DeviceTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val target get() = instrumentation.targetContext
    private val shared get() = target.getSharedPreferences("flow_dictation", Context.MODE_PRIVATE)

    @Test
    fun lightIsFreshInstallDefaultAndThemeChoicePersists() {
        val hadTheme = shared.contains("theme_mode")
        val oldTheme = shared.getString("theme_mode", null)
        val oldNightMode = AppCompatDelegate.getDefaultNightMode()
        val oldSystemNight = shell("cmd uimode night")
        var screen: SettingsActivity? = null
        try {
            shell("cmd uimode night yes")
            shared.edit().remove("theme_mode").commit()
            val fresh = launchSettings().also { screen = it }
            capture("settings-light")
            assertEquals("A fresh install starts light even when Android is dark", Prefs.THEME_MODE_LIGHT, Prefs(target).themeMode)
            assertEquals(AppCompatDelegate.MODE_NIGHT_NO, AppCompatDelegate.getDefaultNightMode())
            assertFalse(isNight(fresh.resources.configuration.uiMode))
            val lightWindowFlags = fresh.window.decorView.systemUiVisibility
            assertTrue("Light theme requests dark status bar icons", lightWindowFlags and View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR != 0)
            assertTrue("Light theme requests dark navigation bar icons", lightWindowFlags and View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR != 0)
            assertTrue("Light is selected on first launch", fresh.findViewById<RadioButton>(R.id.theme_light).isChecked)
            fresh.finish()
            instrumentation.waitForIdleSync()

            listOf(
                Triple(R.id.theme_light, Prefs.THEME_MODE_LIGHT, AppCompatDelegate.MODE_NIGHT_NO),
                Triple(R.id.theme_dark, Prefs.THEME_MODE_DARK, AppCompatDelegate.MODE_NIGHT_YES),
                Triple(R.id.theme_system, Prefs.THEME_MODE_SYSTEM, AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM),
            ).forEach { (id, preference, delegateMode) ->
                val current = launchSettings().also { screen = it }
                val choice = current.findViewById<RadioButton>(id)
                instrumentation.runOnMainSync { choice.performClick() }
                waitUntil("${preference} theme is saved") {
                    Prefs(target).themeMode == preference && AppCompatDelegate.getDefaultNightMode() == delegateMode
                }
                current.finish()
                instrumentation.waitForIdleSync()
                val reopened = launchSettings().also { screen = it }
                assertEquals("Theme survives opening Settings again", preference, Prefs(target).themeMode)
                assertTrue("The saved theme remains selected", reopened.findViewById<RadioButton>(id).isChecked)
                if (preference == Prefs.THEME_MODE_DARK) capture("settings-dark")
                reopened.finish()
                instrumentation.waitForIdleSync()
            }
        } finally {
            screen?.finish()
            if (hadTheme) shared.edit().putString("theme_mode", oldTheme).commit()
            else shared.edit().remove("theme_mode").commit()
            restoreNightMode(oldSystemNight)
            AppCompatDelegate.setDefaultNightMode(oldNightMode)
        }
    }

    @Test
    fun processingFeedbackAndMainControlsRemainAccessibleAtDoubleFontScale() {
        val oldFont = shell("settings get system font_scale").trim()
        assertEquals("The isolated UI test starts with no active dictation", DictState.IDLE, DictationEvents.state)
        var main: MainActivity? = null
        var settings: SettingsActivity? = null
        var bubbleSettings: Activity? = null
        val controlsPrefs = BubbleControlsPrefs(target)
        val oldDoubleTap = controlsPrefs.doubleTapAction
        try {
            shell("settings put system font_scale 1.0")
            val normalMain = instrumentation.startActivitySync(
                Intent(target, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            ) as MainActivity
            main = normalMain
            instrumentation.waitForIdleSync()
            assertTrue("The ready screen capture uses the default font scale", normalMain.resources.configuration.fontScale < 1.2f)
            capture("main-idle-normal")
            normalMain.finish()
            instrumentation.waitForIdleSync()

            shell("settings put system font_scale 2.0")
            val activeMain = instrumentation.startActivitySync(
                Intent(target, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            ) as MainActivity
            main = activeMain
            instrumentation.waitForIdleSync()
            assertTrue("Main screen uses the requested 200% font scale", activeMain.resources.configuration.fontScale >= 1.9f)
            capture("main-idle")
            val editor = activeMain.findViewById<android.widget.EditText>(R.id.transcript_editor)
            instrumentation.runOnMainSync { editor.setText("Keep this draft while processing") }

            DictationEvents.emitState(DictState.PREPARING)
            instrumentation.waitForIdleSync()
            assertEquals(View.VISIBLE, activeMain.findViewById<View>(R.id.processing_progress).visibility)
            assertEquals(View.GONE, activeMain.findViewById<View>(R.id.record_level).visibility)
            DictationEvents.emitState(DictState.RECORDING)
            instrumentation.waitForIdleSync()
            val mainLevel = activeMain.findViewById<android.widget.ProgressBar>(R.id.record_level)
            assertEquals(View.VISIBLE, mainLevel.visibility)
            scrollToView(findScrollView(activeMain.window.decorView)!!, mainLevel)
            capture("main-listening")
            DictationEvents.emitLevel(0.42f)
            instrumentation.waitForIdleSync()
            assertEquals("The synthetic level reaches the live meter", 42, mainLevel.progress)
            DictationEvents.emitState(DictState.TRANSCRIBING)
            instrumentation.waitForIdleSync()
            assertEquals(View.VISIBLE, activeMain.findViewById<View>(R.id.processing_progress).visibility)
            assertEquals(View.GONE, mainLevel.visibility)
            scrollToView(findScrollView(activeMain.window.decorView)!!, activeMain.findViewById(R.id.processing_detail))
            capture("main-transcribing")
            assertEquals("Keep this draft while processing", editor.text.toString())
            assertTrue(activeMain.findViewById<View>(R.id.processing_detail).visibility == View.VISIBLE)

            val mainScroll = findScrollView(activeMain.window.decorView)
            assertNotNull("The main screen should scroll when text is enlarged", mainScroll)
            assertInteractiveControlsReachable(mainScroll!!, activeMain.window.decorView)
            val recordButton = activeMain.findViewById<View>(R.id.btn_talk)
            assertTrue("The main action keeps a comfortable touch height", recordButton.height >= dp(48))

            DictationEvents.emitState(DictState.IDLE)
            instrumentation.waitForIdleSync()
            activeMain.finish()
            instrumentation.waitForIdleSync()
            val activeSettings = launchSettings().also { settings = it }
            assertTrue("Settings uses the requested 200% font scale", activeSettings.resources.configuration.fontScale >= 1.9f)
            val settingsScroll = findScrollView(activeSettings.window.decorView)
            assertNotNull("Settings should scroll at 200% font size", settingsScroll)
            assertInteractiveControlsReachable(settingsScroll!!, activeSettings.window.decorView)
            instrumentation.runOnMainSync { activeSettings.findViewById<Button>(R.id.bubble_controls).performClick() }
            instrumentation.waitForIdleSync()
            waitUntil("floating-button settings opens") { currentResumedActivity() is BubbleControlsActivity }
            bubbleSettings = currentResumedActivity()
            assertTrue("The dedicated floating-button settings open", bubbleSettings is BubbleControlsActivity)
            assertTrue("Floating-button settings uses the requested 200% font scale", bubbleSettings!!.resources.configuration.fontScale >= 1.9f)
            val sizeSlider = bubbleSettings?.let { findByContentDescription(it, "Floating button visible size") }
            assertNotNull("The size control is available on its dedicated page", sizeSlider)
            assertEquals("The visible-size control supports 32dp", BubbleSizePolicy.MIN_DP.toFloat(), (sizeSlider as Slider).valueFrom, 0.01f)
            assertEquals("The visible-size control supports 160dp", BubbleSizePolicy.MAX_DP.toFloat(), sizeSlider.valueTo, 0.01f)
            capture("bubble-controls-200")
            val bubbleScroll = bubbleSettings?.let { findScrollView(it.window.decorView) }
            assertNotNull("Floating-button settings remain scrollable at 200%", bubbleScroll)
            assertInteractiveControlsReachable(bubbleScroll!!, bubbleSettings!!.window.decorView)
            clickTextOnPage(bubbleSettings!!, "Do nothing")
            assertTrue("The double-tap action chooser opens", waitUntilText("Double tap action", 5_000))
            clickText("Open Flow")
            assertEquals("A chosen tap mapping is saved", BubbleGestureAction.OPEN_FLOW, controlsPrefs.doubleTapAction)
        } finally {
            DictationEvents.emitState(DictState.IDLE)
            main?.finish()
            settings?.finish()
            bubbleSettings?.finish()
            controlsPrefs.doubleTapAction = oldDoubleTap
            instrumentation.waitForIdleSync()
            restoreSetting("settings get system font_scale", "settings put system font_scale", oldFont)
        }
    }

    @Test
    fun overlayTripleTapPinchAndRecordingStopUseRealTouchDispatch() {
        val controls = BubbleControlsPrefs(target)
        val oldSize = controls.bubbleSizeDp
        val oldLong = controls.longPressAction
        val oldDouble = controls.doubleTapAction
        val oldTriple = controls.tripleTapAction
        val oldAppOp = shell("cmd appops get ${target.packageName} SYSTEM_ALERT_WINDOW").trim()
        assertEquals("The isolated UI test starts with no active dictation", DictState.IDLE, DictationEvents.state)
        val recorder = RecordingContext(target)
        var manager: BubbleManager? = null
        try {
            shell("cmd appops set ${target.packageName} SYSTEM_ALERT_WINDOW allow")
            controls.bubbleSizeDp = 32
            controls.longPressAction = BubbleGestureAction.HOLD_TO_TALK
            controls.doubleTapAction = BubbleGestureAction.NONE
            controls.tripleTapAction = BubbleGestureAction.RESIZE
            DictationEvents.emitState(DictState.IDLE)
            instrumentation.runOnMainSync {
                manager = BubbleManager(recorder)
                assertTrue("The test overlay should be allowed to appear", manager!!.show())
            }
            instrumentation.waitForIdleSync()
            capture("overlay-idle")
            val bubble = requireNotNull(manager)
            val targetView = field<View>(bubble, "touchTarget")
            val visibleMic = field<View>(bubble, "micButton")
            val resizeHint = field<View>(bubble, "resizeHint")
            assertEquals(dp(32), visibleMic.width)
            assertTrue("A small visible button retains a 48dp hit area", targetView.width >= dp(48))
            assertEquals("No resize affordance is permanently shown", View.GONE, resizeHint.visibility)
            val resizeHandleId = target.resources.getIdentifier("bubble_resize_handle", "id", target.packageName)
            assertFalse("Idle display has no permanent resize handle", resizeHandleId != 0 && hasViewId(targetView, resizeHandleId))

            tripleTap(targetView)
            waitUntil("triple tap opens pinch mode") { field<Boolean>(bubble, "resizeMode") }
            capture("overlay-resize")
            assertEquals("An idle resize gesture must not start dictation", DictState.IDLE, DictationEvents.state)
            assertTrue("Resize mode explains the temporary gesture", resizeHint.visibility == View.VISIBLE)

            val beforeCancel = controls.bubbleSizeDp
            pinch(targetView, cancel = true)
            instrumentation.waitForIdleSync()
            assertEquals("Canceling a pinch does not save the preview", beforeCancel, controls.bubbleSizeDp)
            assertTrue(recorder.actions.isEmpty())

            tripleTap(targetView) {
                assertFalse(
                    "Canceling a pinch exits resize mode before another gesture; ${touchTargetDiagnostic(targetView)}",
                    field<Boolean>(bubble, "resizeMode"),
                )
            }
            waitUntil("a second triple tap reopens pinch mode") { field<Boolean>(bubble, "resizeMode") }
            pinch(targetView, cancel = false)
            instrumentation.waitForIdleSync()
            assertTrue("A completed pinch changes the saved size", controls.bubbleSizeDp > beforeCancel)
            assertTrue("Size is clamped to the supported range", controls.bubbleSizeDp in 32..160)
            assertTrue(recorder.actions.isEmpty())

            // DictationEvents is the synthetic state source. The service start is intercepted,
            // so the test proves UI dispatch and command intent without opening the microphone.
            DictationEvents.emitState(DictState.RECORDING)
            instrumentation.waitForIdleSync()
            capture("overlay-recording")
            val waveform = field<View>(bubble, "waveform")
            DictationEvents.emitLevel(0.08f)
            SystemClock.sleep(180)
            val quietFrame = draw(waveform)
            DictationEvents.emitLevel(0.95f)
            SystemClock.sleep(180)
            val loudFrame = draw(waveform)
            assertFalse("Injected level events change the actual waveform canvas", samePixels(quietFrame, loudFrame))

            DictationEvents.emitState(DictState.TRANSCRIBING)
            instrumentation.waitForIdleSync()
            val bubbleStatus = field<android.widget.TextView>(bubble, "statusLabel")
            assertTrue("The bubble names transcription instead of showing a made-up percentage",
                bubbleStatus.text.toString().startsWith("Transcribing") && !bubbleStatus.text.toString().contains("%"))
            assertEquals("Processing indicator remains visible while text is pending", View.VISIBLE, waveform.visibility)
            capture("overlay-transcribing")

            DictationEvents.emitState(DictState.RECORDING)
            instrumentation.waitForIdleSync()
            tap(targetView)
            waitUntil("a recording tap sends Stop immediately") {
                recorder.actions.lastOrNull() == DictationService.ACTION_STOP
            }
            val stopCount = recorder.actions.count { it == DictationService.ACTION_STOP }
            tap(targetView)
            tap(targetView)
            SystemClock.sleep(120)
            assertEquals("A rapid follow-up tap burst cannot issue another Stop", stopCount,
                recorder.actions.count { it == DictationService.ACTION_STOP })
            assertFalse("The intercepted test never starts microphone capture", recorder.actions.contains(DictationService.ACTION_START))
        } finally {
            instrumentation.runOnMainSync { manager?.hide() }
            DictationEvents.emitState(DictState.IDLE)
            instrumentation.waitForIdleSync()
            controls.bubbleSizeDp = oldSize
            controls.longPressAction = oldLong
            controls.doubleTapAction = oldDouble
            controls.tripleTapAction = oldTriple
            restoreAppOp(oldAppOp)
        }
    }

    @Test
    fun wisprImportPickerPreviewsAndConfirmsOnlySyntheticFixture() {
        val word = "Flow15TestNorthStar"
        val alias = "flow fifteen test north star"
        val store = VocabularyStore(target)
        val fileName = "flow15-synthetic-${SystemClock.uptimeMillis()}.json"
        val json = """{"format":"flow-dictation-wispr-dictionary","version":1,"entries":[{"phrase":"$word","replacement":null},{"phrase":"$alias","replacement":"$word"}]}"""
        val uri = createSyntheticDownload(fileName, json)
        val wordWasAbsent = store.load().none { it.term.equals(word, true) }
        val oldFont = shell("settings get system font_scale").trim()
        var activity: Activity? = null
        var vocabulary: Activity? = null
        try {
            closeDocumentPickerIfOpen()
            assertTrue("Synthetic terms are unique before the test", wordWasAbsent)
            shell("settings put system font_scale 2.0")
            vocabulary = instrumentation.startActivitySync(
                Intent(target, VocabularyActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            ) as VocabularyActivity
            clickTextOnPage(vocabulary!!, target.getString(R.string.wispr_import_button))
            waitUntil("the Wispr import page opens") { currentResumedActivity() is WisprDictionaryImportActivity }
            activity = currentResumedActivity()
            assertTrue("Wispr import uses the requested 200% font scale", activity!!.resources.configuration.fontScale >= 1.9f)
            clickTextOnPage(activity!!, target.getString(R.string.wispr_import_choose))
            assertTrue("The system document picker opens", waitUntilText("Show roots", 8_000))
            clickText("Show roots")
            assertTrue("The document picker locations drawer opens", waitForCondition(8_000) { documentPickerDrawerList() != null })
            tapDownloadsInPickerDrawer("initial selection")
            assertTrue("The Downloads drawer closes after selection", waitForCondition(8_000) { !documentPickerDrawerIsOpen() })
            val fileVisibleAfterFirstSelection = waitForCondition(8_000) {
                !documentPickerDrawerIsOpen() && visibleDocumentPickerNode(fileName) != null
            }
            if (!fileVisibleAfterFirstSelection) {
                capture("import-after-initial-download-selection")
                saveAccessibilityHierarchy("import-after-initial-download-selection")
            }
            assertTrue("Downloads finishes opening and shows the exact synthetic file", fileVisibleAfterFirstSelection)

            clickText("Show roots")
            assertTrue("The document picker locations drawer reopens", waitForCondition(8_000) { documentPickerDrawerList() != null })
            val duplicateLabelsReady = waitForCondition(8_000) { documentPickerHasDuplicateDownloadsLabels() }
            if (!duplicateLabelsReady) {
                capture("import-duplicate-download-labels-missing")
                saveAccessibilityHierarchy("import-duplicate-download-labels-missing")
            }
            assertTrue(
                "The current Downloads breadcrumb and drawer row are both present",
                duplicateLabelsReady,
            )
            tapDownloadsInPickerDrawer("duplicate-label regression")
            val drawerClosed = waitForCondition(8_000) { !documentPickerDrawerIsOpen() }
            if (!drawerClosed) {
                capture("import-drawer-did-not-close")
                saveAccessibilityHierarchy("import-drawer-did-not-close")
            }
            assertTrue("The explicitly selected Downloads drawer row closes the drawer", drawerClosed)
            val fileReadyForTap = waitForCondition(8_000) {
                val file = visibleDocumentPickerNode(fileName)
                !documentPickerDrawerIsOpen() && file != null
            }
            if (!fileReadyForTap) {
                capture("import-before-file-tap-failure")
                saveAccessibilityHierarchy("import-before-file-tap-failure")
            }
            assertTrue("The exact synthetic file is visible after the drawer closes", fileReadyForTap)
            tapVisibleText(fileName)

            val preview = target.getString(R.string.wispr_import_preview_counts, 2, 1, 1, 0, 0)
            var verifiedOpenAction: AccessibilityNodeInfo? = null
            val pickerProgressed = waitForCondition(8_000) {
                if (isWisprImportActivityActive()) true
                else {
                    verifiedOpenAction = selectedDocumentPickerOpenAction(fileName)
                    verifiedOpenAction != null
                }
            }
            if (!pickerProgressed) {
                capture("import-picker-after-file-tap")
                saveAccessibilityHierarchy("import-picker-after-file-tap")
            }
            assertTrue("The picker opens the selected file or presents an enabled Open action", pickerProgressed)

            if (!isWisprImportActivityActive()) {
                capture("import-picker-selected-file")
                saveAccessibilityHierarchy("import-picker-selected-file")
                verifiedOpenAction = selectedDocumentPickerOpenAction(fileName)
                assertNotNull("The selected synthetic file still has a visible enabled Open action", verifiedOpenAction)
                assertTrue(
                    "The visible enabled Open action opens the selected synthetic file",
                    verifiedOpenAction!!.performAction(AccessibilityNodeInfo.ACTION_CLICK),
                )
            }

            val returnedToImport = waitForCondition(8_000) { isWisprImportActivityActive() }
            if (!returnedToImport) {
                capture("import-picker-return-failure")
                saveAccessibilityHierarchy("import-picker-return-failure")
            }
            assertTrue("The document picker returns to the Wispr import page", returnedToImport)
            val previewVisible = waitUntilText(preview, 8_000)
            if (!previewVisible) {
                capture("import-preview-failure-200")
                saveAccessibilityHierarchy("import-preview-failure-200")
            }
            assertTrue("Preview shows two entries, one word and one correction", previewVisible)
            capture("import-preview-200")
            clickTextOnPage(activity!!, target.getString(R.string.wispr_import_confirm, 1, 1))
            capture("import-confirm-200")
            assertTrue("The import asks for explicit confirmation", waitUntilText(target.getString(R.string.wispr_import_confirm_title), 5_000))
            clickText(target.getString(R.string.wispr_import_confirm_action))
            waitUntil("synthetic dictionary entries are saved") {
                store.load().any { it.term == word && it.aliases.contains(alias) }
            }
        } finally {
            try {
                closeDocumentPickerIfOpen()
                activity?.finish()
                vocabulary?.finish()
                if (wordWasAbsent) store.delete(word)
                target.contentResolver.delete(uri, null, null)
                instrumentation.waitForIdleSync()
            } finally {
                restoreSetting("settings get system font_scale", "settings put system font_scale", oldFont)
            }
        }
    }

    private fun launchSettings(): SettingsActivity {
        val activity = instrumentation.startActivitySync(
            Intent(target, SettingsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        ) as SettingsActivity
        instrumentation.waitForIdleSync()
        return activity
    }

    private fun isNight(uiMode: Int) =
        (uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK) == android.content.res.Configuration.UI_MODE_NIGHT_YES

    private fun restoreNightMode(old: String) {
        when {
            old.contains("yes", true) -> shell("cmd uimode night yes")
            old.contains("no", true) -> shell("cmd uimode night no")
            else -> shell("cmd uimode night auto")
        }
    }

    private fun restoreSetting(get: String, put: String, old: String) {
        if (old.isBlank() || old == "null") shell(get.replace(" get ", " delete "))
        else shell("$put $old")
    }

    private fun assertReachable(scroll: ScrollView, view: View) {
        instrumentation.runOnMainSync {
            val bounds = Rect()
            view.getDrawingRect(bounds)
            scroll.offsetDescendantRectToMyCoords(view, bounds)
            scroll.scrollTo(0, bounds.top)
        }
        instrumentation.waitForIdleSync()
        val visible = Rect()
        val label = view.contentDescription?.toString()
            ?: runCatching { if (view.id != View.NO_ID) target.resources.getResourceEntryName(view.id) else null }.getOrNull()
            ?: (view as? android.widget.TextView)?.text?.toString()
            ?: view.javaClass.simpleName
        assertTrue("$label stays reachable by scrolling", view.getGlobalVisibleRect(visible))
        assertTrue("$label keeps at least a 48dp touch target at large font", view.height >= dp(48))
    }

    private fun scrollToView(scroll: ScrollView, view: View) {
        instrumentation.runOnMainSync {
            val bounds = Rect()
            view.getDrawingRect(bounds)
            scroll.offsetDescendantRectToMyCoords(view, bounds)
            scroll.scrollTo(0, bounds.top.coerceAtLeast(0))
        }
        instrumentation.waitForIdleSync()
    }

    private fun assertInteractiveControlsReachable(scroll: ScrollView, root: View) {
        fun inspect(view: View) {
            if (view.visibility == View.VISIBLE && (view is Button || view is RadioButton ||
                    view is android.widget.CompoundButton || view is Slider || view is android.widget.EditText)
            ) assertReachable(scroll, view)
            if (view is ViewGroup) for (index in 0 until view.childCount) inspect(view.getChildAt(index))
        }
        inspect(root)
    }

    private fun findScrollView(view: View): ScrollView? {
        if (view is ScrollView) return view
        if (view is ViewGroup) for (index in 0 until view.childCount) findScrollView(view.getChildAt(index))?.let { return it }
        return null
    }

    private fun findByContentDescription(activity: Activity, description: String): View? {
        var found: View? = null
        fun visit(view: View) {
            if (view.contentDescription?.toString() == description) found = view
            if (view is ViewGroup) for (index in 0 until view.childCount) visit(view.getChildAt(index))
        }
        visit(activity.window.decorView)
        return found
    }

    private fun tap(view: View) {
        val location = IntArray(2)
        instrumentation.runOnMainSync { view.getLocationOnScreen(location) }
        val x = location[0] + view.width / 2f
        val y = location[1] + view.height / 2f
        val down = SystemClock.uptimeMillis()
        injectGestureEvent(view, "tap down", MotionEvent.obtain(down, down, MotionEvent.ACTION_DOWN, x, y, 0))
        SystemClock.sleep(40)
        injectGestureEvent(
            view,
            "tap up",
            MotionEvent.obtain(down, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, x, y, 0),
        )
    }

    private fun tripleTap(view: View, afterGeometrySettles: () -> Unit = {}) {
        awaitStableTouchTarget(view, "Touch target settles before triple tap")
        afterGeometrySettles()
        repeat(3) {
            tap(view)
            if (it < 2) SystemClock.sleep(30)
        }
    }

    private fun pinch(view: View, cancel: Boolean) {
        val location = IntArray(2)
        instrumentation.runOnMainSync { view.getLocationOnScreen(location) }
        val centerX = location[0] + view.width / 2f
        val centerY = location[1] + view.height / 2f
        val downTime = SystemClock.uptimeMillis()
        val first = point(0, centerX - dp(10), centerY)
        val second = point(1, centerX + dp(10), centerY)
        injectGestureEvent(view, "pinch down", pointerEvent(downTime, SystemClock.uptimeMillis(), MotionEvent.ACTION_DOWN, listOf(first)))
        SystemClock.sleep(40)
        injectGestureEvent(
            view,
            "pinch pointer down",
            pointerEvent(
                downTime,
                SystemClock.uptimeMillis(),
                MotionEvent.ACTION_POINTER_DOWN or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT),
                listOf(first, second),
            ),
        )
        SystemClock.sleep(60)
        val moved = listOf(point(0, centerX - dp(40), centerY), point(1, centerX + dp(40), centerY))
        injectGestureEvent(view, "pinch move", pointerEvent(downTime, SystemClock.uptimeMillis(), MotionEvent.ACTION_MOVE, moved))
        if (cancel) {
            SystemClock.sleep(20)
            injectGestureEvent(view, "pinch cancel", pointerEvent(downTime, SystemClock.uptimeMillis(), MotionEvent.ACTION_CANCEL, moved))
        } else {
            SystemClock.sleep(30)
            injectGestureEvent(
                view,
                "pinch pointer up",
                pointerEvent(
                    downTime,
                    SystemClock.uptimeMillis(),
                    MotionEvent.ACTION_POINTER_UP or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT),
                    moved,
                ),
            )
            SystemClock.sleep(30)
            injectGestureEvent(
                view,
                "pinch up",
                pointerEvent(downTime, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, listOf(moved[0])),
            )
        }
    }

    private data class TouchTargetGeometry(
        val left: Int,
        val top: Int,
        val width: Int,
        val height: Int,
        val layoutWidth: Int,
        val layoutHeight: Int,
        val attached: Boolean,
        val shown: Boolean,
        val layoutRequested: Boolean,
    ) {
        val ready: Boolean
            get() = attached && shown && !layoutRequested && width > 0 && height > 0 &&
                width == layoutWidth && height == layoutHeight

        fun sameScreenBounds(other: TouchTargetGeometry): Boolean =
            left == other.left && top == other.top && width == other.width && height == other.height
    }

    private fun awaitStableTouchTarget(view: View, description: String) {
        val startedAt = SystemClock.uptimeMillis()
        val deadline = startedAt + 5_000
        var previous: TouchTargetGeometry? = null
        var stableSamples = 0
        var last = "no geometry sample"
        while (SystemClock.uptimeMillis() < deadline) {
            val remaining = (deadline - SystemClock.uptimeMillis()).coerceAtLeast(1L)
            try {
                instrumentation.uiAutomation.waitForIdle(100, remaining)
            } catch (error: Exception) {
                throw AssertionError(
                    "$description: UiAutomation did not become idle; elapsed=${SystemClock.uptimeMillis() - startedAt}ms; " +
                        "target=${touchTargetDiagnostic(view)}; state=${DictationEvents.state}",
                ).apply { initCause(error) }
            }
            val current = touchTargetGeometry(view)
            last = current.toString()
            stableSamples = if (current.ready && previous?.sameScreenBounds(current) == true) stableSamples + 1 else 0
            if (stableSamples >= 2) return
            previous = current
        }
        throw AssertionError(
            "$description: target geometry did not settle in ${SystemClock.uptimeMillis() - startedAt}ms; " +
                "last=$last; state=${DictationEvents.state}",
        )
    }

    private fun touchTargetGeometry(view: View): TouchTargetGeometry {
        var geometry: TouchTargetGeometry? = null
        instrumentation.runOnMainSync {
            val location = IntArray(2)
            view.getLocationOnScreen(location)
            val layout = view.layoutParams
            geometry = TouchTargetGeometry(
                left = location[0],
                top = location[1],
                width = view.width,
                height = view.height,
                layoutWidth = layout?.width ?: -1,
                layoutHeight = layout?.height ?: -1,
                attached = view.isAttachedToWindow,
                shown = view.isShown,
                layoutRequested = view.isLayoutRequested,
            )
        }
        return requireNotNull(geometry)
    }

    private fun touchTargetDiagnostic(view: View): String =
        "uptime=${SystemClock.uptimeMillis()}ms; geometry=${touchTargetGeometry(view)}; state=${DictationEvents.state}"

    private fun injectGestureEvent(view: View, gesture: String, event: MotionEvent) {
        val action = MotionEvent.actionToString(event.action)
        val eventTime = event.eventTime
        val downTime = event.downTime
        if (!inject(event)) {
            throw AssertionError(
                "Could not inject $gesture; event=$action eventTime=${eventTime} downTime=$downTime; " +
                    touchTargetDiagnostic(view),
            )
        }
    }

    private fun point(id: Int, x: Float, y: Float): Pointer = Pointer(id, x, y)

    private data class Pointer(val id: Int, val x: Float, val y: Float)

    private fun pointerEvent(down: Long, time: Long, action: Int, points: List<Pointer>): MotionEvent {
        val properties = Array(points.size) { index ->
            MotionEvent.PointerProperties().apply { id = points[index].id; toolType = MotionEvent.TOOL_TYPE_FINGER }
        }
        val coordinates = Array(points.size) { index ->
            MotionEvent.PointerCoords().apply {
                x = points[index].x; y = points[index].y; pressure = 1f; size = 1f
            }
        }
        return MotionEvent.obtain(down, time, action, points.size, properties, coordinates, 0, 0,
            1f, 1f, 0, 0, android.view.InputDevice.SOURCE_TOUCHSCREEN, 0)
    }

    private fun inject(event: MotionEvent): Boolean {
        return try {
            event.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            instrumentation.uiAutomation.injectInputEvent(event, true)
        } finally {
            event.recycle()
        }
    }

    private fun <T> field(instance: Any, name: String): T {
        val field = instance.javaClass.getDeclaredField(name).apply { isAccessible = true }
        @Suppress("UNCHECKED_CAST")
        return field.get(instance) as T
    }

    private fun hasViewId(root: View, id: Int): Boolean {
        if (root.id == id) return true
        if (root is ViewGroup) for (index in 0 until root.childCount) if (hasViewId(root.getChildAt(index), id)) return true
        return false
    }

    private fun draw(view: View): Bitmap {
        val bitmap = Bitmap.createBitmap(view.width.coerceAtLeast(1), view.height.coerceAtLeast(1), Bitmap.Config.ARGB_8888)
        instrumentation.runOnMainSync { view.draw(Canvas(bitmap)) }
        return bitmap
    }

    private fun samePixels(first: Bitmap, second: Bitmap): Boolean {
        if (first.width != second.width || first.height != second.height) return false
        val a = IntArray(first.width * first.height)
        val b = IntArray(second.width * second.height)
        first.getPixels(a, 0, first.width, 0, 0, first.width, first.height)
        second.getPixels(b, 0, second.width, 0, 0, second.width, second.height)
        return a.contentEquals(b)
    }

    private fun createSyntheticDownload(name: String, json: String): Uri {
        val values = android.content.ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
            if (android.os.Build.VERSION.SDK_INT >= 29) put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/")
        }
        val uri = target.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw AssertionError("Could not create the synthetic dictionary fixture")
        target.contentResolver.openOutputStream(uri)?.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            ?: throw AssertionError("Could not write the synthetic dictionary fixture")
        return uri
    }

    private fun clickText(text: String) {
        val firstNode = waitForNode(text, 8_000) ?: throw AssertionError("Could not find native UI text: $text")
        val bounds = Rect().also(firstNode::getBoundsInScreen)
        var node: AccessibilityNodeInfo? = firstNode
        var activated = false
        while (node != null && !activated) {
            val current = node
            activated = current.isEnabled && current.isClickable && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            node = current.parent
        }
        if (!activated && !bounds.isEmpty) {
            tapAt(bounds.exactCenterX(), bounds.exactCenterY())
            activated = true
        }
        assertTrue("Could not activate native UI text or its row: $text", activated)
        instrumentation.waitForIdleSync()
    }

    private fun tapAt(x: Float, y: Float) {
        val down = SystemClock.uptimeMillis()
        inject(MotionEvent.obtain(down, down, MotionEvent.ACTION_DOWN, x, y, 0))
        inject(MotionEvent.obtain(down, down + 40, MotionEvent.ACTION_UP, x, y, 0))
    }

    private fun closeDocumentPickerIfOpen() {
        repeat(2) {
            if (!isDocumentPickerPackage(activeWindowPackage())) return
            shell("input keyevent 4")
            instrumentation.waitForIdleSync()
        }
    }

    private fun capture(name: String) {
        if (InstrumentationRegistry.getArguments().getString("flow15Screens") != "true") return
        instrumentation.waitForIdleSync()
        SystemClock.sleep(200)
        val directory = File(target.getExternalFilesDir(null), "flow15-ux-review")
        if (!directory.exists() && !directory.mkdirs()) throw AssertionError("Could not create screenshot output folder")
        val screenshot = instrumentation.uiAutomation.takeScreenshot()
            ?: throw AssertionError("Could not capture $name")
        FileOutputStream(File(directory, "$name.png")).use { output ->
            if (!screenshot.compress(Bitmap.CompressFormat.PNG, 100, output)) throw AssertionError("Could not save $name")
        }
        screenshot.recycle()
    }

    private fun clickTextOnPage(activity: Activity, text: String) {
        val targetView = findTextView(activity.window.decorView, text)
        if (targetView != null) {
            instrumentation.runOnMainSync {
                targetView.requestRectangleOnScreen(Rect(0, 0, targetView.width, targetView.height), true)
            }
            instrumentation.waitForIdleSync()
            tap(targetView)
            return
        }
        clickText(text)
    }

    private fun findTextView(root: View, text: String): android.widget.TextView? {
        if (root is android.widget.TextView && root.text?.toString() == text) return root
        if (root is ViewGroup) for (index in 0 until root.childCount) findTextView(root.getChildAt(index), text)?.let { return it }
        return null
    }

    private fun waitUntilText(text: String, timeoutMs: Long): Boolean = waitForNode(text, timeoutMs) != null

    private fun waitForCondition(timeoutMs: Long, condition: () -> Boolean): Boolean {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        while (SystemClock.uptimeMillis() < deadline) {
            if (condition()) return true
            SystemClock.sleep(100)
        }
        return condition()
    }

    private fun activeWindowPackage(): String? =
        instrumentation.uiAutomation.rootInActiveWindow?.packageName?.toString()

    private fun isDocumentPickerPackage(packageName: String?): Boolean =
        packageName == "com.android.documentsui" || packageName == "com.google.android.documentsui"

    private fun isWisprImportActivityActive(): Boolean =
        activeWindowPackage() == target.packageName && currentResumedActivity() is WisprDictionaryImportActivity

    private fun findAccessibilityNode(
        root: AccessibilityNodeInfo,
        predicate: (AccessibilityNodeInfo) -> Boolean,
    ): AccessibilityNodeInfo? {
        if (predicate(root)) return root
        for (index in 0 until root.childCount) {
            root.getChild(index)?.let { findAccessibilityNode(it, predicate)?.let { found -> return found } }
        }
        return null
    }

    private fun findAccessibilityNodes(
        root: AccessibilityNodeInfo,
        predicate: (AccessibilityNodeInfo) -> Boolean,
    ): List<AccessibilityNodeInfo> {
        val matches = mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo) {
            if (predicate(node)) matches += node
            for (index in 0 until node.childCount) node.getChild(index)?.let(::visit)
        }
        visit(root)
        return matches
    }

    private fun documentPickerDrawerList(): AccessibilityNodeInfo? {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return null
        return findDocumentPickerDrawerList(root)
    }

    private fun findDocumentPickerDrawerList(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (!isDocumentPickerPackage(root.packageName?.toString())) return null
        val openFromVisible = findAccessibilityNode(root) {
            it.text?.toString() == "Open from" && it.isVisibleToUser
        } != null
        if (!openFromVisible) return null
        return findAccessibilityNodes(root) {
            it.className?.toString() == "android.widget.ListView" && it.isVisibleToUser
        }.firstOrNull { list ->
            findAccessibilityNode(list) { it.text?.toString() == "Downloads" && it.isVisibleToUser } != null
        }
    }

    private fun documentPickerDrawerIsOpen(): Boolean = documentPickerDrawerList() != null

    private fun documentPickerHasDuplicateDownloadsLabels(): Boolean {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return false
        if (!isDocumentPickerPackage(root.packageName?.toString())) return false
        val drawer = findDocumentPickerDrawerList(root) ?: return false
        val visibleDownloads = findAccessibilityNodes(root) {
            it.text?.toString() == "Downloads" && it.isVisibleToUser
        }
        val drawerLabel = visibleDownloads.any { isDescendantOf(it, drawer) }
        val backgroundBreadcrumb = visibleDownloads.any {
            !isDescendantOf(it, drawer) && hasAncestorClass(it, "androidx.recyclerview.widget.RecyclerView")
        }
        return drawerLabel && backgroundBreadcrumb
    }

    private fun isDescendantOf(node: AccessibilityNodeInfo, ancestor: AccessibilityNodeInfo): Boolean {
        var current: AccessibilityNodeInfo? = node
        repeat(32) {
            if (current == null) return false
            if (current == ancestor) return true
            current = current?.parent
        }
        return false
    }

    private fun hasAncestorClass(node: AccessibilityNodeInfo, className: String): Boolean {
        var current = node.parent
        repeat(32) {
            if (current == null) return false
            if (current?.className?.toString() == className) return true
            current = current?.parent
        }
        return false
    }

    private fun tapDownloadsInPickerDrawer(context: String) {
        val drawer = documentPickerDrawerList()
            ?: throw AssertionError("Could not find the visible document picker locations drawer ($context)")
        val node = findAccessibilityNode(drawer) {
            it.text?.toString() == "Downloads" && it.isVisibleToUser &&
                !Rect().also(it::getBoundsInScreen).isEmpty
        } ?: throw AssertionError("Could not find Downloads inside the visible drawer list ($context)")
        tapNodeWithFinger(node, "Downloads in document picker drawer ($context)")
    }

    private fun visibleDocumentPickerNode(text: String): AccessibilityNodeInfo? {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return null
        if (!isDocumentPickerPackage(root.packageName?.toString())) return null
        return findAccessibilityNode(root) {
            it.text?.toString() == text && it.isVisibleToUser &&
                !Rect().also(it::getBoundsInScreen).isEmpty
        }
    }

    private fun selectedDocumentPickerOpenAction(selectedFileName: String): AccessibilityNodeInfo? {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return null
        if (!isDocumentPickerPackage(root.packageName?.toString())) return null

        fun find(node: AccessibilityNodeInfo, predicate: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
            if (predicate(node)) return node
            for (index in 0 until node.childCount) {
                node.getChild(index)?.let { find(it, predicate)?.let { found -> return found } }
            }
            return null
        }

        val fileNode = find(root) {
            it.text?.toString() == selectedFileName && it.isVisibleToUser &&
                !Rect().also(it::getBoundsInScreen).isEmpty
        } ?: return null
        var row: AccessibilityNodeInfo? = fileNode
        var fileIsSelected = false
        var depth = 0
        while (row != null && depth++ < 8) {
            val current = row ?: break
            val itemSelected = current.collectionItemInfo?.isSelected == true
            val state = if (android.os.Build.VERSION.SDK_INT >= 30) current.stateDescription?.toString().orEmpty() else ""
            val stateDescriptionSelected = state.contains("selected", ignoreCase = true) &&
                !state.contains("not selected", ignoreCase = true) &&
                !state.contains("unselected", ignoreCase = true)
            if (current.isSelected || current.isChecked || itemSelected || stateDescriptionSelected) {
                fileIsSelected = true
            }
            row = current.parent
        }
        if (!fileNode.isVisibleToUser || !fileIsSelected) return null
        val open = find(root) {
            (it.text?.toString()?.equals("Open", ignoreCase = true) == true ||
                it.contentDescription?.toString()?.equals("Open", ignoreCase = true) == true) &&
                it.isVisibleToUser && it.isEnabled && it.isClickable &&
                !Rect().also(it::getBoundsInScreen).isEmpty
        } ?: return null
        return open
    }

    private fun tapVisibleText(text: String) {
        val node = waitForNode(text, 8_000) ?: throw AssertionError("Could not find native UI text: $text")
        val bounds = Rect().also(node::getBoundsInScreen)
        assertTrue("Could not see native UI text: $text", node.isVisibleToUser && !bounds.isEmpty)
        tapNodeWithFinger(node, text)
        instrumentation.waitForIdleSync()
    }

    private fun tapNodeWithFinger(node: AccessibilityNodeInfo, label: String) {
        val bounds = Rect().also(node::getBoundsInScreen)
        assertTrue("Could not see native UI text: $label", node.isVisibleToUser && !bounds.isEmpty)
        val downTime = SystemClock.uptimeMillis()
        val finger = point(0, bounds.exactCenterX(), bounds.exactCenterY())
        assertTrue(
            "Could not inject finger-down on native UI text: $label",
            inject(pointerEvent(downTime, downTime, MotionEvent.ACTION_DOWN, listOf(finger))),
        )
        SystemClock.sleep(50)
        assertTrue(
            "Could not inject finger-up on native UI text: $label",
            inject(pointerEvent(downTime, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, listOf(finger))),
        )
        node.recycle()
    }

    private fun saveAccessibilityHierarchy(name: String) {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return
        val lines = mutableListOf("root package=[${root.packageName}]")
        fun append(node: AccessibilityNodeInfo, depth: Int) {
            val bounds = Rect().also(node::getBoundsInScreen)
            val text = node.text?.toString().orEmpty().replace('\n', ' ')
            val description = node.contentDescription?.toString().orEmpty().replace('\n', ' ')
            lines += "${"  ".repeat(depth)}${node.className} id=[${node.viewIdResourceName}] text=[$text] description=[$description] " +
                "bounds=$bounds visible=${node.isVisibleToUser} enabled=${node.isEnabled} " +
                "clickable=${node.isClickable} selected=${node.isSelected} checked=${node.isChecked} " +
                "checkable=${node.isCheckable} collectionSelected=${node.collectionItemInfo?.isSelected} " +
                "stateDescription=[${if (android.os.Build.VERSION.SDK_INT >= 30) node.stateDescription?.toString().orEmpty() else ""}]"
            for (index in 0 until node.childCount) node.getChild(index)?.let { append(it, depth + 1) }
        }
        append(root, 0)
        val directory = File(target.getExternalFilesDir(null), "flow15-ux-review")
        if (!directory.exists() && !directory.mkdirs()) return
        File(directory, "$name.txt").writeText(lines.joinToString("\n"), Charsets.UTF_8)
    }

    private fun waitForNode(text: String, timeoutMs: Long): AccessibilityNodeInfo? {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        while (SystemClock.uptimeMillis() < deadline) {
            val root = instrumentation.uiAutomation.rootInActiveWindow
            fun search(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
                if (node.text?.toString() == text || node.contentDescription?.toString() == text) return node
                for (index in 0 until node.childCount) node.getChild(index)?.let { search(it)?.let { found -> return found } }
                return null
            }
            root?.let { search(it)?.let { found -> return found } }
            SystemClock.sleep(100)
        }
        return null
    }

    private fun restoreAppOp(old: String) {
        val mode = when {
            old.contains("allow", true) -> "allow"
            old.contains("ignore", true) -> "ignore"
            old.contains("deny", true) -> "deny"
            else -> "default"
        }
        shell("cmd appops set ${target.packageName} SYSTEM_ALERT_WINDOW $mode")
    }

    private fun dp(value: Int): Int = (value * target.resources.displayMetrics.density).toInt()

    private fun waitUntil(description: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 5_000
        while (SystemClock.uptimeMillis() < deadline) {
            if (condition()) return
            SystemClock.sleep(50)
        }
        throw AssertionError("Timed out waiting for $description")
    }

    private fun currentResumedActivity(): Activity? {
        var resumed: Activity? = null
        instrumentation.runOnMainSync {
            resumed = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).firstOrNull()
        }
        return resumed
    }

    private fun shell(command: String): String = ParcelFileDescriptor.AutoCloseInputStream(
        instrumentation.uiAutomation.executeShellCommand(command),
    ).bufferedReader().use { it.readText() }

    private class RecordingContext(base: Context) : ContextWrapper(base) {
        val actions = CopyOnWriteArrayList<String>()
        override fun getApplicationContext(): Context = this
        override fun checkSelfPermission(permission: String): Int =
            if (permission == Manifest.permission.RECORD_AUDIO) PackageManager.PERMISSION_GRANTED else super.checkSelfPermission(permission)
        override fun startService(service: Intent): android.content.ComponentName? {
            service.action?.let(actions::add)
            return android.content.ComponentName(packageName, DictationService::class.java.name)
        }
        override fun startForegroundService(service: Intent): android.content.ComponentName? {
            service.action?.let(actions::add)
            return android.content.ComponentName(packageName, DictationService::class.java.name)
        }
    }
}
