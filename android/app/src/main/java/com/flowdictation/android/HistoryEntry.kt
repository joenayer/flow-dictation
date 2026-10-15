package com.flowdictation.android

/** One saved dictation. Kept independent of Android for text-operation tests. */
data class HistoryEntry(
    val id: Long,
    val timestampMs: Long,
    val text: String,
    val durationMs: Long,
    val modelId: String,
    val originalText: String = text,
)
