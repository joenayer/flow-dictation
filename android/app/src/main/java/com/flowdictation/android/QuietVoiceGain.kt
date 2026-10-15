package com.flowdictation.android

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sqrt
import kotlin.math.tanh

/** Per-take, allocation-free PCM gain. Metering always measures the original microphone. */
internal class QuietVoiceGain(private val sampleRate: Int = 16000) {
    private var power = 0.0
    private var gain = 1.0
    private var quietSamples = 0L
    var isQuiet = false
        private set
    var level = 0f
        private set

    fun reset() {
        power = 0.0
        gain = 1.0
        quietSamples = 0
        isQuiet = false
        level = 0f
    }

    fun process(samples: ShortArray, count: Int, enabled: Boolean) {
        require(count in 0..samples.size)
        if (count == 0) return
        var sum = 0.0
        for (i in 0 until count) {
            val sample = samples[i] / 32768.0
            sum += sample * sample
        }
        val chunkPower = sum / count
        val blend = 1.0 - exp(-count / (sampleRate * 0.20))
        power += (chunkPower - power) * blend
        val rms = sqrt(power)
        val db = if (rms > 0) 20 * log10(rms) else -120.0
        level = ((db + 50) / 40).toFloat().coerceIn(0f, 1f)
        if (db < -42) quietSamples += count else quietSamples = 0
        isQuiet = quietSamples > sampleRate * 1.5
        if (!enabled) {
            gain = 1.0
            return
        }
        // Avoid lifting digital silence/noise. Never attenuate ordinary speech.
        val desired = if (rms < 0.00056) 1.0 else (0.1 / rms).coerceIn(1.0, MAX_GAIN)
        val startGain = gain
        // Fast retreat protects sudden loud speech; slower rise avoids pumping.
        val gainBlend = 1.0 - exp(-count / (sampleRate * if (desired < gain) 0.02 else 0.15))
        gain += (desired - gain) * gainBlend
        for (i in 0 until count) {
            val interpolatedGain = startGain + (gain - startGain) * (i + 1) / count
            val value = samples[i] / 32768.0 * interpolatedGain
            val magnitude = abs(value)
            val limited = if (magnitude <= 0.85) magnitude else
                // Keep headroom even when tanh rounds to 1 for a sudden loud peak.
                0.85 + 0.13 * tanh((magnitude - 0.85) / 0.13)
            val signed = if (value < 0) -limited else limited
            samples[i] = (signed * 32768).toInt().coerceIn(-32768, 32767).toShort()
        }
    }

    private companion object {
        val MAX_GAIN = 10.0.pow(18.0 / 20.0)
    }
}
