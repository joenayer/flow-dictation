package com.flowdictation.android

/** One completed dictation retained in memory until the editor receives it.
 * No file is written when history is disabled; process death clears this slot.
 */
class PendingTranscript {
    data class Result(val id: Long, val text: String, val durationMs: Long)
    private var nextId = 0L
    private var pending: Result? = null

    @Synchronized
    fun publish(text: String, durationMs: Long) {
        pending = Result(++nextId, text, durationMs)
    }

    @Synchronized
    fun peek(): Result? = pending

    @Synchronized
    fun acknowledge(result: Result) {
        if (pending?.id == result.id) pending = null
    }
}
