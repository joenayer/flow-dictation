package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin
import java.util.Random

class AudioSignalMonitorTest {
    private fun tone(amplitude: Double) = ShortArray(512) { (sin(2 * PI * 250 * it / 16000) * amplitude * 32767).toInt().toShort() }
    private fun feed(m: AudioSignalMonitor, samples: ShortArray, frames: Int) { repeat(frames) { m.process(samples, samples.size) } }

    @Test fun rawMeterRespondsToSoftAndLoudSpeechWithoutChangingSamples() {
        val levels = listOf(0.003, 0.03, 0.3).map { amplitude ->
            val samples = tone(amplitude)
            val original = samples.copyOf()
            val m = AudioSignalMonitor()
            feed(m, samples, 15)
            assertArrayEquals(original, samples)
            m.level
        }
        assertTrue(levels[0] > 0.1f)
        assertTrue(levels[0] < levels[1] && levels[1] < levels[2])
    }

    @Test fun SilenceIsFlatAndQuietWarningWaitsBeforeAppearing() {
        val m = AudioSignalMonitor()
        feed(m, ShortArray(512), 20)
        assertEquals(0f, m.level, 0f)
        assertEquals(AudioSignalStatus.LISTENING, m.status)
        feed(m, ShortArray(512), 30)
        assertEquals(AudioSignalStatus.TOO_QUIET, m.status)
    }

    @Test fun sustainedBroadbandSoundGetsTentativeNoiseHintButVoicedToneDoesNot() {
        val random = Random(11)
        val noise = ShortArray(512) { (random.nextInt(6000) - 3000).toShort() }
        val m = AudioSignalMonitor()
        feed(m, noise, 75)
        assertEquals(AudioSignalStatus.NOISY, m.status)
        val voice = AudioSignalMonitor()
        feed(voice, tone(0.3), 90)
        assertEquals(AudioSignalStatus.LISTENING, voice.status)
    }

    @Test fun shortNoiseBurstDoesNotMislabelTheWholeRecording() {
        val random = Random(12)
        val m = AudioSignalMonitor()
        feed(m, ShortArray(512) { (random.nextInt(10000) - 5000).toShort() }, 10)
        assertEquals(AudioSignalStatus.LISTENING, m.status)
        feed(m, tone(0.03), 2)
        assertEquals(AudioSignalStatus.LISTENING, m.status)
    }

    @Test fun clippingHasPriorityAndResetClearsTheTake() {
        val m = AudioSignalMonitor()
        feed(m, ShortArray(512) { if (it % 2 == 0) 32767 else -32768 }, 8)
        assertEquals(AudioSignalStatus.CLIPPING, m.status)
        m.reset()
        assertEquals(0f, m.level, 0f)
        assertEquals(AudioSignalStatus.LISTENING, m.status)
    }

    @Test fun partialFrameIgnoresUnusedLoudTail() {
        val m = AudioSignalMonitor()
        val frame = ShortArray(512) { if (it < 100) 0 else 32767 }
        repeat(300) { m.process(frame, 100) }
        assertEquals(0f, m.level, 0f)
        assertEquals(AudioSignalStatus.TOO_QUIET, m.status)
    }
}
