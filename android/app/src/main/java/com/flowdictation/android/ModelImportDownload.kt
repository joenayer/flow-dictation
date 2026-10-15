package com.flowdictation.android

import java.io.File
import java.io.InputStream
import java.net.URL
import java.security.MessageDigest
import javax.net.ssl.HttpsURLConnection

/** Downloads only pinned HTTPS model files after an explicit user action. */
class ModelImportDownload(
    private val openHttps: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection },
) {
    fun download(spec: ModelSpec, target: File, cancelled: () -> Boolean, progress: (Long, Long) -> Unit): String =
        downloadPinned(spec.downloadUrl, spec.archiveSha256 ?: error("This model does not have a verified download checksum yet."),
            target, MAX_BYTES, spec.archiveSizeBytes, cancelled, progress)

    /** Resumes a verified catalog file into [target], retaining a partial file after interruption. */
    fun downloadPinned(
        address: String,
        sha256: String,
        target: File,
        maxBytes: Long,
        expectedBytes: Long,
        cancelled: () -> Boolean,
        progress: (Long, Long) -> Unit,
    ): String {
        check(sha256.matches(Regex("[a-f0-9]{64}"))) { "This download does not have a verified checksum yet." }
        target.parentFile?.mkdirs()
        if (target.length() > maxBytes || (expectedBytes > 0 && target.length() > expectedBytes)) target.delete()
        if (expectedBytes > 0 && target.length() == expectedBytes) {
            if (fileSha256(target) == sha256) return sha256
            target.delete()
        }
        var url = URL(address)
        repeat(6) { hop ->
            check(!cancelled()) { "Cancelled" }
            check(url.protocol == "https" && url.host in HOSTS) { "Unsupported model download address." }
            val connection = openHttps(url)
            try {
                connection.instanceFollowRedirects = false
                connection.connectTimeout = 15_000
                connection.readTimeout = 15_000
                connection.setRequestProperty("Accept-Encoding", "identity")
                val offset = target.length()
                if (offset > 0) connection.setRequestProperty("Range", "bytes=$offset-")
                when (connection.responseCode) {
                    301, 302, 303, 307, 308 -> {
                        check(hop < 5) { "Too many download redirects. Try again later." }
                        url = URL(url, connection.getHeaderField("Location") ?: error("Missing download location."))
                    }
                    200, 206 -> {
                        val partialResponse = connection.responseCode == 206
                        val append = partialResponse && offset > 0
                        if (partialResponse) {
                            val range = connection.getHeaderField("Content-Range")
                            val parsed = range?.let { Regex("^bytes (\\d+)-(\\d+)/(\\d+)$").matchEntire(it) }
                            val rangeStart = parsed?.groupValues?.get(1)?.toLongOrNull()
                            val rangeEnd = parsed?.groupValues?.get(2)?.toLongOrNull()
                            val rangeTotal = parsed?.groupValues?.get(3)?.toLongOrNull()
                            val validRange = rangeStart != null && rangeEnd != null && rangeTotal != null &&
                                rangeStart == offset && rangeEnd >= rangeStart && rangeEnd < rangeTotal &&
                                rangeEnd == rangeTotal - 1 && (expectedBytes <= 0 || rangeTotal == expectedBytes)
                            if (!validRange) {
                                target.delete()
                                error("The model server returned an invalid resume response. Try again.")
                            }
                        }
                        if (!append) target.delete()
                        val start = if (append) offset else 0L
                        val total = if (expectedBytes > 0) expectedBytes else {
                            val contentRange = connection.getHeaderField("Content-Range")
                            contentRange?.substringAfter('/')?.toLongOrNull() ?: connection.contentLengthLong
                        }
                        val remaining = connection.contentLengthLong
                        if (total > maxBytes) {
                            target.delete()
                            error("The model download is too large.")
                        }
                        check(remaining < 0 || start + remaining <= maxBytes) { "The model download is too large." }
                        val digest = connection.inputStream.use { copyResume(it, target, append, total, maxBytes, cancelled, progress) }
                        if (total >= 0) check(target.length() == total) { "The model download is incomplete. Reopen setup to resume it." }
                        if (expectedBytes > 0) check(target.length() == expectedBytes) { "The model download length did not match. Try again." }
                        if (digest != sha256) {
                            target.delete()
                            error("The model checksum did not match. Download it again.")
                        }
                        return digest
                    }
                    416 -> {
                        target.delete()
                        error("The saved partial download could not be resumed. Tap again to start a fresh download.")
                    }
                    else -> error("The model server returned ${connection.responseCode}. Try again later.")
                }
            } finally { connection.disconnect() }
        }
        error("Could not reach the model download.")
    }

    companion object {
        const val MAX_BYTES = 512L * 1024 * 1024
        private val HOSTS = setOf("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com")

        private fun fileSha256(file: File): String {
            val hash = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) { val read = input.read(buffer); if (read < 0) break; if (read > 0) hash.update(buffer, 0, read) }
            }
            return hash.digest().joinToString("") { "%02x".format(it) }
        }

        /** Shared with file import: bounded full-file digest, never a filename-based trust check. */
        fun copyChecked(input: InputStream, target: File, expectedLength: Long = -1,
                        cancelled: () -> Boolean = { false }, progress: (Long, Long) -> Unit = { _, _ -> }): String {
            target.parentFile?.mkdirs()
            return copyResume(input, target, false, expectedLength, MAX_BYTES, cancelled, progress)
        }

        private fun copyResume(input: InputStream, target: File, append: Boolean, total: Long, maxBytes: Long,
                               cancelled: () -> Boolean, progress: (Long, Long) -> Unit): String {
            val hash = MessageDigest.getInstance("SHA-256")
            val count = if (append) target.length() else 0L
            if (append) target.inputStream().use { old ->
                val prior = ByteArray(64 * 1024)
                while (true) { val read = old.read(prior); if (read < 0) break; if (read > 0) hash.update(prior, 0, read) }
            }
            var bytes = count
            val buffer = ByteArray(64 * 1024)
            (if (append) java.io.FileOutputStream(target, true) else target.outputStream()).use {
                    while (true) {
                        check(!cancelled()) { "Cancelled" }
                        val read = input.read(buffer)
                        if (read < 0) break
                        if (read == 0) continue
                        bytes += read
                        check(bytes <= maxBytes) { "This model archive is too large." }
                        check(target.usableSpace > read + 32L * 1024 * 1024) { "Not enough phone storage for the model download." }
                        it.write(buffer, 0, read)
                        hash.update(buffer, 0, read)
                        progress(bytes, total)
                    }
            }
            check(bytes > 0 && (total < 0 || bytes == total)) { "The model download is incomplete. Reopen setup to resume it." }
            return hash.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
