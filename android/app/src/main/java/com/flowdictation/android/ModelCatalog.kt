package com.flowdictation.android

/** Which sherpa-onnx model family a catalog entry uses. */
enum class ModelKind {
    WHISPER,
    MOONSHINE,
    PARAKEET,
}

/**
 * One downloadable on-device English model.
 *
 * @param id Directory name under assets/models/ and the persisted setting value.
 * @param displayName Shown in Settings.
 * @param kind sherpa-onnx config family to build.
 * @param downloadUrl Tarball URL (see README for versions/licenses).
 * @param approxSizeMb Approximate extracted footprint, for the Settings info line.
 * @param blurb One-line size/accuracy tradeoff note.
 */
data class ModelSpec(
    val id: String,
    val displayName: String,
    val kind: ModelKind,
    val downloadUrl: String,
    val approxSizeMb: Int,
    val blurb: String,
    /** SHA-256 of the official archive, verified before imported/downloaded models are used. */
    val archiveSha256: String? = null,
    val license: String = "MIT",
    val archiveSizeBytes: Long = 0,
    val installationSpaceMb: Int = approxSizeMb,
)

/** v1 model catalog. English-only, offline. */
object ModelCatalog {
    const val RECOMMENDED_MODEL_ID = "nemo-parakeet-tdt-0.6b-v2-int8"
    const val DEFAULT_MODEL_ID = RECOMMENDED_MODEL_ID

    private const val ASR_MODELS =
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

    val models: List<ModelSpec> = listOf(
        ModelSpec(
            id = "nemo-parakeet-tdt-0.6b-v2-int8",
            displayName = "NVIDIA Parakeet TDT 0.6B v2 int8 (recommended)",
            kind = ModelKind.PARAKEET,
            downloadUrl = "$ASR_MODELS/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
            approxSizeMb = 661,
            blurb = "Recommended English model. Downloads separately; Silero detects pauses to divide speech into shorter sections. Requires more memory than Tiny models.",
            archiveSizeBytes = 482468385,
            installationSpaceMb = 1800,
            archiveSha256 = "157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad",
            license = "CC-BY-4.0",
        ),
        ModelSpec(
            id = "moonshine-tiny-en-int8",
            displayName = "Moonshine Tiny (downloadable)",
            kind = ModelKind.MOONSHINE,
            downloadUrl = "$ASR_MODELS/sherpa-onnx-moonshine-tiny-en-int8.tar.bz2",
            approxSizeMb = 120,
            blurb = "Compact legacy model. English-only. Matches the Linux fallback engine.",
            archiveSha256 = "d5fe6ec4334fef36255b2a4010412cad4c007e33103fec62fb5d17cad88086f2",
        ),
        ModelSpec(
            id = "whisper-tiny.en",
            displayName = "Whisper Tiny.en",
            kind = ModelKind.WHISPER,
            downloadUrl = "$ASR_MODELS/sherpa-onnx-whisper-tiny.en.tar.bz2",
            approxSizeMb = 104,
            blurb = "Compact alternative model. Accuracy and processing time depend on your speech and phone.",
            archiveSizeBytes = 118071777,
            installationSpaceMb = 450,
            archiveSha256 = "2bd6cf965c8bb3e068ef9fa2191387ee63a9dfa2a4e37582a8109641c20005dd",
        ),
        ModelSpec(
            id = "whisper-base.en",
            displayName = "Whisper Base.en",
            kind = ModelKind.WHISPER,
            downloadUrl = "$ASR_MODELS/sherpa-onnx-whisper-base.en.tar.bz2",
            // Verified retained int8 files: 160,626,066 bytes.
            approxSizeMb = 161,
            blurb = "Larger alternative that may process more slowly. Accuracy depends on your speech and phone.",
            archiveSizeBytes = 208576005,
            installationSpaceMb = 750,
            archiveSha256 = "475bc7052ce299c007f6d5d5407ba8601f819a2867f6eecee510ed17df581542",
        ),
    )

    fun spec(id: String): ModelSpec? = models.find { it.id == id }
    fun recommended(): ModelSpec = requireNotNull(spec(RECOMMENDED_MODEL_ID))

    /** Asset subdirectory for a model id, e.g. "models/moonshine-tiny-en-int8". */
    fun assetDir(id: String): String = "models/$id"
}
