package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test

class HistoryTextTest {
    private val entries = listOf(
        HistoryEntry(1, 1000, "Send the NorthStar samples.", 2000, "tiny"),
        HistoryEntry(2, 2000, "Book the meeting\nBring notes.", 3000, "tiny"),
    )
    @Test fun searchIsCaseInsensitiveAndTrimsWhitespace() {
        assertEquals(listOf(entries[0]), HistoryText.search(entries, "  NorthStar "))
    }
    @Test fun emptyQueryReturnsAllAndMissingQueryReturnsNone() {
        assertEquals(entries, HistoryText.search(entries, " "))
        assertTrue(HistoryText.search(entries, "missing").isEmpty())
    }
    @Test fun exportPreservesFullTextAndLineBreaks() {
        val result = HistoryText.format(entries)
        assertTrue(result.contains(entries[0].text))
        assertTrue(result.contains(entries[1].text))
        assertTrue(result.indexOf(entries[0].text) < result.indexOf(entries[1].text))
        assertEquals("", HistoryText.format(emptyList()))
    }
}
