package com.flowdictation.android

import android.content.Context
import java.io.File
import java.security.MessageDigest

/** Pinned Silero download with the small APK asset retained as an offline fallback. */
class SileroVadRepository(private val context: Context) {
    val downloadedFile: File get() = File(File(context.filesDir, "speech-models"), FILE_NAME)

    fun isDownloaded(): Boolean = downloadedFile.isFile && runCatching {
        downloadedFile.length() == SIZE_BYTES && sha256(downloadedFile) == SHA256
    }.getOrDefault(false)

    /** A verified downloaded file wins; otherwise return the bundled asset path. */
    fun resolve(): VadModel {
        if (isDownloaded()) return VadModel(downloadedFile.absolutePath, fromAssets = false)
        check("silero_vad.onnx" in context.assets.list("").orEmpty()) { "Silero pause detection is not installed." }
        return VadModel("silero_vad.onnx", fromAssets = true)
    }

    data class VadModel(val path: String, val fromAssets: Boolean)

    companion object {
        const val URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
        const val SHA256 = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
        const val SIZE_BYTES = 643_854L
        const val FILE_NAME = "silero_vad.onnx"

        private fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(32 * 1024)
                while (true) { val count = input.read(buffer); if (count < 0) break; if (count > 0) digest.update(buffer, 0, count) }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
