package com.flowdictation.android

import android.content.Context
import android.content.res.AssetManager
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineMoonshineModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.OfflineWhisperModelConfig
import com.k2fsa.sherpa.onnx.OfflineTransducerModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import android.os.SystemClock

/**
 * Offline speech-to-text via sherpa-onnx [OfflineRecognizer].
 *
 * Models live in APK assets under `models/<model-id>/` (see ModelCatalog and
 * scripts/fetch-deps.sh). Loading is lazy: the recognizer for the selected
 * model is created on first use, so the app (history, settings) works even
 * when model files are missing — transcription just reports a clear error.
 */
class Transcriber(appContext: Context) {
    private val assets: AssetManager = appContext.assets
    private val importedModels = ModelImportRepository(appContext)
    private val sileroVad = SileroVadRepository(appContext)
    private val prefs = Prefs(appContext)

    private var recognizer: OfflineRecognizer? = null
    private var loadedModelId: String? = null
    private var vad: Vad? = null
    private var loadedSensitiveVad: Boolean? = null
    private var utterance: IncrementalVadSession? = null

    var lastError: String? = null
        private set

    val isLoaded: Boolean
        get() = recognizer != null

    val currentModelId: String?
        get() = loadedModelId

    /**
     * Ensures the recognizer for [modelId] is loaded. Returns false (with
     * [lastError] set) when model files are missing or native init fails.
     */
    @Synchronized
    fun ensureLoaded(modelId: String): Boolean {
        cancelUtterance()
        if (recognizer != null && loadedModelId == modelId && loadedSensitiveVad == prefs.sensitiveVad) return true
        release()
        lastError = null
        val spec = ModelCatalog.spec(modelId)
        if (spec == null) {
            lastError = "Unknown model: $modelId"
            return false
        }
        val files = try {
            resolveFiles(spec)
        } catch (e: Exception) {
            lastError = "Cannot read model assets for '$modelId': ${e.message}"
            return false
        }
        if (files == null) {
            lastError = "This speech model is not installed. Open Settings to download a model."
            return false
        }
        return try {
            val started = SystemClock.elapsedRealtime()
            val external = importedModels.directory(spec.id).isDirectory
            recognizer = OfflineRecognizer(
                assetManager = if (external) null else assets,
                config = configuration(spec, files),
            )
            if (spec.kind == ModelKind.PARAKEET) {
                val vadModel = sileroVad.resolve()
                vad = Vad(assetManager = if (vadModel.fromAssets) assets else null, config = VadModelConfig(
                    sileroVadModelConfig = SileroVadModelConfig(model = vadModel.path,
                        threshold = if (prefs.sensitiveVad) 0.35f else 0.5f,
                        minSilenceDuration = 0.5f, minSpeechDuration = 0.25f, maxSpeechDuration = 20f),
                    numThreads = 1,
                ))
            }
            loadedModelId = modelId
            loadedSensitiveVad = prefs.sensitiveVad
            prefs.lastModelLoadMs = SystemClock.elapsedRealtime() - started
            prefs.lastLoadedModel = spec.displayName
            true
        } catch (e: Throwable) {
            // Throwable, not Exception: a JNI UnsatisfiedLinkError must also
            // report cleanly instead of crashing with the service stuck busy.
            lastError = "Failed to load model '$modelId': ${e.message}"
            release()
            false
        }
    }

    /**
     * Transcribes 16 kHz mono samples. Throws IllegalStateException when no
     * model is loaded; throws on empty audio.
     */
    @Synchronized
    fun transcribe(samples: FloatArray, sampleRate: Int = 16000): String {
        cancelUtterance()
        val rec = recognizer
            ?: throw IllegalStateException(lastError ?: "Recognizer not loaded")
        require(samples.isNotEmpty()) { "No audio captured" }
        val detector = vad ?: return decode(rec, samples, sampleRate)
        require(sampleRate == 16000) { "Parakeet pause detection requires 16 kHz audio" }
        detector.reset()
        val text = ArrayList<String>()
        try {
            var offset = 0
            while (offset < samples.size) {
                // Silero requires 512-sample windows. Pad only the final partial window.
                val window = FloatArray(512)
                val count = minOf(window.size, samples.size - offset)
                samples.copyInto(window, endIndex = offset + count, startIndex = offset)
                detector.acceptWaveform(window)
                drain(rec, detector, text, sampleRate)
                offset += count
            }
            detector.flush()
            drain(rec, detector, text, sampleRate)
            return joinSegments(text)
        } finally { detector.reset() }
    }

    /** Start feeding complete microphone chunks into Parakeet's existing Silero VAD. */
    @Synchronized
    fun beginUtterance(): Boolean {
        cancelUtterance()
        val detector = vad ?: return false
        if (recognizer == null) return false
        return try {
            detector.reset()
            utterance = IncrementalVadSession()
            true
        } catch (_: Throwable) {
            runCatching { detector.reset() }
            utterance = null
            false
        }
    }

    /** Accept any chunk length; only complete 512-sample windows reach Silero. */
    @Synchronized
    fun acceptUtteranceAudio(samples: FloatArray) {
        val session = utterance ?: return
        if (samples.isEmpty() || session.requiresBatchFallback) return
        val rec = recognizer ?: run {
            session.fail(IllegalStateException("Recognizer released during dictation"))
            return
        }
        val detector = vad ?: run {
            session.fail(IllegalStateException("VAD released during dictation"))
            return
        }
        try {
            session.audio.append(samples) { window ->
                detector.acceptWaveform(window)
                drain(rec, detector, session.text, SAMPLE_RATE)
            }
        } catch (failure: Throwable) {
            // Stop can safely restart with the full captured audio if JNI fails
            // while processing an early window.
            session.fail(failure)
        }
    }

    /**
     * Finish incremental VAD and decode. The final capture is authoritative:
     * append only audio not already accepted, or restart from the full sample
     * array if the streamed count is inconsistent or any native step failed.
     */
    @Synchronized
    fun finishUtterance(fullSamples: FloatArray): String {
        val session = utterance ?: return transcribe(fullSamples)
        utterance = null
        val detector = vad
        try {
            require(fullSamples.isNotEmpty()) { "No audio captured" }
            val rec = recognizer ?: throw IllegalStateException(lastError ?: "Recognizer not loaded")
            if (detector == null) return transcribe(fullSamples)
            if (session.requiresBatchFallback) return transcribe(fullSamples)
            if (!session.audio.reconcile(fullSamples) { window ->
                    detector.acceptWaveform(window)
                    drain(rec, detector, session.text, SAMPLE_RATE)
                }) {
                return transcribe(fullSamples)
            }
            session.audio.finishWindow()?.let { window ->
                detector.acceptWaveform(window)
                drain(rec, detector, session.text, SAMPLE_RATE)
            }
            detector.flush()
            drain(rec, detector, session.text, SAMPLE_RATE)
            return joinSegments(session.text)
        } catch (_: Throwable) {
            // A failed incremental pass must not lose words or partial audio.
            return transcribe(fullSamples)
        } finally {
            runCatching { detector?.reset() }
            session.clear()
        }
    }

    /** Drop all partial words and samples, then leave the detector ready again. */
    @Synchronized
    fun cancelUtterance() {
        val session = utterance
        utterance = null
        session?.clear()
        runCatching { vad?.reset() }
    }

    private fun drain(
        rec: OfflineRecognizer,
        detector: Vad,
        text: MutableList<String>,
        sampleRate: Int,
    ) {
        while (!detector.empty()) {
            val segment = detector.front()
            try {
                if (segment.samples.isNotEmpty()) text.add(decode(rec, segment.samples, sampleRate))
            } finally { detector.pop() }
        }
    }

    private fun joinSegments(text: List<String>): String =
        text.filter { it.isNotBlank() }.joinToString(" ").trim()

    private fun decode(rec: OfflineRecognizer, samples: FloatArray, sampleRate: Int): String {
        val stream = rec.createStream()
        try {
            stream.acceptWaveform(samples, sampleRate)
            rec.decode(stream)
            return rec.getResult(stream).text.trim()
        } finally {
            stream.release()
        }
    }

    @Synchronized
    fun release() {
        cancelUtterance()
        try { vad?.release() } catch (_: Exception) {}
        vad = null
        try {
            recognizer?.release()
        } catch (ignored: Exception) {
        }
        recognizer = null
        loadedModelId = null
        loadedSensitiveVad = null
    }

    private fun resolveFiles(spec: ModelSpec): ModelImportFiles? {
        val imported = importedModels.directory(spec.id)
        if (imported.isDirectory) {
            return ModelImportFiles.resolve(spec, imported.list()?.toList().orEmpty()) {
                java.io.File(imported, it).absolutePath
            }
        }
        val dir = ModelCatalog.assetDir(spec.id)
        return ModelImportFiles.resolve(spec, assets.list(dir)?.toList().orEmpty()) { "$dir/$it" }
    }

    companion object {
        private const val SAMPLE_RATE = 16000

        /** Opens and releases a staged model before it becomes selectable. */
        fun validateImport(spec: ModelSpec, directory: java.io.File) {
            val files = ModelImportFiles.resolve(spec, directory.list()?.toList().orEmpty()) {
                java.io.File(directory, it).absolutePath
            } ?: error("The archive is missing required speech-model files.")
            OfflineRecognizer(config = configuration(spec, files)).release()
        }

        private fun configuration(spec: ModelSpec, files: ModelImportFiles): OfflineRecognizerConfig {
            val model = OfflineModelConfig(numThreads = 2, tokens = files.tokens)
            when (spec.kind) {
                ModelKind.PARAKEET -> {
                    model.transducer = OfflineTransducerModelConfig(
                        encoder = files.encoder, decoder = files.decoder, joiner = files.joiner,
                    )
                    model.modelType = "nemo_transducer"
                }
                ModelKind.WHISPER -> model.whisper = OfflineWhisperModelConfig(
                    encoder = files.encoder, decoder = files.decoder,
                    language = Prefs.LANGUAGE, task = "transcribe",
                )
                ModelKind.MOONSHINE -> model.moonshine = OfflineMoonshineModelConfig(
                    preprocessor = files.preprocessor, encoder = files.encoder,
                    uncachedDecoder = files.uncachedDecoder, cachedDecoder = files.cachedDecoder,
                )
            }
            // 1.4 deliberately uses post-ASR vocabulary replacement for every engine.
            // The 1.13.8 Kotlin API exposes hotwordsFile/Score and modelingUnit/bpeVocab,
            // and upstream NeMo TDT has a beam-search context graph. However our installed
            // Parakeet inputs contain tokens.txt, not a verified BPE encoder vocabulary,
            // and Android biasing accuracy/stability has not been validated. Do not switch
            // decoders or feed unencoded words into native code. Vocabulary changes are
            // read after recognition, so they need no model reload and respect idle unload.
            return OfflineRecognizerConfig(modelConfig = model)
        }
    }
}
