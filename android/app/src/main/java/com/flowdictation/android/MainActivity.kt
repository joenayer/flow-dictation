package com.flowdictation.android

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.text.Editable
import android.text.TextWatcher
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.switchmaterial.SwitchMaterial

class MainActivity : FlowActivity(), DictationListener {
    private lateinit var prefs: Prefs
    private lateinit var history: HistoryStore
    private lateinit var modelRepository: ModelImportRepository
    private lateinit var talk: Button
    private lateinit var status: TextView
    private lateinit var timer: TextView
    private lateinit var editor: EditText
    private lateinit var level: ProgressBar
    private lateinit var bubble: SwitchMaterial
    private val main = Handler(Looper.getMainLooper())
    private var updating = false
    private var dirty = false
    private var selectedId: Long? = null
    private var held = false
    private var pendingBubble = false
    private var askedMic = false
    private var recordingSince = 0L
    private var reviewingText: String? = null
    private var savedEditorText = ""
    private val inputListener: () -> Unit = { refreshSetup() }
    private val modelListener: () -> Unit = { refreshModelSetup() }
    private val tick = object : Runnable {
        override fun run() {
            if (DictationEvents.state == DictState.RECORDING) {
                val seconds = DictationEvents.recordingDurationMs() / 1000
                timer.text = "%d:%02d · %s · 5-minute limit".format(seconds / 60, seconds % 60,
                    if (DictationEvents.paused) getString(R.string.bubble_paused) else "Recording")
                main.postDelayed(this, 250)
            } else if (DictationEvents.state == DictState.PREPARING || DictationEvents.state == DictState.TRANSCRIBING) {
                val seconds = DictationEvents.processingElapsedMs() / 1000
                timer.text = "${seconds}s · On this device"
                main.postDelayed(this, 250)
            }
        }
    }
    @SuppressLint("ClickableViewAccessibility")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        applyInsets()
        prefs = Prefs(this)
        history = HistoryStore(this)
        modelRepository = ModelImportRepository(applicationContext)
        talk = findViewById(R.id.btn_talk)
        status = findViewById(R.id.tv_status)
        timer = findViewById(R.id.tv_timer)
        editor = findViewById(R.id.transcript_editor)
        level = findViewById(R.id.record_level)
        bubble = findViewById(R.id.bubble_switch)
        askedMic = savedInstanceState?.getBoolean("asked_mic") ?: false
        selectedId = savedInstanceState?.getLong("selected_id")?.takeIf { it > 0 }
        dirty = savedInstanceState?.getBoolean("dirty") ?: false
        if (savedInstanceState != null) editor.setText(savedInstanceState.getString("editor"))
        else history.load().firstOrNull()?.let { selectedId = it.id; editor.setText(it.text) }
        savedEditorText = savedInstanceState?.getString("saved_editor") ?: editor.text.toString()
        editor.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                if (!updating) dirty = true
                refreshActions()
            }
            override fun afterTextChanged(s: Editable?) {}
        })
        talk.setOnClickListener { toggleRecording() }
        talk.setOnTouchListener { _, event ->
            if (!prefs.holdToTalk) false else {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        // An editing decision cannot be made during a hold gesture.
                        if (dirty && editor.text.isNotBlank()) message("Save your edits before starting a new recording.")
                        else if (DictationEvents.state == DictState.IDLE && micGranted()) {
                            held = true
                            beginRecording()
                        } else if (!micGranted()) requestMic()
                    }
                    MotionEvent.ACTION_UP -> {
                        if (held) stopRecording()
                        held = false
                    }
                    MotionEvent.ACTION_CANCEL -> {
                        if (held) send(DictationService.cancelIntent(this))
                        held = false
                    }
                }
                true
            }
        }
        findViewById<Button>(R.id.btn_cancel).setOnClickListener { send(DictationService.cancelIntent(this)) }
        findViewById<Button>(R.id.btn_settings).setOnClickListener { startActivity(Intent(this, SettingsActivity::class.java)) }
        findViewById<Button>(R.id.btn_automatic_typing).setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        findViewById<Button>(R.id.btn_history).setOnClickListener { startActivity(Intent(this, HistoryActivity::class.java)) }
        findViewById<Button>(R.id.btn_permission).setOnClickListener { requestMic() }
        findViewById<Button>(R.id.model_setup_start).setOnClickListener { ModelImportJob.downloadRecommended(this) }
        findViewById<Button>(R.id.model_setup_cancel).setOnClickListener { ModelImportJob.cancel() }
        findViewById<Button>(R.id.btn_copy).setOnClickListener {
            if (TextOutput.copy(this, editor.text.toString())) message("Copied. Paste into your app.")
        }
        findViewById<Button>(R.id.btn_share).setOnClickListener {
            if (!TextOutput.share(this, editor.text.toString())) message("Could not share text.")
        }
        findViewById<Button>(R.id.btn_export).setOnClickListener { exportText(editor.text.toString(), "Flow-transcript.txt") }
        findViewById<Button>(R.id.btn_original).setOnClickListener {
            val original = selectedId?.let { id -> history.load().firstOrNull { it.id == id }?.originalText }
                ?: DictationEvents.originalResult?.takeIf { it.first == savedEditorText }?.second
            if (original == null) message("No original transcript is available for this text.")
            else MaterialAlertDialogBuilder(this).setTitle(R.string.show_original)
                .setMessage(original).setPositiveButton("Close", null).show()
        }
        findViewById<Button>(R.id.btn_save).setOnClickListener {
            try {
                val text = editor.text.toString()
                if (selectedId == null || !history.update(selectedId!!, text)) {
                    selectedId = history.add(text, 0, prefs.modelId).id
                }
                dirty = false
                message("Edits saved.")
                VocabularyLearning.offer(this, savedEditorText, text)
                savedEditorText = text
                refreshActions()
                refreshSetup()
            } catch (_: Exception) { message("Could not save edits. Copy or export your text first.") }
        }
        bubble.setOnCheckedChangeListener { _, enabled ->
            if (!updating) {
                if (enabled) enableBubble()
                else {
                    prefs.bubbleEnabled = false
                    send(DictationService.setBubbleIntent(this, false))
                    refreshSetup()
                }
            }
        }
        refreshActions()
        consumeReviewIntent(intent)
    }
    override fun onStart() {
        super.onStart()
        DictationEvents.register(this)
        ModelImportJob.register(modelListener)
        DictationEvents.peekPendingResult()?.let { onResult(it.text, it.durationMs) }
    }
    override fun onStop() {
        if (held) { send(DictationService.cancelIntent(this)); held = false }
        DictationEvents.unregister(this)
        ModelImportJob.unregister(modelListener)
        main.removeCallbacks(tick)
        super.onStop()
    }
    override fun onResume() {
        super.onResume()
        if (pendingBubble && Settings.canDrawOverlays(this)) {
            pendingBubble = false
            enableBubble()
        }
        AutoInputBridge.addListener(inputListener)
        AutoInputBridge.refresh()
        if (prefs.bubbleEnabled && Settings.canDrawOverlays(this)) {
            try { startForegroundService(DictationService.setBubbleIntent(this, true)) }
            catch (_: Exception) { message("Could not restore the floating microphone. Try enabling it again.") }
        }
        refreshSetup()
        onStateChanged(DictationEvents.state)
        refreshActions()
    }
    override fun onPause() {
        AutoInputBridge.removeListener(inputListener)
        super.onPause()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("editor", editor.text.toString())
        outState.putLong("selected_id", selectedId ?: 0)
        outState.putBoolean("dirty", dirty)
        outState.putBoolean("asked_mic", askedMic)
        outState.putString("saved_editor", savedEditorText)
        super.onSaveInstanceState(outState)
    }
    override fun onStateChanged(state: DictState) {
        main.removeCallbacks(tick)
        val active = state == DictState.RECORDING || state == DictState.PREPARING
        findViewById<Button>(R.id.btn_cancel).visibility = if (active) View.VISIBLE else View.GONE
        val modelReady = ModelCatalog.spec(prefs.modelId)?.let { modelRepository.isAvailable(it) } == true
        talk.isEnabled = state != DictState.TRANSCRIBING && state != DictState.DISCARDING && modelReady
        val processing = state == DictState.PREPARING || state == DictState.TRANSCRIBING
        findViewById<ProgressBar>(R.id.processing_progress).visibility = if (processing) View.VISIBLE else View.GONE
        findViewById<TextView>(R.id.processing_detail).apply {
            visibility = if (processing) View.VISIBLE else View.GONE
            text = if (state == DictState.PREPARING) "Getting speech recognition ready."
                else "Longer recordings take more time. Your audio stays on this device."
        }
        level.visibility = if (state == DictState.RECORDING) View.VISIBLE else View.GONE
        when (state) {
            DictState.IDLE -> {
                status.text = if (modelReady) "Ready to record" else "Set up speech recognition"
                talk.text = if (prefs.holdToTalk) "Hold to talk" else "Start recording"
                timer.text = "English · Offline"
                level.progress = 0
            }
            DictState.PREPARING -> {
                status.text = "Getting the microphone ready"
                talk.text = if (prefs.holdToTalk) "Release to cancel" else "Cancel preparation"
                main.post(tick)
            }
            DictState.RECORDING -> {
                status.text = "Listening"
                talk.text = if (prefs.holdToTalk) "Release to finish" else "Finish recording"
                recordingSince = DictationEvents.recordingStartedAtMs.takeIf { it > 0 } ?: SystemClock.elapsedRealtime()
                main.post(tick)
            }
            DictState.DISCARDING -> {
                status.text = "Discarding recording"
                talk.text = "Discarding…"
                timer.text = "Your previous transcript is kept"
                level.progress = 0
            }
            DictState.TRANSCRIBING -> {
                status.text = "Transcribing…"
                talk.text = "Transcribing…"
                timer.text = "Processing on your device"
                main.post(tick)
            }
        }
        if (state == DictState.IDLE) recordingSince = 0
        findViewById<TextView>(R.id.tv_hint).text = if (prefs.holdToTalk) "Press and hold. Release to finish." else "Tap to start. Tap again to finish."
    }
    override fun onLevel(level01: Float) { level.progress = (level01 * 100).toInt().coerceIn(0, 100) }
    override fun onQuiet(quiet: Boolean) { updateListeningStatus() }
    override fun onPaused(paused: Boolean) { updateListeningStatus() }
    override fun onAudioStatus(status: AudioSignalStatus) { updateListeningStatus() }
    private fun updateListeningStatus() {
        if (DictationEvents.state != DictState.RECORDING) return
        status.text = when {
            DictationEvents.paused -> getString(R.string.bubble_paused)
            else -> DictationEvents.audioStatus.label
        }
    }
    override fun onResult(text: String, durationMs: Long) {
        // Do not overwrite edits made while dictating from the bubble.
        if (dirty && editor.text.isNotBlank()) {
            reviewText(text, durationMs)
            return
        }
        DictationEvents.peekPendingResult()?.takeIf { it.text == text && it.durationMs == durationMs }
            ?.let { DictationEvents.acknowledgeResult(it) }
        updating = true
        editor.setText(text)
        savedEditorText = text
        updating = false
        dirty = false
        selectedId = if (prefs.historyEnabled) history.load().firstOrNull { it.text == text }?.id else null
        refreshActions()
        refreshSetup()
    }
    override fun onAutoResult(text: String, durationMs: Long, inserted: Boolean) {
        onResult(text, durationMs)
    }
    override fun onHistorySaved(text: String, entryId: Long) {
        if (!dirty && editor.text.toString() == text) selectedId = entryId
        refreshActions()
        refreshSetup()
    }
    override fun onError(message: String) { message(message); refreshSetup() }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        consumeReviewIntent(intent)
    }
    private fun consumeReviewIntent(incoming: Intent) {
        val text = incoming.getStringExtra("review_text") ?: return
        incoming.removeExtra("review_text")
        reviewText(text)
    }
    private fun reviewText(text: String, durationMs: Long? = null) {
        // Capture identity now so an older review cannot clear a newer result.
        val pendingResult = DictationEvents.peekPendingResult()?.takeIf {
            it.text == text && (durationMs == null || durationMs == it.durationMs)
        }
        fun acknowledge() { pendingResult?.let { DictationEvents.acknowledgeResult(it) } }
        fun useText() {
            acknowledge()
            updating = true
            editor.setText(text)
            savedEditorText = text
            updating = false
            dirty = false
            selectedId = history.load().firstOrNull { it.text == text }?.id
            refreshActions()
        }
        if (dirty && editor.text.isNotBlank()) {
            if (reviewingText == text) return
            reviewingText = text
            val dialog = MaterialAlertDialogBuilder(this).setTitle("New dictation is ready")
                .setMessage("Your editor has unsaved changes. Copy the new dictation or replace the editor text.")
                .setNegativeButton("Keep editing", null)
                .setNeutralButton("Copy new text") { _, _ ->
                    if (TextOutput.copy(this, text)) { acknowledge(); message("New dictation copied.") }
                }
                .setPositiveButton("Use new text") { _, _ -> useText() }.create()
            dialog.setOnDismissListener { reviewingText = null }
            dialog.show()
        } else useText()
    }
    private fun refreshActions() {
        val hasText = editor.text.isNotBlank()
        listOf(R.id.btn_copy, R.id.btn_share, R.id.btn_export).forEach { findViewById<Button>(it).isEnabled = hasText }
        findViewById<Button>(R.id.btn_save).isEnabled = hasText && dirty && prefs.historyEnabled
    }
    private fun refreshSetup() {
        findViewById<View>(R.id.setup_card).visibility = if (micGranted()) View.GONE else View.VISIBLE
        refreshModelSetup()
        updating = true
        bubble.isChecked = prefs.bubbleEnabled && Settings.canDrawOverlays(this)
        updating = false
        findViewById<TextView>(R.id.bubble_help).setText(
            if (prefs.autoInputEnabled) R.string.automatic_bubble_help else R.string.manual_bubble_help
        )
        findViewById<TextView>(R.id.automatic_typing_summary).setText(when {
            !prefs.autoInputEnabled -> R.string.automatic_typing_main_off
            !AutoInputBridge.isServiceEnabled(this) -> R.string.automatic_typing_main_needed
            !prefs.bubbleEnabled || !Settings.canDrawOverlays(this) -> R.string.automatic_typing_main_paused
            !AutoInputBridge.connected -> R.string.automatic_typing_connecting
            else -> R.string.automatic_typing_main_ready
        })
        findViewById<Button>(R.id.btn_automatic_typing).setText(
            if (prefs.autoInputEnabled) R.string.automatic_typing_manage_setup else R.string.automatic_typing_setup
        )
        val count = history.load().size
        findViewById<TextView>(R.id.history_summary).text = if (!prefs.historyEnabled) "History is off. Existing entries: " + count
            else if (count == 0) "No saved dictations yet." else count.toString() + " saved dictations · Stored on this device"
    }

    private fun refreshModelSetup() {
        if (!::modelRepository.isInitialized) return
        val available = ModelCatalog.models.filter { modelRepository.isAvailable(it) }
        val selected = ModelCatalog.spec(prefs.modelId)
        val setupPending = ModelImportJob.hasResumableSetup(this)
        if (!setupPending && available.isNotEmpty() && selected !in available) prefs.modelId = available.first().id
        val ready = ModelCatalog.spec(prefs.modelId)?.let { modelRepository.isAvailable(it) } == true
        val card = findViewById<View>(R.id.model_setup_card)
        card.visibility = if (ModelSetupPolicy.showSetup(available.map { it.id }.toSet(), setupPending)) View.VISIBLE else View.GONE
        talk.isEnabled = DictationEvents.state != DictState.TRANSCRIBING && DictationEvents.state != DictState.DISCARDING && ready
        val label = findViewById<TextView>(R.id.model_setup_status)
        val bar = findViewById<ProgressBar>(R.id.model_setup_progress)
        val start = findViewById<Button>(R.id.model_setup_start)
        val pause = findViewById<Button>(R.id.model_setup_cancel)
        if (ModelImportJob.isRunning) {
            label.text = ModelImportJob.status
            bar.visibility = View.VISIBLE
            bar.isIndeterminate = ModelImportJob.progressPercent < 0
            if (!bar.isIndeterminate) bar.progress = ModelImportJob.progressPercent
            start.isEnabled = false
            start.text = "Setup in progress"
            pause.visibility = View.VISIBLE
        } else {
            val status = ModelImportJob.status
            label.text = when {
                status.isNotBlank() -> status
                setupPending -> "A previous download is saved. Tap to resume setup."
                else -> "Nothing downloads until you tap the button."
            }
            bar.visibility = View.GONE
            start.isEnabled = true
            start.text = if (setupPending) "Resume recommended setup" else "Download recommended setup"
            pause.visibility = View.GONE
        }
    }
    private fun toggleRecording() {
        when (DictationEvents.state) {
            DictState.IDLE -> {
                if (!micGranted()) { requestMic(); return }
                if (dirty && editor.text.isNotBlank()) {
                    MaterialAlertDialogBuilder(this).setTitle("Keep your edits?")
                        .setMessage("Copy, export or save your edits before replacing this transcript.")
                        .setNegativeButton("Keep editing", null)
                        .setPositiveButton("Replace") { _, _ -> dirty = false; beginRecording() }.show()
                } else beginRecording()
            }
            DictState.RECORDING, DictState.PREPARING -> stopRecording()
            DictState.TRANSCRIBING, DictState.DISCARDING -> Unit
        }
    }
    private fun beginRecording() {
        editor.clearFocus()
        androidx.core.view.WindowInsetsControllerCompat(window, window.decorView).hide(WindowInsetsCompat.Type.ime())
        try { startForegroundService(DictationService.startIntent(this)) }
        catch (_: Exception) { message("Could not start recording. Open Flow and try again.") }
    }
    private fun stopRecording() { send(DictationService.stopIntent(this)) }
    private fun send(intent: Intent) {
        try { startService(intent) } catch (_: Exception) { message("Could not update recording. Reopen Flow and try again.") }
    }
    private fun micGranted() = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    private fun requestMic() {
        if (askedMic && !shouldShowRequestPermissionRationale(Manifest.permission.RECORD_AUDIO)) {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + packageName)))
        } else {
            askedMic = true
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
    }
    private fun enableBubble() {
        if (!Settings.canDrawOverlays(this)) {
            pendingBubble = true
            try { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + packageName))) }
            catch (_: Exception) { message("Open phone settings and allow Flow to appear on top.") }
            refreshSetup()
            return
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        }
        try {
            prefs.bubbleEnabled = true
            startForegroundService(DictationService.setBubbleIntent(this, true))
        } catch (_: Exception) { prefs.bubbleEnabled = false; message("Could not enable the floating microphone. Try again.") }
        refreshSetup()
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refreshSetup()
        if (requestCode == 1 && micGranted()) message("Microphone ready. Tap Start recording when you are ready.")
        if (requestCode == 1 && micGranted() && pendingBubble) { pendingBubble = false; enableBubble() }
        if (requestCode == 1 && !micGranted()) pendingBubble = false
    }
}
