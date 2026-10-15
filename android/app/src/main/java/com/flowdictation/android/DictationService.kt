package com.flowdictation.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.annotation.SuppressLint
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.widget.Toast
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Foreground service owning the dictation pipeline: microphone capture
 * ([AudioCapture]), offline transcription ([Transcriber]), history
 * ([HistoryStore]) and the floating bubble ([BubbleManager]).
 *
 * Commands arrive as start intents (see companion builders). State, levels,
 * results and errors are published via [DictationEvents]. Heavy work (model
 * load, capture stop/join, transcription) always runs on [bg], never on the
 * main thread.
 *
 * Foreground types: idle runs untyped (API 29-33) or specialUse (API 34+);
 * the MICROPHONE type is used only while actually recording, after the
 * permission check and before capture starts — starting mic-type foreground without
 * RECORD_AUDIO throws SecurityException on Android 14+.
 */
class DictationService : Service(), DictationListener {

    private lateinit var transcriber: Transcriber
    private lateinit var history: HistoryStore
    private lateinit var prefs: Prefs
    private lateinit var bubbles: BubbleManager
    private lateinit var notifications: NotificationManager

    private val bg: ExecutorService = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val idlePolicy = IdleUnloadPolicy()
    private var bubbleWasVisible = false
    @Volatile private var warming = false
    private val unloadIdle = Runnable {
        if (!destroyed) bg.execute {
            if (!destroyed && idlePolicy.shouldUnload(SystemClock.elapsedRealtime(), prefs.idleUnloadMinutes,
                    busy || warming || DictationEvents.state != DictState.IDLE)) {
                transcriber.release()
                main.post { if (!destroyed && !prefs.bubbleEnabled && !busy) stopSelf() }
            }
        }
    }

    /** True while preparing, recording or transcribing; guards double-start. */
    @Volatile
    private var busy = false

    @Volatile
    private var destroyed = false

    /**
     * Stop/cancel requested while PREPARING. The bg prepare block checks it
     * after every slow step and aborts before opening the mic, so releasing
     * hold-to-talk during model load never starts unattended recording.
     */
    @Volatile
    private var stopRequested = false

    /** Like [stopRequested], but discard instead of transcribe on the edge. */
    @Volatile
    private var cancelRequested = false

    @Volatile
    private var capture: AudioCapture? = null
    private var takeSequence = 0L // Allocated on main; zero means no live take.
    @Volatile private var activeTakeId = 0L
    @Volatile
    private var autoTargetId: Long? = null
    private val autoInputChanged: () -> Unit = { refreshBubble() }

    override fun onStateChanged(state: DictState) {
        if (DictationEvents.state == DictState.IDLE && !busy && !warming) scheduleIdleUnload()
        else {
            idlePolicy.beginWork()
            main.removeCallbacks(unloadIdle)
        }
        refreshBubble()
    }

    private fun scheduleIdleUnload() {
        if (destroyed || busy || warming) return
        idlePolicy.beginIdle(SystemClock.elapsedRealtime())
        main.removeCallbacks(unloadIdle)
        val remaining = idlePolicy.remainingMs(SystemClock.elapsedRealtime(), prefs.idleUnloadMinutes) ?: return
        main.postDelayed(unloadIdle, remaining)
    }

    private fun prewarm() {
        if (destroyed || warming || busy || ModelImportJob.isRunning) return
        warming = true
        idlePolicy.beginWork()
        main.removeCallbacks(unloadIdle)
        bg.execute {
            if (!destroyed && !ModelImportJob.isRunning) transcriber.ensureLoaded(prefs.modelId)
            main.post {
                warming = false
                if (!destroyed && !busy) scheduleIdleUnload()
            }
        }
    }

    private fun refreshBubble() {
        if (destroyed || !::bubbles.isInitialized) return
        val automatic = prefs.autoInputEnabled
        val show = AutoBubblePolicy.shouldShow(
            prefs.bubbleEnabled, automatic, AutoInputBridge.eligible,
            autoTargetId != null && DictationEvents.state != DictState.IDLE,
        )
        if (show) {
            if (!bubbles.show(automatic, AutoInputBridge.keyboardTop)) {
                prefs.bubbleEnabled = false
                DictationEvents.emitError(getString(R.string.need_overlay_permission))
            } else {
                bubbles.updatePlacement(if (automatic) AutoInputBridge.keyboardTop else null)
                if (!bubbleWasVisible) prewarm()
            }
        } else bubbles.hide()
        bubbleWasVisible = show && prefs.bubbleEnabled
        maybeStop()
    }

    private fun clearAutoTarget() {
        val target = autoTargetId ?: return
        autoTargetId = null
        if (Looper.myLooper() == Looper.getMainLooper()) AutoInputBridge.clearTarget(target)
        else main.post { AutoInputBridge.clearTarget(target) }
    }

    override fun onCreate() {
        super.onCreate()
        transcriber = Transcriber(applicationContext)
        history = HistoryStore(applicationContext)
        prefs = Prefs(applicationContext)
        bubbles = BubbleManager(applicationContext)
        bubbles.onPause = { setCapturePaused(true) }
        bubbles.onResume = { setCapturePaused(false) }
        notifications =
            applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        DictationEvents.register(this)
        AutoInputBridge.addListener(autoInputChanged)
        notifications.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notif_channel),
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> handleStart(intent.getLongExtra(EXTRA_AUTO_TARGET, 0L).takeIf { it != 0L })
            ACTION_REFRESH_AUTO_BUBBLE -> {
                val recording = DictationEvents.state == DictState.RECORDING
                foreground(getString(if (recording) R.string.notif_recording else R.string.notif_ready), mic = recording)
                refreshBubble()
            }
            ACTION_STOP -> handleStop()
            ACTION_CANCEL -> handleCancel()
            ACTION_SET_BUBBLE -> handleSetBubble(
                intent.getBooleanExtra(EXTRA_BUBBLE_ENABLED, false),
            )
            else -> {
                // Process restart with a null intent: restore the bubble if
                // it was enabled, otherwise stop. Idle foreground type only.
                foreground(getString(R.string.notif_ready))
                refreshBubble()
                maybeStop()
            }
        }
        // With no bubble there is nothing to restore after a kill; a sticky
        // restart would only spin up a mic-type service from the background.
        return if (prefs.bubbleEnabled) START_STICKY else START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        destroyed = true
        activeTakeId = 0
        DictationEvents.unregister(this)
        AutoInputBridge.removeListener(autoInputChanged)
        clearAutoTarget()
        main.removeCallbacks(unloadIdle)
        idlePolicy.beginWork()
        val cap = capture
        capture = null
        cap?.requestStop()
        bubbles.hide()
        // Never join AudioRecord or wait for the recognizer lock on the main thread.
        // Serial executor runs cleanup after any in-flight transcription returns.
        bg.execute {
            try { cap?.stop() } catch (_: Exception) {}
            transcriber.release()
        }
        bg.shutdown()
        DictationEvents.emitState(DictState.IDLE)
        super.onDestroy()
    }

    private fun handleStart(targetId: Long?) {
        if (destroyed || busy || DictationEvents.state != DictState.IDLE) {
            targetId?.let { AutoInputBridge.clearTarget(it) }
            return
        }
        if (ModelImportJob.isRunning) {
            targetId?.let { AutoInputBridge.clearTarget(it) }
            foreground(getString(R.string.notif_ready))
            DictationEvents.emitError("Finish installing the speech model before recording.")
            maybeStop()
            return
        }
        autoTargetId = targetId
        val takeId = ++takeSequence
        activeTakeId = takeId
        busy = true
        idlePolicy.beginWork()
        main.removeCallbacks(unloadIdle)
        stopRequested = false
        cancelRequested = false
        // Must become foreground promptly after startForegroundService().
        // Idle type: the mic type comes later, once capture actually starts.
        DictationEvents.emitState(DictState.PREPARING)
        foreground(getString(R.string.notif_working))
        bg.execute {
            if (stopRequested || destroyed) {
                abortPrepare()
                return@execute
            }
            if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                fail(getString(R.string.need_mic_permission))
                return@execute
            }
            if (stopRequested || destroyed) {
                abortPrepare()
                return@execute
            }
            if (!transcriber.ensureLoaded(prefs.modelId)) {
                fail(transcriber.lastError ?: "Model failed to load")
                return@execute
            }
            if (stopRequested || destroyed) {
                abortPrepare()
                return@execute
            }
            // Parakeet can decode completed pause-separated phrases during capture.
            // Other models keep their existing whole-take path.
            val incremental = transcriber.beginUtterance()
            // Set the foreground-service microphone type before AudioRecord starts.
            try {
                foreground(getString(R.string.notif_recording), mic = true)
            } catch (e: Exception) {
                fail("Cannot start microphone service: ${e.message}")
                return@execute
            }
            var cap: AudioCapture? = null
            val newCap = AudioCapture(
                onLevel = DictationEvents::emitLevel,
                boostQuietVoice = prefs.boostQuietVoice,
                onAudioStatus = { status -> main.post {
                    if (!destroyed && capture === cap && DictationEvents.state == DictState.RECORDING && cap?.isPaused != true) {
                        DictationEvents.emitAudioStatus(status)
                    }
                } },
                onQuiet = { quiet -> main.post {
                    if (!destroyed && capture === cap && DictationEvents.state == DictState.RECORDING) {
                        DictationEvents.emitQuiet(quiet && cap?.isPaused != true)
                    }
                } },
                onCapReached = { main.post { if (!destroyed) handleStop() } },
                onError = { message -> main.post {
                    if (!destroyed) cap?.let { handleCaptureError(it, message) }
                } },
                onSamples = if (!incremental) null else { samples ->
                    // Never decode on the microphone thread. The retained PCM is immutable;
                    // finishUtterance reconciles any final callback that races with Stop.
                    if (!destroyed && activeTakeId == takeId) runCatching {
                        bg.execute {
                            if (!destroyed && activeTakeId == takeId) {
                                transcriber.acceptUtteranceAudio(FloatArray(samples.size) { samples[it] / 32768.0f })
                            }
                        }
                    }
                    Unit
                },
            )
            cap = newCap
            capture = newCap
            if (!newCap.start()) {
                capture = null
                foreground(getString(R.string.notif_ready))
                fail(newCap.lastError ?: "Microphone failed to start")
                return@execute
            }
            if (stopRequested || destroyed) {
                try { newCap.stop() } catch (_: Exception) {}
                capture = null
                foreground(getString(R.string.notif_ready))
                abortPrepare()
                return@execute
            }
            // Commit RECORDING on main. This serializes capture failures and
            // release requests that arrive while the state is still PREPARING.
            main.post {
                if (destroyed || capture !== newCap) return@post
                updateNotification(getString(R.string.notif_recording))
                DictationEvents.emitState(DictState.RECORDING)
                if (stopRequested) {
                    if (cancelRequested) handleCancel() else handleStop()
                }
            }
        }
    }

    private fun handleStop() {
        when (DictationEvents.state) {
            DictState.RECORDING -> {
                val stoppedAt = SystemClock.elapsedRealtime()
                val takeId = activeTakeId
                // Let the in-flight phrase finish, but skip queued feed jobs. The
                // finalizer reconciles their unprocessed suffix from the full take.
                activeTakeId = 0
                val cap = capture
                cap?.requestStop()
                capture = null
                DictationEvents.emitState(DictState.TRANSCRIBING)
                updateNotification(getString(R.string.notif_working))
                stopRequested = false
                cancelRequested = false
                bg.execute { finishRecording(cap, takeId, stoppedAt) }
            }
            // Released during model load: the bg block aborts before capture.
            DictState.PREPARING -> stopRequested = true
            DictState.TRANSCRIBING, DictState.DISCARDING, DictState.IDLE -> Unit
        }
    }

    private fun setCapturePaused(paused: Boolean) {
        if (DictationEvents.state != DictState.RECORDING) return
        val cap = capture ?: return
        cap.setPaused(paused)
        DictationEvents.emitPaused(paused)
        if (paused) DictationEvents.emitQuiet(false)
        updateNotification(getString(if (paused) R.string.bubble_paused else R.string.notif_recording))
    }

    private fun handleCancel() {
        when (DictationEvents.state) {
            DictState.RECORDING -> {
                // Block Finish/repeated Discard while microphone cleanup runs.
                DictationEvents.emitState(DictState.DISCARDING)
                updateNotification(getString(R.string.notif_working))
                // Discard the partial utterance (no transcription).
                val cap = capture
                capture = null
                activeTakeId = 0
                cap?.requestStop()
                stopRequested = false
                cancelRequested = false
                bg.execute {
                    try {
                        cap?.stop()
                    } catch (_: Exception) {
                    }
                    transcriber.cancelUtterance()
                    clearAutoTarget()
                    busy = false
                    if (destroyed) return@execute
                    DictationEvents.emitState(DictState.IDLE)
                    foreground(getString(R.string.notif_ready))
                    updateNotification(getString(R.string.notif_ready))
                    maybeStop()
                }
            }
            // Cancelled during model load: the bg block aborts silently,
            // which discards (there is nothing to transcribe yet).
            DictState.PREPARING -> {
                stopRequested = true
                cancelRequested = true
            }
            // Native decoding is not interruptible; commands are only offered
            // while preparing/recording. Stale notification commands are harmless.
            DictState.TRANSCRIBING, DictState.DISCARDING, DictState.IDLE -> Unit
        }
    }

    /** Stop path tail on [bg]. History is saved only after text has been delivered. */
    private fun finishRecording(cap: AudioCapture?, takeId: Long, stoppedAt: Long) {
        val workerStartedAt = SystemClock.elapsedRealtime()
        val samples = try {
            cap?.stop() ?: FloatArray(0)
        } catch (e: Exception) {
            fail("Microphone error: ${e.message}")
            return
        }
        val audioReadyAt = SystemClock.elapsedRealtime()
        if (destroyed) return
        foreground(getString(R.string.notif_working))
        val durationMs = cap?.capturedDurationMs ?: 0L
        if (samples.size < MIN_SAMPLES) {
            fail("Recording too short. Speak for a little longer, then finish.")
            return
        }
        try {
            val rawText = transcriber.finishUtterance(samples)
            if (activeTakeId == takeId) activeTakeId = 0
            val recognizedAt = SystemClock.elapsedRealtime()
            val vocabulary = runCatching { VocabularyStore(applicationContext).load() }.getOrElse {
                DictationEvents.emitError("Vocabulary could not be read. Your transcript is available without vocabulary corrections.")
                emptyList()
            }
            val text = TranscriptProcessing.process(rawText, vocabulary, prefs.spokenCommands, prefs.cleanupPrompt)
            val processedAt = SystemClock.elapsedRealtime()
            DictationEvents.originalResult = text to rawText
            if (destroyed) return
            if (text.isEmpty()) {
                fail("No speech recognized")
                return
            }
            val saveHistory = prefs.historyEnabled
            val modelId = transcriber.currentModelId ?: prefs.modelId
            main.post {
                if (!destroyed) {
                    val target = autoTargetId
                    if (target == null) {
                        DictationEvents.emitResult(text, durationMs) { !destroyed }
                    } else {
                        val delivery = AutoInputDelivery.deliver(applicationContext, target, text)
                        DictationEvents.emitAutoResult(text, durationMs, delivery.inserted)
                        clearAutoTarget()
                        if (delivery.result != AutoInputResult.INSERTED) {
                            Toast.makeText(applicationContext, delivery.message, Toast.LENGTH_LONG).show()
                        }
                    }
                    val timing = StopToTextTiming(stoppedAt, workerStartedAt, audioReadyAt,
                        recognizedAt, processedAt, SystemClock.elapsedRealtime())
                    // Enqueue only after the main-thread delivery completed, so file writes
                    // cannot delay typing or block the open editor's history lookup.
                    bg.execute {
                        val historyStartedAt = SystemClock.elapsedRealtime()
                        val saved = if (saveHistory) runCatching {
                            history.add(text, durationMs, modelId, rawText)
                        }.onFailure {
                            DictationEvents.emitError("Text is ready, but history could not be saved. Copy or export it.")
                        }.getOrNull() else null
                        prefs.lastDictationTiming = timing.describe(SystemClock.elapsedRealtime() - historyStartedAt)
                        main.post {
                            busy = false
                            if (!destroyed) {
                                saved?.let { DictationEvents.emitHistorySaved(text, it.id) }
                                DictationEvents.emitState(DictState.IDLE)
                                foreground(getString(R.string.notif_ready))
                                maybeStop()
                            }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            fail(e.message ?: "Transcription failed")
        }
    }

    /** User stopped during PREPARING: silent return to idle. Runs on [bg]. */
    private fun abortPrepare() {
        activeTakeId = 0
        transcriber.cancelUtterance()
        clearAutoTarget()
        stopRequested = false
        cancelRequested = false
        busy = false
        if (destroyed) return
        DictationEvents.emitState(DictState.IDLE)
        foreground(getString(R.string.notif_ready))
        maybeStop()
    }

    private fun handleSetBubble(enabled: Boolean) {
        prefs.bubbleEnabled = enabled
        val recording = DictationEvents.state == DictState.RECORDING
        foreground(
            getString(if (recording) R.string.notif_recording else R.string.notif_ready),
            mic = recording,
        )
        refreshBubble()
        updateNotification(getString(
            if (DictationEvents.state == DictState.RECORDING) R.string.notif_recording
            else R.string.notif_ready,
        ))
        maybeStop()
    }

    private fun handleCaptureError(cap: AudioCapture, message: String) {
        if (capture !== cap) return
        capture = null
        activeTakeId = 0
        cap.requestStop()
        if (DictationEvents.state != DictState.RECORDING &&
            DictationEvents.state != DictState.PREPARING
        ) return
        DictationEvents.emitState(DictState.TRANSCRIBING)
        foreground(getString(R.string.notif_working))
        bg.execute {
            try { cap.stop() } catch (_: Exception) {}
            transcriber.cancelUtterance()
            fail(message)
        }
    }

    /** Reports a failure and returns the service to idle. Runs on [bg]. */
    private fun fail(message: String) {
        activeTakeId = 0
        transcriber.cancelUtterance()
        val automatic = autoTargetId != null
        clearAutoTarget()
        stopRequested = false
        cancelRequested = false
        busy = false
        if (destroyed) return
        if (automatic) main.post {
            if (!destroyed) Toast.makeText(applicationContext, message, Toast.LENGTH_LONG).show()
        } else DictationEvents.emitError(message)
        DictationEvents.emitState(DictState.IDLE)
        foreground(getString(R.string.notif_ready))
        maybeStop()
    }

    /**
     * Keeps the service until the configured idle model deadline. An enabled bubble keeps
     * its service alive even while automatic visibility is temporarily false.
     */
    private fun maybeStop() {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            main.post { if (!destroyed) maybeStop() }
            return
        }
        if (DictationEvents.state == DictState.IDLE && !busy && !warming) scheduleIdleUnload()
    }

    // InlinedApi is safe here: the FGS type constants are compile-time ints
    // and each use is SDK-guarded (mic >= 29, specialUse >= 34).
    @SuppressLint("InlinedApi")
    private fun foreground(text: String, mic: Boolean = false) {
        if (destroyed) return
        val notification = buildNotification(text)
        if (Build.VERSION.SDK_INT >= 29) {
            val type = if (mic) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            } else if (Build.VERSION.SDK_INT >= 34) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            } else {
                0
            }
            if (type == 0) {
                startForeground(NOTIF_ID, notification)
            } else {
                startForeground(NOTIF_ID, notification, type)
            }
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun updateNotification(text: String) {
        if (destroyed) return
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        notifications.notify(NOTIF_ID, buildNotification(text))
    }

    private fun buildNotification(text: String): Notification {
        val openApp = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = Notification.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setSubText(getString(R.string.tap_to_open))
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(openApp)
            .setOngoing(true)
        if (DictationEvents.state == DictState.RECORDING || DictationEvents.state == DictState.PREPARING) {
            builder.addAction(
                android.R.drawable.ic_media_pause,
                if (DictationEvents.state == DictState.PREPARING) "Cancel preparation" else "Finish",
                PendingIntent.getService(this, 1, stopIntent(this), PendingIntent.FLAG_IMMUTABLE),
            )
            builder.addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "Discard",
                PendingIntent.getService(this, 2, cancelIntent(this), PendingIntent.FLAG_IMMUTABLE),
            )
        }
        if (DictationEvents.state == DictState.IDLE && prefs.bubbleEnabled) {
            builder.addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "Disable bubble",
                PendingIntent.getService(
                    this, 3, setBubbleIntent(this, false), PendingIntent.FLAG_IMMUTABLE,
                ),
            )
        }
        return builder.build()
    }

    companion object {
        const val ACTION_START = "com.flowdictation.android.START"
        const val ACTION_STOP = "com.flowdictation.android.STOP"
        const val ACTION_CANCEL = "com.flowdictation.android.CANCEL"
        const val ACTION_SET_BUBBLE = "com.flowdictation.android.SET_BUBBLE"
        const val ACTION_REFRESH_AUTO_BUBBLE = "com.flowdictation.android.REFRESH_AUTO_BUBBLE"
        private const val EXTRA_AUTO_TARGET = "auto_target_id"
        const val EXTRA_BUBBLE_ENABLED = "bubble_enabled"

        private const val NOTIF_ID = 1
        private const val CHANNEL_ID = "flow_dictation"

        /** Minimum utterance length (~0.3 s at 16 kHz). */
        private const val MIN_SAMPLES = 4800

        fun startIntent(context: Context, targetId: Long? = null): Intent =
            Intent(context, DictationService::class.java).setAction(ACTION_START).apply {
                targetId?.let { putExtra(EXTRA_AUTO_TARGET, it) }
            }

        fun refreshAutoBubbleIntent(context: Context): Intent =
            Intent(context, DictationService::class.java).setAction(ACTION_REFRESH_AUTO_BUBBLE)

        fun stopIntent(context: Context): Intent =
            Intent(context, DictationService::class.java).setAction(ACTION_STOP)

        fun cancelIntent(context: Context): Intent =
            Intent(context, DictationService::class.java).setAction(ACTION_CANCEL)

        fun setBubbleIntent(context: Context, enabled: Boolean): Intent =
            Intent(context, DictationService::class.java)
                .setAction(ACTION_SET_BUBBLE)
                .putExtra(EXTRA_BUBBLE_ENABLED, enabled)
    }
}
