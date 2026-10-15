package com.flowdictation.android

/**
 * Turns arbitrary audio chunks into complete Silero windows without padding.
 * Only [finishWindow] may return a zero-padded final window.
 */
internal class IncrementalVadAudioBuffer(private val windowSize: Int = WINDOW_SIZE) {
    init { require(windowSize > 0) }

    private val pending = FloatArray(windowSize)
    private var pendingCount = 0

    /** Number of real samples accepted so far, excluding any final padding. */
    var sampleCount: Int = 0
        private set

    /** Add samples and call [onWindow] once for each newly completed window. */
    fun append(samples: FloatArray, onWindow: (FloatArray) -> Unit) {
        appendRange(samples, 0, samples.size, onWindow)
    }

    /**
     * Reconcile the streamed input with the final captured audio. If streaming
     * received more samples than the final capture contains, return false and
     * leave the caller to restart with the full batch. Otherwise only the
     * missing suffix is appended, exactly once.
     */
    fun reconcile(fullSamples: FloatArray, onWindow: (FloatArray) -> Unit): Boolean {
        if (sampleCount > fullSamples.size) return false
        appendRange(fullSamples, sampleCount, fullSamples.size, onWindow)
        return true
    }

    /** Return a padded final window only when a real partial window remains. */
    fun finishWindow(): FloatArray? {
        if (pendingCount == 0) return null
        return pending.copyOf()
    }

    fun reset() {
        pending.fill(0f)
        pendingCount = 0
        sampleCount = 0
    }

    private fun appendRange(
        samples: FloatArray,
        startIndex: Int,
        endIndex: Int,
        onWindow: (FloatArray) -> Unit,
    ) {
        require(startIndex in 0..endIndex && endIndex <= samples.size)
        sampleCount += endIndex - startIndex
        var sourceIndex = startIndex
        while (sourceIndex < endIndex) {
            val count = minOf(windowSize - pendingCount, endIndex - sourceIndex)
            samples.copyInto(
                destination = pending,
                destinationOffset = pendingCount,
                startIndex = sourceIndex,
                endIndex = sourceIndex + count,
            )
            pendingCount += count
            sourceIndex += count
            if (pendingCount == windowSize) {
                onWindow(pending.copyOf())
                pending.fill(0f)
                pendingCount = 0
            }
        }
    }

    companion object {
        const val WINDOW_SIZE = 512
    }
}

/** Per-take state kept separate so a failed or cancelled take cannot leak words. */
internal class IncrementalVadSession {
    val audio = IncrementalVadAudioBuffer()
    val text = ArrayList<String>()
    var failure: Throwable? = null
        private set

    val requiresBatchFallback: Boolean get() = failure != null

    fun fail(cause: Throwable) {
        if (failure == null) failure = cause
    }

    fun clear() {
        audio.reset()
        text.clear()
        failure = null
    }
}
