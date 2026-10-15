package com.flowdictation.android

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.util.concurrent.CopyOnWriteArraySet

/** Dictation pipeline state. */
enum class DictState {
    IDLE,
    /** Model loading / mic opening: stop/cancel here aborts before capture. */
    PREPARING,
    RECORDING,
    TRANSCRIBING,
    /** Microphone cleanup after Discard; no further recording commands. */
    DISCARDING,
}

/** Callbacks for dictation activity. All are invoked on the main thread. */
interface DictationListener {
    fun onStateChanged(state: DictState) {}
    fun onLevel(level01: Float) {}
    fun onQuiet(quiet: Boolean) {}
    fun onPaused(paused: Boolean) {}
    fun onAudioStatus(status: AudioSignalStatus) {}
    fun onResult(text: String, durationMs: Long) {}
    fun onError(message: String) {}
    fun onAutoResult(text: String, durationMs: Long, inserted: Boolean) {}
    fun onHistorySaved(text: String, entryId: Long) {}
}

/**
 * Tiny main-thread event bus between [DictationService] and UI (activity, bubble).
 * No external dependencies (deliberately not coroutines/Flow: framework only).
 */
object DictationEvents {
    private val listeners = CopyOnWriteArraySet<DictationListener>()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val pendingTranscript = PendingTranscript()

    /** Only the latest raw result is retained in memory when history is disabled. */
    @Volatile var originalResult: Pair<String, String>? = null
    @Volatile var paused: Boolean = false
        private set
    @Volatile var quiet: Boolean = false
        private set
    @Volatile var audioStatus = AudioSignalStatus.LISTENING
        private set
    @Volatile var stateStartedAtMs = 0L
        private set

    fun processingElapsedMs(now: Long = SystemClock.elapsedRealtime()): Long =
        if (state == DictState.PREPARING || state == DictState.TRANSCRIBING)
            (now - stateStartedAtMs).coerceAtLeast(0) else 0

    fun emitAudioStatus(value: AudioSignalStatus) {
        audioStatus = value
        mainHandler.post { listeners.forEach { it.onAudioStatus(value) } }
    }
    @Volatile private var pauseStartedAtMs = 0L
    @Volatile private var pausedTotalMs = 0L

    fun recordingDurationMs(now: Long = SystemClock.elapsedRealtime()): Long {
        if (recordingStartedAtMs == 0L) return 0L
        return ((if (paused) pauseStartedAtMs else now) - recordingStartedAtMs - pausedTotalMs).coerceAtLeast(0)
    }

    fun emitPaused(value: Boolean) {
        if (value == paused) return
        val now = SystemClock.elapsedRealtime()
        if (value) pauseStartedAtMs = now else pausedTotalMs += now - pauseStartedAtMs
        paused = value
        mainHandler.post { listeners.forEach { it.onPaused(value) } }
    }

    fun emitQuiet(value: Boolean) {
        quiet = value
        mainHandler.post { listeners.forEach { it.onQuiet(value) } }
    }

    @Volatile
    var state: DictState = DictState.IDLE
        private set

    /** Monotonic start time shared by UI surfaces across activity recreation. */
    @Volatile
    var recordingStartedAtMs: Long = 0L
        private set

    fun register(listener: DictationListener) {
        listeners.add(listener)
        mainHandler.post {
            listener.onStateChanged(state)
            listener.onPaused(paused)
            listener.onQuiet(quiet)
            listener.onAudioStatus(audioStatus)
        }
    }

    fun unregister(listener: DictationListener) {
        listeners.remove(listener)
    }

    fun emitState(newState: DictState) {
        if (newState != state) stateStartedAtMs = SystemClock.elapsedRealtime()
        if (newState == DictState.RECORDING && state != DictState.RECORDING) {
            recordingStartedAtMs = SystemClock.elapsedRealtime()
            pausedTotalMs = 0
            paused = false
        } else if (newState == DictState.IDLE) {
            recordingStartedAtMs = 0L
        }
        if (newState != DictState.RECORDING) {
            paused = false
            quiet = false
            audioStatus = AudioSignalStatus.LISTENING
        }
        state = newState
        mainHandler.post {
            listeners.forEach { it.onStateChanged(newState) }
        }
    }

    fun emitLevel(level01: Float) {
        mainHandler.post {
            listeners.forEach { it.onLevel(level01) }
        }
    }

    fun emitResult(
        text: String,
        durationMs: Long,
        stillValid: () -> Boolean = { true },
    ) {
        val publish = {
            if (stillValid()) {
                pendingTranscript.publish(text, durationMs)
                listeners.forEach { it.onResult(text, durationMs) }
            }
        }
        if (Looper.myLooper() == Looper.getMainLooper()) publish() else mainHandler.post { publish() }
    }

    /** History is written after delivery; lets an open editor attach the saved entry without rereading. */
    fun emitHistorySaved(text: String, entryId: Long) {
        listeners.forEach { it.onHistorySaved(text, entryId) }
    }

    /** Auto dictation stays recoverable without opening the manual result panel. */
    fun emitAutoResult(text: String, durationMs: Long, inserted: Boolean) {
        pendingTranscript.publish(text, durationMs)
        listeners.forEach { it.onAutoResult(text, durationMs, inserted) }
    }

    /** In-memory recovery when the editor was away while transcription completed. */
    fun peekPendingResult(): PendingTranscript.Result? = pendingTranscript.peek()

    fun acknowledgeResult(result: PendingTranscript.Result) {
        pendingTranscript.acknowledge(result)
    }

    fun emitError(message: String) {
        mainHandler.post {
            listeners.forEach { it.onError(message) }
        }
    }
}
