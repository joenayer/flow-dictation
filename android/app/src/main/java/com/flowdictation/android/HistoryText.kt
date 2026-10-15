package com.flowdictation.android

import java.text.DateFormat
import java.util.Date

/** Text operations independent of Android Views. */
object HistoryText {
    fun search(entries: List<HistoryEntry>, query: String): List<HistoryEntry> {
        val trimmed = query.trim()
        return if (trimmed.isEmpty()) entries else entries.filter { it.text.contains(trimmed, ignoreCase = true) }
    }
    fun format(entries: List<HistoryEntry>): String = entries.joinToString("\n\n---\n\n") {
        DateFormat.getDateTimeInstance().format(Date(it.timestampMs)) + "\n\n" + it.text
    }
}
