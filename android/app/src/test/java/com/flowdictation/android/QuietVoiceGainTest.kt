package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.pow

class QuietVoiceGainTest {
    @Test fun boostsQuietVoiceTowardMinusTwentyDb() {
        val gain = QuietVoiceGain()
        var output = shortArrayOf()
        repeat(120) {
            output = ShortArray(512) { 1000 }
            gain.process(output, output.size, true)
        }
        assertEquals(3277.0, output.last().toDouble(), 50.0)
    }

    @Test fun boostNeverExceedsEighteenDb() {
        val gain = QuietVoiceGain()
        var output = shortArrayOf()
        repeat(200) {
            output = ShortArray(512) { 40 }
            gain.process(output, output.size, true)
        }
        assertTrue(output.all { it <= 40 * 10.0.pow(18.0 / 20.0) })
        assertTrue(output.last() > 250)
    }

    @Test fun limiterHandlesSuddenFullScaleInputWithoutWrapping() {
        val gain = QuietVoiceGain()
        repeat(200) { gain.process(ShortArray(512) { 40 }, 512, true) }
        val loud = ShortArray(512) { if (it % 2 == 0) Short.MAX_VALUE else Short.MIN_VALUE }
        gain.process(loud, loud.size, true)
        assertTrue(loud.indices.all { if (it % 2 == 0) loud[it] > 0 else loud[it] < 0 })
        assertTrue(loud.all { it > Short.MIN_VALUE && it < Short.MAX_VALUE })
    }

    @Test fun softLimiterDoesNotHardClipAnAmplifiedSpeechPeak() {
        val gain = QuietVoiceGain()
        repeat(200) { gain.process(ShortArray(512) { 40 }, 512, true) }
        val peak = ShortArray(512) { if (it % 2 == 0) 6000 else -6000 }
        gain.process(peak, peak.size, true)
        assertTrue(peak.all { it > Short.MIN_VALUE && it < Short.MAX_VALUE })
        assertTrue(peak[0] > 6000)
        assertTrue(peak[1] < -6000)
    }

    @Test fun disabledGainPreservesEverySample() {
        val gain = QuietVoiceGain()
        val original = shortArrayOf(0, 1, -1, 1500, -1500, Short.MAX_VALUE, Short.MIN_VALUE)
        val output = original.copyOf()
        gain.process(output, output.size, false)
        assertArrayEquals(original, output)
    }

    @Test fun silenceRemainsSilentAndQuietHintWaitsOneAndAHalfSeconds() {
        val gain = QuietVoiceGain()
        val silence = ShortArray(512)
        repeat(46) { gain.process(silence, silence.size, true) }
        assertFalse(gain.isQuiet)
        gain.process(silence, silence.size, true)
        assertTrue(gain.isQuiet)
        assertTrue(silence.all { it == 0.toShort() })
        gain.reset()
        assertFalse(gain.isQuiet)
    }

    @Test fun meterAndHintUseOriginalInputInsteadOfAmplifiedOutput() {
        val enabled = QuietVoiceGain()
        val disabled = QuietVoiceGain()
        repeat(70) {
            enabled.process(ShortArray(512) { 100 }, 512, true)
            disabled.process(ShortArray(512) { 100 }, 512, false)
        }
        assertTrue(enabled.isQuiet)
        assertEquals(disabled.level, enabled.level, 0.00001f)
        repeat(30) { enabled.process(ShortArray(512) { 5000 }, 512, true) }
        assertFalse(enabled.isQuiet)
    }

    @Test fun processingRespectsPartialReadBoundary() {
        val gain = QuietVoiceGain()
        val samples = ShortArray(512) { 1000 }
        gain.process(samples, 100, true)
        assertEquals(1000.toShort(), samples[100])
    }
}
