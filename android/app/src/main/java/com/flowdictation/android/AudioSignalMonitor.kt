package com.flowdictation.android

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sqrt

/** Microphone-level hints, measured before gain. Noise is an estimate, not speech recognition. */
enum class AudioSignalStatus(val label: String) {
    LISTENING("Listening"),
    TOO_QUIET("Speak a little louder"),
    NOISY("Background may be noisy"),
    CLIPPING("Microphone is too loud"),
}

/** One bounded pass over each PCM frame, with no per-frame allocations. */
internal class AudioSignalMonitor(private val sampleRate: Int = 16000) {
    var level = 0f
        private set
    var status = AudioSignalStatus.LISTENING
        private set
    private var power = 0.0
    private var quietSamples = 0L
    private var noisySamples = 0L
    private var clippedSamples = 0L

    fun reset() {
        level = 0f
        status = AudioSignalStatus.LISTENING
        power = 0.0
        quietSamples = 0
        noisySamples = 0
        clippedSamples = 0
    }

    fun process(samples: ShortArray, count: Int) {
        require(count in 0..samples.size)
        if (count == 0) return
        var sum = 0.0
        var peak = 0.0
        var crossings = 0
        var clipped = 0
        var previous = samples[0].toInt()
        for (i in 0 until count) {
            val raw = samples[i].toInt()
            val sample = raw / 32768.0
            sum += sample * sample
            peak = maxOf(peak, abs(sample))
            if (abs(raw) >= 32112) clipped++
            if (i > 0 && ((raw >= 0) != (previous >= 0))) crossings++
            previous = raw
        }
        val framePower = sum / count
        val blend = 1.0 - exp(-count / (sampleRate * if (framePower > power) 0.045 else 0.16))
        power += (framePower - power) * blend
        val rms = sqrt(power)
        val db = if (rms > 0) 20 * log10(rms) else -120.0
        // Useful movement even with a quiet mic. Digital silence stays flat.
        level = ((db + 65) / 55).coerceIn(0.0, 1.0).pow(0.8).toFloat()
        quietSamples = if (db < -47) quietSamples + count else 0
        val frameRms = sqrt(framePower)
        val noisy = db > -35 && crossings.toDouble() / count > 0.22 &&
            frameRms > 0 && peak / frameRms < 5
        noisySamples = if (noisy) noisySamples + count else 0
        clippedSamples = if (clipped.toDouble() / count >= 0.02) clippedSamples + count else 0
        status = when {
            clippedSamples >= sampleRate / 5 -> AudioSignalStatus.CLIPPING
            noisySamples >= sampleRate * 2 -> AudioSignalStatus.NOISY
            quietSamples >= sampleRate * 3 / 2 -> AudioSignalStatus.TOO_QUIET
            else -> AudioSignalStatus.LISTENING
        }
    }
}
