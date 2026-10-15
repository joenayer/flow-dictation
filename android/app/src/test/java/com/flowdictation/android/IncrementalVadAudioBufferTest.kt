package com.flowdictation.android

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class IncrementalVadAudioBufferTest {
    @Test
    fun arbitraryChunksEmitOnlyCompleteWindowsAndKeepOrder() {
        val audio = IncrementalVadAudioBuffer(windowSize = 4)
        val windows = mutableListOf<FloatArray>()

        audio.append(floatArrayOf(1f, 2f, 3f)) { windows.add(it) }
        assertTrue(windows.isEmpty())
        audio.append(floatArrayOf(4f)) { windows.add(it) }
        audio.append(floatArrayOf(5f, 6f, 7f, 8f, 9f)) { windows.add(it) }

        assertEquals(2, windows.size)
        assertArrayEquals(floatArrayOf(1f, 2f, 3f, 4f), windows[0], 0f)
        assertArrayEquals(floatArrayOf(5f, 6f, 7f, 8f), windows[1], 0f)
        assertEquals(9, audio.sampleCount)
        assertArrayEquals(floatArrayOf(9f, 0f, 0f, 0f), audio.finishWindow()!!, 0f)
    }

    @Test
    fun finalCaptureAddsMissingSamplesWhenLastChunkCallbackWasNotDelivered() {
        val audio = IncrementalVadAudioBuffer(windowSize = 4)
        val windows = mutableListOf<FloatArray>()
        val full = floatArrayOf(1f, 2f, 3f, 4f, 5f, 6f)

        audio.append(full.copyOfRange(0, 3)) { windows.add(it) }
        assertTrue(audio.reconcile(full) { windows.add(it) })

        assertEquals(1, windows.size)
        assertArrayEquals(floatArrayOf(1f, 2f, 3f, 4f), windows.single(), 0f)
        assertEquals(full.size, audio.sampleCount)
        assertArrayEquals(floatArrayOf(5f, 6f, 0f, 0f), audio.finishWindow()!!, 0f)
    }

    @Test
    fun streamedAudioLongerThanFinalCaptureRequestsBatchFallback() {
        val audio = IncrementalVadAudioBuffer(windowSize = 4)
        val windows = mutableListOf<FloatArray>()
        audio.append(floatArrayOf(1f, 2f, 3f, 4f)) { windows.add(it) }

        assertFalse(audio.reconcile(floatArrayOf(1f, 2f, 3f)) { windows.add(it) })
        assertEquals(4, audio.sampleCount)
        assertEquals(1, windows.size)
    }

    @Test
    fun emptyAndExactFinalBoundariesDoNotCreatePaddedWindows() {
        val audio = IncrementalVadAudioBuffer(windowSize = 4)
        assertNull(audio.finishWindow())
        audio.append(floatArrayOf(1f, 2f, 3f, 4f)) {}
        assertNull(audio.finishWindow())
    }

    @Test
    fun cancellationAndNativeFailureStateCannotLeakIntoNextTake() {
        val cancelled = IncrementalVadSession()
        cancelled.text += "discard this"
        cancelled.audio.append(floatArrayOf(1f, 2f)) {}
        cancelled.clear()
        assertTrue(cancelled.text.isEmpty())
        assertEquals(0, cancelled.audio.sampleCount)

        val failed = IncrementalVadSession()
        failed.text += "partial result"
        failed.fail(IllegalStateException("native decode failed"))
        assertTrue(failed.requiresBatchFallback)
        failed.clear()

        val nextTake = IncrementalVadSession()
        assertFalse(nextTake.requiresBatchFallback)
        assertTrue(nextTake.text.isEmpty())
        assertEquals(0, nextTake.audio.sampleCount)
        nextTake.audio.append(floatArrayOf(7f, 8f)) {}
        assertEquals(2, nextTake.audio.sampleCount)
    }
}
