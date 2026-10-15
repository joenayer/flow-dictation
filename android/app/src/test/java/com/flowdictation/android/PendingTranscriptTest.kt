package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test

class PendingTranscriptTest {
    @Test fun completedDictationSurvivesAnAbsentEditorUntilAcknowledged() {
        val pending = PendingTranscript()
        pending.publish("Keep this offline dictation", 1200)
        val result = pending.peek()!!
        assertEquals("Keep this offline dictation", result.text)
        assertEquals(1200L, result.durationMs)
        // Showing the floating microphone or keeping edits must not consume it.
        assertEquals(result, pending.peek())
        pending.acknowledge(result)
        assertNull(pending.peek())
    }

    @Test fun oldEditorAcknowledgementCannotDropANewerDictation() {
        val pending = PendingTranscript()
        pending.publish("Earlier", 1000)
        val earlier = pending.peek()!!
        pending.publish("Newer", 2000)
        pending.acknowledge(earlier)
        assertEquals("Newer", pending.peek()!!.text)
    }

    @Test fun identicalWordsAndDurationStillHaveIndependentRecordingIdentity() {
        val pending = PendingTranscript()
        pending.publish("Same words", 2000)
        val earlier = pending.peek()!!
        pending.publish("Same words", 2000)
        pending.acknowledge(earlier)
        val newer = pending.peek()!!
        assertNotEquals(earlier.id, newer.id)
        pending.acknowledge(newer)
        assertNull(pending.peek())
    }
}
