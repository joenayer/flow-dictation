package com.flowdictation.android

import android.content.Context
import android.os.SystemClock
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Device-only batch/equivalence and timing check. Timings separate work done
 * while audio is being fed from the Stop-tail flush; they are not live-mic or
 * Samsung performance claims.
 */
@RunWith(AndroidJUnit4::class)
class TranscriberIncrementalLatencyDeviceTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val target: Context get() = instrumentation.targetContext

    @Test
    fun parakeetBatchAndIncrementalMatchOnOfficialAndLongStitchedAudio() {
        val spec = requireNotNull(ModelCatalog.spec(ModelCatalog.RECOMMENDED_MODEL_ID))
        val repository = ModelImportRepository(target)
        val destination = repository.directory(spec.id)
        val source = if (repository.isAvailable(spec)) destination else findStagedModel()
        val installedByTest = !repository.isAvailable(spec)
        if (installedByTest) copyModelFiles(spec, source, destination)

        val fixture = InstrumentationRegistry.getArguments().getString(ARG_AUDIO)
            ?.let(::File)
            ?: File(source, "test_wavs/0.wav")
        val transcriber = Transcriber(target)
        try {
            assertTrue("Official Parakeet reference WAV must be available", fixture.isFile)
            assertTrue(
                "Parakeet and Silero must load: ${transcriber.lastError}",
                transcriber.ensureLoaded(spec.id),
            )
            val official = readPcm16MonoWavAt16k(fixture)
            val cases = listOf(
                AudioCase("official-7s", official),
                AudioCase("stitched-60s-final-phrase", stitchEndingWithPhrase(official, 60)),
                AudioCase("stitched-180s-final-phrase", stitchEndingWithPhrase(official, 180)),
            )

            for (case in cases) {
                val batchStart = SystemClock.elapsedRealtimeNanos()
                val batchText = transcriber.transcribe(case.samples)
                val batchMs = elapsedMs(batchStart)

                assertTrue("Incremental Parakeet session should start", transcriber.beginUtterance())
                val feedStart = SystemClock.elapsedRealtimeNanos()
                var offset = 0
                var chunkIndex = 0
                // Mirror the 512-sample AudioRecord cadence, with irregular
                // boundaries included to exercise the carry-over buffer.
                val chunkSizes = intArrayOf(512, 384, 640, 512)
                while (offset < case.samples.size) {
                    val count = minOf(chunkSizes[chunkIndex++ % chunkSizes.size], case.samples.size - offset)
                    transcriber.acceptUtteranceAudio(case.samples.copyOfRange(offset, offset + count))
                    offset += count
                }
                val preStopMs = elapsedMs(feedStart)
                val finishStart = SystemClock.elapsedRealtimeNanos()
                val incrementalText = transcriber.finishUtterance(case.samples)
                val stopTailMs = elapsedMs(finishStart)
                val totalMs = preStopMs + stopTailMs

                assertTrue(
                    "Batch and incremental results must match for ${case.name}",
                    batchText == incrementalText,
                )
                Log.i(
                    TAG,
                    "case=${case.name} audioMs=${case.samples.size * 1000L / SAMPLE_RATE} " +
                        "batchMs=$batchMs preStopFeedMs=$preStopMs stopTailMs=$stopTailMs " +
                        "incrementalTotalMs=$totalMs resultMatches=true",
                )

                if (case.name == "official-7s") {
                    val prefixSamples = 511
                    assertTrue("Parakeet tail-reconciliation session should start", transcriber.beginUtterance())
                    transcriber.acceptUtteranceAudio(case.samples.copyOfRange(0, prefixSamples))
                    val recoveredText = transcriber.finishUtterance(case.samples)
                    assertTrue(
                        "Full capture reconciliation must recover audio after a 511-sample queued prefix",
                        recoveredText == batchText,
                    )
                    Log.i(TAG, "case=official-7s missing-callback-suffix=true prefixSamples=$prefixSamples resultMatches=true")
                }
            }

            assertCancelNewTakeAndReleaseReload(transcriber, official)
        } finally {
            transcriber.release()
            if (installedByTest) destination.deleteRecursively()
        }
    }

    private fun findStagedModel(): File {
        val argument = InstrumentationRegistry.getArguments().getString(ARG_MODEL_DIR)
        val root = argument?.let(::File)
            ?: File(target.getExternalFilesDir(null) ?: target.filesDir, "flow-parakeet")
        val candidates = listOf(root, File(root, MODEL_ARCHIVE_DIR))
        return candidates.firstOrNull { directory ->
            ModelImportFiles.resolve(
                requireNotNull(ModelCatalog.spec(ModelCatalog.RECOMMENDED_MODEL_ID)),
                directory.list()?.toList().orEmpty(),
            ) { File(directory, it).path } != null
        } ?: throw AssertionError("Extracted Parakeet model files were not staged under $root")
    }

    private fun copyModelFiles(spec: ModelSpec, source: File, destination: File) {
        val files = requireNotNull(ModelImportFiles.resolve(spec, source.list()?.toList().orEmpty()) {
            File(source, it).path
        })
        destination.mkdirs()
        files.paths().forEach { path ->
            val file = File(path)
            assertTrue("Required model file is empty: ${file.name}", file.isFile && file.length() > 0)
            file.copyTo(File(destination, file.name), overwrite = true)
        }
    }

    /** Repeats natural speech with one-second gaps and places leftover silence first. */
    private fun stitchEndingWithPhrase(phrase: FloatArray, seconds: Int): FloatArray {
        val sampleCount = seconds * SAMPLE_RATE
        val out = FloatArray(sampleCount)
        val standardPause = SAMPLE_RATE
        val stride = phrase.size + standardPause
        val repeats = ((sampleCount + standardPause) / stride).coerceAtLeast(1)
        val usedSamples = repeats * phrase.size + (repeats - 1) * standardPause
        var offset = sampleCount - usedSamples
        repeat(repeats) {
            phrase.copyInto(out, destinationOffset = offset)
            offset += phrase.size + standardPause
        }
        return out
    }

    private fun assertCancelNewTakeAndReleaseReload(transcriber: Transcriber, official: FloatArray) {
        val partial = official.copyOfRange(0, minOf(official.size, 2 * SAMPLE_RATE))
        assertTrue("Parakeet take should start before cancellation", transcriber.beginUtterance())
        feed(transcriber, partial)
        transcriber.cancelUtterance()

        val silence = FloatArray(2 * SAMPLE_RATE)
        val batchSilence = transcriber.transcribe(silence)
        assertTrue("Silence batch reference should be blank", batchSilence.isBlank())
        assertTrue("New take should start after cancellation", transcriber.beginUtterance())
        feed(transcriber, silence)
        val cancelledThenNew = transcriber.finishUtterance(silence)
        assertTrue(
            "Cancelled speech must not leak into the next silent take",
            cancelledThenNew.isBlank() && cancelledThenNew == batchSilence,
        )

        assertTrue("Take should start before native release", transcriber.beginUtterance())
        feed(transcriber, partial)
        transcriber.release()
        assertFalse("Released recognizer should not accept a new take", transcriber.beginUtterance())
        assertTrue("Recognizer should load again after release", transcriber.ensureLoaded(ModelCatalog.RECOMMENDED_MODEL_ID))
        assertTrue("New take should start after native reload", transcriber.beginUtterance())
        feed(transcriber, silence)
        val afterReload = transcriber.finishUtterance(silence)
        assertTrue(
            "Partial speech before release must not leak after native reload",
            afterReload.isBlank() && afterReload == batchSilence,
        )
    }

    private fun feed(transcriber: Transcriber, samples: FloatArray) {
        var offset = 0
        var chunkIndex = 0
        val chunkSizes = intArrayOf(512, 384, 640, 512)
        while (offset < samples.size) {
            val count = minOf(chunkSizes[chunkIndex++ % chunkSizes.size], samples.size - offset)
            transcriber.acceptUtteranceAudio(samples.copyOfRange(offset, offset + count))
            offset += count
        }
    }

    private fun readPcm16MonoWavAt16k(file: File): FloatArray {
        val bytes = file.readBytes()
        assertTrue("WAV is too short", bytes.size >= 44)
        assertEqualsAscii("RIFF", bytes, 0)
        assertEqualsAscii("WAVE", bytes, 8)
        var format = 0
        var channels = 0
        var rate = 0
        var bits = 0
        var dataOffset = -1
        var dataLength = 0
        var offset = 12
        while (offset + 8 <= bytes.size) {
            val tag = String(bytes, offset, 4, Charsets.US_ASCII)
            val size = littleInt(bytes, offset + 4).coerceAtLeast(0)
            val start = offset + 8
            if (start + size > bytes.size) break
            when (tag) {
                "fmt " -> {
                    format = littleShort(bytes, start)
                    channels = littleShort(bytes, start + 2)
                    rate = littleInt(bytes, start + 4)
                    bits = littleShort(bytes, start + 14)
                }
                "data" -> {
                    dataOffset = start
                    dataLength = size
                    break
                }
            }
            offset = start + size + (size and 1)
        }
        assertTrue("Fixture must be PCM", format == 1 && bits == 16)
        assertTrue("Fixture must be mono 16 kHz", channels == 1 && rate == SAMPLE_RATE)
        assertTrue("WAV data chunk is missing", dataOffset >= 0 && dataLength > 0)
        val frames = dataLength / (channels * 2)
        return FloatArray(frames) { frame ->
            val index = dataOffset + frame * 2
            val sample = ((bytes[index + 1].toInt() shl 8) or (bytes[index].toInt() and 0xff)).toShort()
            sample / 32768f
        }
    }

    private fun elapsedMs(startNanos: Long): Long =
        (SystemClock.elapsedRealtimeNanos() - startNanos) / 1_000_000L

    private fun assertEqualsAscii(expected: String, bytes: ByteArray, offset: Int) {
        assertTrue(String(bytes, offset, expected.length, Charsets.US_ASCII) == expected)
    }

    private fun littleShort(bytes: ByteArray, start: Int): Int =
        (bytes[start].toInt() and 0xff) or ((bytes[start + 1].toInt() and 0xff) shl 8)

    private fun littleInt(bytes: ByteArray, start: Int): Int =
        littleShort(bytes, start) or (littleShort(bytes, start + 2) shl 16)

    private data class AudioCase(val name: String, val samples: FloatArray)

    private companion object {
        const val ARG_MODEL_DIR = "parakeetModelDir"
        const val ARG_AUDIO = "parakeetAudio"
        const val MODEL_ARCHIVE_DIR = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
        const val SAMPLE_RATE = 16_000
        const val TAG = "FlowASRBenchmark"
    }
}
