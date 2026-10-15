package com.flowdictation.android

/** Monotonic elapsed times only. No audio, transcript or target-app information is retained. */
data class StopToTextTiming(
    val stoppedAt: Long,
    val workerStartedAt: Long,
    val audioReadyAt: Long,
    val recognizedAt: Long,
    val processedAt: Long,
    val deliveredAt: Long,
) {
    val totalMs: Long get() = elapsed(deliveredAt, stoppedAt)
    // Work queued before finalization is recognition of earlier phrases, not microphone stopping.
    val speechMs: Long get() = elapsed(workerStartedAt, stoppedAt) + elapsed(recognizedAt, audioReadyAt)
    val microphoneMs: Long get() = elapsed(audioReadyAt, workerStartedAt)
    val cleanupMs: Long get() = elapsed(processedAt, recognizedAt)
    val deliveryMs: Long get() = elapsed(deliveredAt, processedAt)

    fun describe(historyMs: Long): String =
        "Last Stop to text: $totalMs ms\n" +
            "Speech: $speechMs ms · Microphone: $microphoneMs ms · Cleanup: $cleanupMs ms · " +
            "Typing/display: $deliveryMs ms\nHistory saved afterwards: ${historyMs.coerceAtLeast(0)} ms"

    private fun elapsed(end: Long, start: Long): Long = (end - start).coerceAtLeast(0)
}
