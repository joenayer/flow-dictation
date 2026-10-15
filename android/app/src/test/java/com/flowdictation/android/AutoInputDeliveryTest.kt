package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test

class AutoInputDeliveryTest {
    private val text = "Synthetic transcript for delivery tests"

    @Test fun everyBridgeResultIsAttemptedExactlyOnceAndRetained() {
        AutoInputResult.values().forEach { expected ->
            var insertCalls = 0
            var copyCalls = 0
            var copiedText: String? = null
            val delivery = AutoInputDeliveryPolicy.deliver(text,
                insert = { insertCalls++; expected },
                copy = { value -> copyCalls++; copiedText = value; true })

            assertEquals("insert calls for $expected", 1, insertCalls)
            assertEquals(expected, delivery.result)
            val confirmed = expected == AutoInputResult.INSERTED ||
                expected == AutoInputResult.INSERTED_CURSOR_UNCONFIRMED
            assertEquals(confirmed, delivery.inserted)
            assertEquals(!confirmed, delivery.copied)
            assertEquals(if (confirmed) 0 else 1, copyCalls)
            assertEquals(if (confirmed) null else text, copiedText)
            if (expected == AutoInputResult.INSERTION_UNCONFIRMED) {
                assertTrue(delivery.message.contains("Check the field before pasting"))
            }
            if (!confirmed && expected != AutoInputResult.EMPTY_TRANSCRIPT) {
                assertTrue(delivery.message.contains("clipboard") || delivery.message.contains("available in Flow"))
            }
        }
    }

    @Test fun insertionExceptionFallsBackOnceAndKeepsFailureResult() {
        var insertCalls = 0
        var copyCalls = 0
        val delivery = AutoInputDeliveryPolicy.deliver(text,
            insert = { insertCalls++; throw IllegalStateException("synthetic bridge failure") },
            copy = { copyCalls++; it == text })

        assertEquals(1, insertCalls)
        assertEquals(1, copyCalls)
        assertEquals(AutoInputResult.UNSUPPORTED, delivery.result)
        assertFalse(delivery.inserted)
        assertTrue(delivery.copied)
        assertTrue(delivery.message.contains("clipboard"))
    }

    @Test fun copyFailureAndExceptionSayTranscriptRemainsInFlow() {
        listOf<(String) -> Boolean>(
            { false },
            { throw IllegalStateException("synthetic clipboard failure") },
        ).forEach { copy ->
            val delivery = AutoInputDeliveryPolicy.deliver(text,
                insert = { AutoInputResult.NO_TARGET }, copy = copy)
            assertEquals(AutoInputResult.NO_TARGET, delivery.result)
            assertFalse(delivery.inserted)
            assertFalse(delivery.copied)
            assertTrue(delivery.message.contains("available in Flow"))
            assertFalse(delivery.message.contains("clipboard"))
        }
    }

    @Test fun confirmedInsertionNeverTouchesClipboardEvenIfCursorIsUnconfirmed() {
        listOf(AutoInputResult.INSERTED, AutoInputResult.INSERTED_CURSOR_UNCONFIRMED).forEach { result ->
            var copyCalls = 0
            val delivery = AutoInputDeliveryPolicy.deliver(text, insert = { result }, copy = { copyCalls++; true })
            assertTrue(delivery.inserted)
            assertFalse(delivery.copied)
            assertEquals(0, copyCalls)
        }
    }

    @Test fun emptyTranscriptIsNeverCopied() {
        var copyCalls = 0
        val delivery = AutoInputDeliveryPolicy.deliver("", insert = { AutoInputResult.EMPTY_TRANSCRIPT }, copy = { copyCalls++; true })

        assertEquals(AutoInputResult.EMPTY_TRANSCRIPT, delivery.result)
        assertFalse(delivery.inserted)
        assertFalse(delivery.copied)
        assertEquals(0, copyCalls)
    }
}
