package com.flowdictation.android

/** Required files for the two supported sherpa model families. */
data class ModelImportFiles(
    val encoder: String,
    val decoder: String,
    val preprocessor: String = "",
    val uncachedDecoder: String = "",
    val cachedDecoder: String = "",
    val tokens: String,
    val joiner: String = "",
) {
    fun paths(): List<String> = listOf(encoder, decoder, preprocessor, uncachedDecoder, cachedDecoder, tokens, joiner).filter { it.isNotEmpty() }
    companion object {
        fun resolve(spec: ModelSpec, names: List<String>, path: (String) -> String): ModelImportFiles? {
            val tokens = names.firstOrNull { it == "tokens.txt" }
                ?: names.firstOrNull { it.endsWith("tokens.txt", ignoreCase = true) }
                ?: return null

            return when (spec.kind) {
                ModelKind.PARAKEET -> {
                    val required = listOf("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
                    if (!names.containsAll(required)) return null
                    ModelImportFiles(encoder = path(required[0]), decoder = path(required[1]),
                        joiner = path(required[2]), tokens = path(required[3]))
                }
                ModelKind.WHISPER -> {
                    // NOTE: upstream whisper tarballs ship BOTH fp32 (*-encoder.onnx)
                    // and int8 (*-encoder.int8.onnx) files. Prefer int8: it is ~2x
                    // smaller and much faster on phone CPUs. Asset listing order is
                    // unspecified, so an unqualified firstOrNull could pick fp32.
                    val encoder = names.firstOrNull {
                        it.contains("encoder", ignoreCase = true) &&
                            it.contains("int8", ignoreCase = true) &&
                            it.endsWith(".onnx")
                    } ?: names.firstOrNull {
                        it.contains("encoder", ignoreCase = true) && it.endsWith(".onnx")
                    } ?: return null
                    val decoder = names.firstOrNull {
                        it.contains("decoder", ignoreCase = true) &&
                            it.contains("int8", ignoreCase = true) &&
                            it.endsWith(".onnx")
                    } ?: names.firstOrNull {
                        it.contains("decoder", ignoreCase = true) && it.endsWith(".onnx")
                    } ?: return null
                    ModelImportFiles(
                        encoder = path(encoder),
                        decoder = path(decoder),
                        tokens = path(tokens),
                    )
                }
                ModelKind.MOONSHINE -> {
                    // NOTE: match "uncached" before "cached": "uncached_decode…"
                    // contains the substring "cached".
                    val preprocessor = names.firstOrNull {
                        it.contains("preprocess", ignoreCase = true) && it.endsWith(".onnx")
                    } ?: return null
                    val encoder = names.firstOrNull {
                        it.contains("encode", ignoreCase = true) &&
                            !it.contains("decode", ignoreCase = true) &&
                            it.endsWith(".onnx")
                    } ?: return null
                    val uncached = names.firstOrNull {
                        it.contains("uncached", ignoreCase = true) && it.endsWith(".onnx")
                    } ?: return null
                    val cached = names.firstOrNull {
                        it.contains("cached", ignoreCase = true) &&
                            !it.contains("uncached", ignoreCase = true) &&
                            it.endsWith(".onnx")
                    } ?: return null
                    ModelImportFiles(
                        encoder = path(encoder),
                        decoder = "",
                        preprocessor = path(preprocessor),
                        uncachedDecoder = path(uncached),
                        cachedDecoder = path(cached),
                        tokens = path(tokens),
                    )
                }
            }
        }
    }
}
