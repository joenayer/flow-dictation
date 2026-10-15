package com.flowdictation.android

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Rect
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.ScrollView
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.slider.Slider
import com.google.android.material.switchmaterial.SwitchMaterial
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Device checks for Flow 1.3 model decoding and settings on an actual Android UI. */
class Flow13DeviceTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val target: Context get() = instrumentation.targetContext

    @Test
    fun firstLaunchOffersModelSetupWithoutStartingDownloadOrRequestingMicrophone() {
        val repository = ModelImportRepository(target)
        assertTrue("The compact Android package must not bundle a speech model", ModelCatalog.models.none(repository::isBundled))
        if (ModelCatalog.models.any(repository::isAvailable)) return // This device already has a downloaded or imported model.

        var activity: MainActivity? = null
        try {
            activity = instrumentation.startActivitySync(
                Intent(target, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            ) as MainActivity
            instrumentation.waitForIdleSync()
            val screen = requireNotNull(activity)
            assertEquals(View.VISIBLE, screen.findViewById<View>(R.id.model_setup_card).visibility)
            assertTrue("Model setup waits for the user to tap", screen.findViewById<View>(R.id.model_setup_start).isEnabled)
            assertFalse("Opening Flow must not start a download", ModelImportJob.isRunning)
            assertEquals(PackageManager.PERMISSION_DENIED, screen.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO))
        } finally {
            activity?.finish()
            instrumentation.waitForIdleSync()
        }
    }

    @Test
    fun parakeetLoadsAndDecodesOfficialSpeechFixtureThroughTranscriber() {
        val spec = requireNotNull(ModelCatalog.spec(PARAKEET_ID))
        val repo = ModelImportRepository(target)
        val privateModel = repo.directory(spec.id)
        val stagedRoot = stagedModelRoot(repo.isAvailable(spec))
        val modelSource = if (repo.isAvailable(spec) &&
            ModelImportFiles.resolve(spec, privateModel.list()?.toList().orEmpty()) { it } != null
        ) privateModel else findModelDirectory(stagedRoot)
        val installedByTest = !repo.isAvailable(spec)
        if (installedByTest) copyParakeetModel(modelSource, privateModel)

        val fixture = InstrumentationRegistry.getArguments().getString(ARG_AUDIO)
            ?.let(::File)
            ?: File(modelSource, "test_wavs/0.wav")
        val transcriber = Transcriber(target)
        try {
            assertTrue(
                "The official archive's test_wavs/0.wav must be staged, or pass -e parakeetAudio <wav>",
                fixture.isFile,
            )
            assertTrue(
                "Parakeet recognizer and Silero VAD should load: ${transcriber.lastError}",
                transcriber.ensureLoaded(spec.id),
            )
            assertTrue("Transcriber should hold a native recognizer", transcriber.isLoaded)
            assertEquals(spec.id, transcriber.currentModelId)

            // This traverses the complete Silero VAD path, including final-window
            // padding and flush, and must finish without inventing speech.
            assertTrue(
                "Silence should produce no words",
                transcriber.transcribe(FloatArray(32_000), sampleRate = 16_000).isBlank(),
            )

            val decoded = transcriber.transcribe(readPcm16MonoWavAt16k(fixture))
            assertTrue("Parakeet should decode speech from ${fixture.name}", decoded.isNotBlank())
        } finally {
            transcriber.release()
            if (installedByTest) privateModel.deleteRecursively()
        }
    }

    @Test
    fun settingsRemainReachableAtLargeFontAndControlsPersist() {
        val shared = target.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val hadCleanupKey = shared.contains(KEY_CLEANUP_PROMPT)
        val oldCleanup = shared.getBoolean(KEY_CLEANUP_PROMPT, false)
        val prefs = Prefs(target)
        val oldSize = prefs.bubbleSizeDp
        val oldIdle = prefs.idleUnloadMinutes
        val oldBubble = prefs.bubbleEnabled
        val oldAutoInput = prefs.autoInputEnabled
        val oldFontScale = shell("settings get system font_scale").trim()
        var activity: SettingsActivity? = null
        var bubbleSettings: BubbleControlsActivity? = null

        try {
            // Remove only this key so the test covers the first-run default.
            shared.edit().remove(KEY_CLEANUP_PROMPT).commit()
            prefs.apply {
                bubbleSizeDp = 64
                idleUnloadMinutes = 2
                bubbleEnabled = false
                autoInputEnabled = false
            }
            shell("settings put system font_scale 2.0")
            activity = instrumentation.startActivitySync(
                Intent(target, SettingsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            ) as SettingsActivity
            instrumentation.waitForIdleSync()

            val screen = activity
            assertNotNull(screen)
            val activeScreen = screen!!
            // Settings' root content is a ScrollView but does not carry a resource id.
            val settingsScroll = findScrollView(activeScreen.window.decorView)
            assertNotNull("Settings should remain scrollable at 200% font size", settingsScroll)

            val cleanup = activeScreen.findViewById<SwitchMaterial>(R.id.cleanup_prompt_switch)
            val idleButton = activeScreen.findViewById<View>(R.id.idle_unload)
            assertVisibleByScrolling(settingsScroll!!, cleanup)
            assertFalse("Prompt cleanup is off on first run", cleanup.isChecked)
            assertFalse("First-run cleanup preference defaults off", prefs.cleanupPrompt)
            instrumentation.runOnMainSync { cleanup.performClick() }
            assertTrue("Cleanup toggle should save on", prefs.cleanupPrompt)
            instrumentation.runOnMainSync { cleanup.performClick() }
            assertFalse("Cleanup toggle should save off", prefs.cleanupPrompt)

            assertVisibleByScrolling(settingsScroll, idleButton)
            instrumentation.runOnMainSync { idleButton.performClick() }
            instrumentation.waitForIdleSync()
            assertTrue("Idle choices should be reachable in the dialog", waitForAccessibilityText("5 min idle"))
            clickAccessibilityText("5 min idle")
            waitUntil("idle timeout preference updates") { prefs.idleUnloadMinutes == 5 }
            assertTrue(idleButton.contentDescription?.contains("5 min") == true ||
                (idleButton as? android.widget.Button)?.text?.contains("5 min") == true)

            bubbleSettings = instrumentation.startActivitySync(
                Intent(target, BubbleControlsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            ) as BubbleControlsActivity
            instrumentation.waitForIdleSync()
            val bubbleScreen = requireNotNull(bubbleSettings)
            val bubbleScroll = requireNotNull(findScrollView(bubbleScreen.window.decorView))
            val slider = bubbleScreen.findViewById<Slider>(R.id.bubble_size_slider)
            assertVisibleByScrolling(bubbleScroll, slider)
            dragSliderToHighValue(slider)
            assertTrue("Moving the size slider should save a larger bubble", prefs.bubbleSizeDp > 110)
            assertTrue("Saved size stays inside the supported range", prefs.bubbleSizeDp in 32..160)
        } finally {
            bubbleSettings?.finish()
            activity?.finish()
            instrumentation.waitForIdleSync()
            if (oldFontScale.isBlank() || oldFontScale == "null") {
                shell("settings delete system font_scale")
            } else {
                shell("settings put system font_scale $oldFontScale")
            }
            prefs.apply {
                bubbleSizeDp = oldSize
                idleUnloadMinutes = oldIdle
                bubbleEnabled = oldBubble
                autoInputEnabled = oldAutoInput
                cleanupPrompt = oldCleanup
            }
            if (!hadCleanupKey) shared.edit().remove(KEY_CLEANUP_PROMPT).commit()
        }
    }

    private fun stagedModelRoot(modelAlreadyInstalled: Boolean): File {
        val argument = InstrumentationRegistry.getArguments().getString(ARG_MODEL_DIR)
        val fallback = File(target.getExternalFilesDir(null) ?: target.filesDir, "flow-parakeet")
        val root = argument?.let(::File) ?: fallback
        if (modelAlreadyInstalled && argument == null) {
            return ModelImportRepository(target).directory(PARAKEET_ID)
        }
        if (modelAlreadyInstalled && !root.isDirectory) return ModelImportRepository(target).root
        assertTrue(
            "Stage the extracted official Parakeet archive in $root, or pass -e $ARG_MODEL_DIR <path>",
            root.isDirectory,
        )
        return root
    }

    private fun findModelDirectory(root: File): File {
        val candidates = listOf(
            root,
            File(root, "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"),
        )
        return candidates.firstOrNull { directory ->
            ModelImportFiles.resolve(
                requireNotNull(ModelCatalog.spec(PARAKEET_ID)),
                directory.list()?.toList().orEmpty(),
            ) { File(directory, it).path } != null
        } ?: throw AssertionError(
            "No extracted Parakeet files found under $root; expected encoder.int8.onnx, " +
                "decoder.int8.onnx, joiner.int8.onnx, and tokens.txt",
        )
    }

    private fun copyParakeetModel(source: File, destination: File) {
        val files = requireNotNull(ModelImportFiles.resolve(
            requireNotNull(ModelCatalog.spec(PARAKEET_ID)),
            source.list()?.toList().orEmpty(),
        ) { File(source, it).path })
        destination.mkdirs()
        files.paths().forEach { path ->
            val file = File(path)
            assertTrue("Required model file is empty: ${file.name}", file.isFile && file.length() > 0)
            file.copyTo(File(destination, file.name), overwrite = true)
        }
    }

    private fun readPcm16MonoWavAt16k(file: File): FloatArray {
        val bytes = file.readBytes()
        assertTrue("WAV is too short: ${file.path}", bytes.size >= 44)
        assertEquals("RIFF", ascii(bytes, 0, 4))
        assertEquals("WAVE", ascii(bytes, 8, 4))
        var format = 0
        var channels = 0
        var rate = 0
        var bits = 0
        var dataOffset = -1
        var dataLength = 0
        var offset = 12
        while (offset + 8 <= bytes.size) {
            val tag = ascii(bytes, offset, 4)
            val size = littleInt(bytes, offset + 4).coerceAtLeast(0)
            val start = offset + 8
            if (start + size > bytes.size) break
            when (tag) {
                "fmt " -> {
                    format = littleShort(bytes, start)
                    channels = littleShort(bytes, start + 2)
                    rate = littleInt(bytes, start + 4)
                    bits = littleShort(bytes, start + 14)
                }
                "data" -> {
                    dataOffset = start
                    dataLength = size
                    break
                }
            }
            offset = start + size + (size and 1)
        }
        assertEquals("Fixture should be PCM WAV", 1, format)
        assertTrue("Fixture should have one or more channels", channels > 0)
        assertEquals("Fixture should be 16 kHz", 16_000, rate)
        assertEquals("Fixture should use 16-bit samples", 16, bits)
        assertTrue("WAV data chunk is missing", dataOffset >= 0 && dataLength > 0)
        val bytesPerFrame = channels * 2
        val frames = dataLength / bytesPerFrame
        return FloatArray(frames) { frame ->
            var sum = 0f
            repeat(channels) { channel ->
                val index = dataOffset + frame * bytesPerFrame + channel * 2
                val sample = ((bytes[index + 1].toInt() shl 8) or (bytes[index].toInt() and 0xff)).toShort()
                sum += sample / 32768f
            }
            sum / channels
        }
    }

    private fun dragSliderToHighValue(slider: Slider) {
        instrumentation.runOnMainSync {
            val startX = slider.width * 0.12f
            val endX = slider.width * 0.84f
            val y = slider.height / 2f
            val downTime = SystemClock.uptimeMillis()
            fun event(action: Int, x: Float, elapsed: Long) = MotionEvent.obtain(
                downTime, downTime + elapsed, action, x, y, 0,
            )
            val down = event(MotionEvent.ACTION_DOWN, startX, 0)
            slider.dispatchTouchEvent(down)
            down.recycle()
            val steps = 12
            for (step in 1..steps) {
                val x = startX + (endX - startX) * step / steps
                val move = event(MotionEvent.ACTION_MOVE, x, step * 20L)
                slider.dispatchTouchEvent(move)
                move.recycle()
            }
            val up = event(MotionEvent.ACTION_UP, endX, (steps + 1) * 20L)
            slider.dispatchTouchEvent(up)
            up.recycle()
        }
        instrumentation.waitForIdleSync()
    }

    private fun assertVisibleByScrolling(scroll: ScrollView, view: View) {
        instrumentation.runOnMainSync {
            view.requestRectangleOnScreen(Rect(0, 0, view.width, view.height), true)
            scroll.scrollTo(0, view.top)
        }
        instrumentation.waitForIdleSync()
        val visible = Rect()
        assertTrue("${resourceName(view)} should be reachable by scrolling at large font", view.getGlobalVisibleRect(visible))
        assertTrue("${resourceName(view)} should have visible height", visible.height() > 0)
    }

    private fun findScrollView(view: View): ScrollView? {
        if (view is ScrollView) return view
        if (view is android.view.ViewGroup) {
            for (index in 0 until view.childCount) findScrollView(view.getChildAt(index))?.let { return it }
        }
        return null
    }

    private fun resourceName(view: View): String = runCatching {
        target.resources.getResourceEntryName(view.id)
    }.getOrDefault(view.javaClass.simpleName)

    private fun waitForAccessibilityText(text: String): Boolean {
        val deadline = SystemClock.uptimeMillis() + 5_000
        while (SystemClock.uptimeMillis() < deadline) {
            if (accessibilityTexts().contains(text)) return true
            SystemClock.sleep(100)
        }
        return false
    }

    private fun clickAccessibilityText(text: String) {
        val deadline = SystemClock.uptimeMillis() + 5_000
        while (SystemClock.uptimeMillis() < deadline) {
            val node = findAccessibilityNode(text)
            if (node != null) {
                assertTrue("Could not select $text", node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
                instrumentation.waitForIdleSync()
                return
            }
            SystemClock.sleep(100)
        }
        throw AssertionError("Timed out waiting for option: $text")
    }

    private fun findAccessibilityNode(text: String): AccessibilityNodeInfo? {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return null
        fun find(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
            if (node.text?.toString() == text || node.contentDescription?.toString() == text) return node
            for (index in 0 until node.childCount) node.getChild(index)?.let { child ->
                find(child)?.let { return it }
            }
            return null
        }
        return find(root)
    }

    private fun accessibilityTexts(): Set<String> {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return emptySet()
        val found = mutableSetOf<String>()
        fun visit(node: AccessibilityNodeInfo) {
            node.text?.toString()?.let(found::add)
            node.contentDescription?.toString()?.let(found::add)
            for (index in 0 until node.childCount) node.getChild(index)?.let(::visit)
        }
        visit(root)
        return found
    }

    private fun waitUntil(description: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 5_000
        while (SystemClock.uptimeMillis() < deadline) {
            if (condition()) return
            SystemClock.sleep(50)
        }
        throw AssertionError("Timed out waiting for $description")
    }

    private fun shell(command: String): String = android.os.ParcelFileDescriptor
        .AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(command))
        .bufferedReader()
        .use { it.readText() }

    private fun ascii(bytes: ByteArray, start: Int, length: Int): String =
        String(bytes, start, length, Charsets.US_ASCII)

    private fun littleShort(bytes: ByteArray, start: Int): Int =
        (bytes[start].toInt() and 0xff) or ((bytes[start + 1].toInt() and 0xff) shl 8)

    private fun littleInt(bytes: ByteArray, start: Int): Int =
        (littleShort(bytes, start) or (littleShort(bytes, start + 2) shl 16))

    private companion object {
        const val PARAKEET_ID = "nemo-parakeet-tdt-0.6b-v2-int8"
        const val ARG_MODEL_DIR = "parakeetModelDir"
        const val ARG_AUDIO = "parakeetAudio"
        const val PREFS_NAME = "flow_dictation"
        const val KEY_CLEANUP_PROMPT = "cleanup_prompt"
    }
}
