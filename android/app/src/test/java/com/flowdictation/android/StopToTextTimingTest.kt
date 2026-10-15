package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StopToTextTimingTest {
    @Test fun backlogCountsAsSpeechAndHistoryIsOutsideStopToText() {
        val timing = StopToTextTiming(100, 300, 320, 700, 710, 750)
        assertEquals(650L, timing.totalMs)
        assertEquals(580L, timing.speechMs)
        assertEquals(20L, timing.microphoneMs)
        assertEquals(10L, timing.cleanupMs)
        assertEquals(40L, timing.deliveryMs)
        assertEquals(timing.totalMs, timing.speechMs + timing.microphoneMs + timing.cleanupMs + timing.deliveryMs)
        assertTrue(timing.describe(5000).contains("Stop to text: 650 ms"))
        assertTrue(timing.describe(5000).contains("afterwards: 5000 ms"))
    }
}
