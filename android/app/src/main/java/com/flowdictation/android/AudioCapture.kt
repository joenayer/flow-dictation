package com.flowdictation.android

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder

/**
 * 16 kHz mono PCM16 microphone capture via [AudioRecord].
 *
 * Runs a dedicated capture thread; [onLevel] receives a 0..1 loudness estimate.
 * [stop] returns the full utterance as normalized float samples for sherpa-onnx.
 * [onCapReached] fires once on the capture thread when the 5-minute cap ends
 * capture; the owner should stop-and-transcribe (state must not stick).
 */
class AudioCapture(
    private val sampleRate: Int = 16000,
    private val onLevel: (Float) -> Unit = {},
    private val onCapReached: () -> Unit = {},
    private val onError: (String) -> Unit = {},
    private val boostQuietVoice: Boolean = true,
    private val onQuiet: (Boolean) -> Unit = {},
    private val onAudioStatus: (AudioSignalStatus) -> Unit = {},
    /** Accepted, gain-adjusted PCM. Immutable and identical to the retained take. Never block here. */
    private val onSamples: ((ShortArray) -> Unit)? = null,
) {
    @Volatile
    private var running = false
    private var thread: Thread? = null
    private var recorder: AudioRecord? = null
    private val lock = Any()

    // Guarded by [lock].
    private val captured = ArrayList<ShortArray>()
    private var capturedCount = 0
    private val gain = QuietVoiceGain(sampleRate)
    private val signal = AudioSignalMonitor(sampleRate)
    @Volatile private var paused = false
    @Volatile private var pauseEpoch = 0L
    @Volatile private var durationSamples = 0L

    val isPaused: Boolean get() = paused
    val capturedDurationMs: Long get() = durationSamples * 1000 / sampleRate

    /** Read and discard mic frames while paused; never stop or replace this take. */
    fun setPaused(value: Boolean) {
        synchronized(lock) {
            if (paused != value) {
                paused = value
                pauseEpoch++
                gain.reset()
                signal.reset()
            }
        }
        if (value) {
            runCatching { onLevel(0f) }
            runCatching { onQuiet(false) }
            runCatching { onAudioStatus(AudioSignalStatus.LISTENING) }
        }
    }

    val isRunning: Boolean
        get() = running

    /**
     * Starts capture. Returns false (with [lastError] set) if the microphone
     * cannot be opened.
     */
    @Volatile
    var lastError: String? = null
        private set

    // MissingPermission is intentional: DictationService checks RECORD_AUDIO
    // before starting, and a mid-flight revoke throws SecurityException,
    // which the try/catch below turns into a clean false.
    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        if (running) return true
        lastError = null
        val minBuf = try {
            AudioRecord.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
        } catch (e: Exception) {
            lastError = "Cannot query microphone: ${e.message}"
            return false
        }
        if (minBuf <= 0) {
            lastError = "Microphone does not support 16 kHz mono PCM16."
            return false
        }
        val bufferSize = maxOf(minBuf * 2, sampleRate * 2)
        val rec = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSize,
            )
        } catch (e: Exception) {
            lastError = "Cannot open microphone: ${e.message}"
            return false
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            lastError = "Microphone init failed (in use by another app?)."
            rec.release()
            return false
        }
        synchronized(lock) {
            captured.clear()
            capturedCount = 0
            durationSamples = 0
            paused = false
            pauseEpoch++
            gain.reset()
            signal.reset()
        }
        recorder = rec
        running = true
        try {
            thread = Thread(::captureLoop, "FlowAudioCapture").also { it.start() }
        } catch (e: Exception) {
            running = false
            recorder = null
            rec.release()
            lastError = "Cannot start microphone capture: ${e.message}"
            return false
        }
        return true
    }

    /** Stop accepting audio immediately, without joining a thread or calling AudioRecord on main. */
    fun requestStop() {
        synchronized(lock) {
            running = false
            pauseEpoch++
        }
    }

    /**
     * Stops capture and returns normalized float samples in [-1, 1].
     * Safe to call when not recording (returns empty array).
     */
    fun stop(): FloatArray {
        requestStop()
        val rec = recorder
        recorder = null
        if (rec != null) {
            try {
                if (rec.recordingState == AudioRecord.RECORDSTATE_RECORDING) rec.stop()
            } catch (_: Exception) {
                // stop() also unblocks a pending AudioRecord.read on supported devices.
            }
        }
        try {
            thread?.join(3000)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        }
        thread = null
        rec?.release()
        synchronized(lock) {
            val out = FloatArray(capturedCount)
            var target = 0
            for (chunk in captured) {
                for (sample in chunk) out[target++] = sample / 32768.0f
            }
            captured.clear()
            capturedCount = 0
            return out
        }
    }

    private fun captureLoop() {
        val rec = recorder ?: return
        // 32 ms per read: RMS updates keep pace with the 30 fps bubble without polling.
        val buf = ShortArray(512)
        var lastQuiet = false
        var lastStatus = AudioSignalStatus.LISTENING
        try {
            rec.startRecording()
        } catch (e: Exception) {
            reportError("Recording failed to start: ${e.message}")
            running = false
            return
        }
        while (running) {
            val readEpoch = pauseEpoch
            val n = try {
                rec.read(buf, 0, buf.size)
            } catch (e: Exception) {
                if (running) reportError("Microphone read failed: ${e.message}")
                break
            }
            if (n < 0) {
                if (running) reportError("Microphone read failed (AudioRecord error $n).")
                break
            }
            if (n == 0) {
                Thread.yield()
                continue
            }
            // Hard cap: 5 minutes per utterance to bound memory.
            var level = 0f
            var quiet = false
            var audioStatus = AudioSignalStatus.LISTENING
            var acceptedSamples: ShortArray? = null
            val accepted = synchronized(lock) {
                // A frame crossing either pause boundary is discarded too.
                if (!running || paused || readEpoch != pauseEpoch) return@synchronized 0
                val count = minOf(n, sampleRate * 300 - capturedCount)
                if (count > 0) {
                    signal.process(buf, count)
                    gain.process(buf, count, boostQuietVoice)
                    level = signal.level
                    audioStatus = signal.status
                    quiet = audioStatus == AudioSignalStatus.TOO_QUIET
                    val chunk = buf.copyOf(count)
                    captured.add(chunk)
                    acceptedSamples = chunk
                }
                capturedCount += count
                durationSamples += count
                count
            }
            if (accepted == 0) continue
            acceptedSamples?.let { samples -> runCatching { onSamples?.invoke(samples) } }
            try { onLevel(level) } catch (_: Exception) {}
            if (audioStatus != lastStatus) {
                lastStatus = audioStatus
                runCatching { onAudioStatus(audioStatus) }
            }
            if (quiet != lastQuiet) {
                lastQuiet = quiet
                try { onQuiet(quiet) } catch (_: Exception) {}
            }
            val overCap = synchronized(lock) { capturedCount >= sampleRate * 300 }
            if (overCap) {
                running = false
                try {
                    onCapReached()
                } catch (_: Exception) {
                }
                break
            }
        }
        // Release the live microphone as soon as this capture loop observes Stop,
        // even if the recognition worker is still decoding an earlier phrase.
        // The owner later joins this thread and releases the recorder in stop().
        runCatching {
            if (rec.recordingState == AudioRecord.RECORDSTATE_RECORDING) rec.stop()
        }
        running = false
    }

    private fun reportError(message: String) {
        lastError = message
        try { onError(message) } catch (_: Exception) {}
    }

}
