package com.flowdictation.android

import java.io.File
import java.io.BufferedInputStream
import java.io.FilterInputStream
import java.io.InputStream
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorInputStream

/** Imports only official catalog archive layouts into an unpublished private directory. */
class ModelImportArchive(
    private val compressedLimit: Long = 512L * 1024 * 1024,
    private val expandedLimit: Long = 1024L * 1024 * 1024,
    private val entryLimit: Int = 512,
    private val cancelled: () -> Boolean = { false },
    private val progress: (Long, Long) -> Unit = { _, _ -> },
) {
    fun extract(input: InputStream, stage: File, allowed: List<ModelSpec>): ModelSpec {
        check(stage.isDirectory && stage.list().isNullOrEmpty()) { "Import staging folder is not empty." }
        var spec: ModelSpec? = null
        val seen = HashSet<String>()
        var count = 0
        TarArchiveInputStream(BoundedInput(BZip2CompressorInputStream(
            // The bzip bit reader reads single bytes. Buffer *outside* the
            // bounded raw stream to avoid millions of FileInputStream syscalls;
            // the bounds/cancellation checks still run for every refill.
            BufferedInputStream(BoundedInput(input, compressedLimit, cancelled) {
                progress(it, allowed.singleOrNull()?.archiveSizeBytes ?: -1)
            }, 64 * 1024), true,
        ), expandedLimit, cancelled)).use { tar ->
            while (true) {
                val entry = tar.nextEntry ?: break
                check(++count <= entryLimit) { "This archive contains too many files." }
                val path = entry.name.removePrefix("./").trimEnd('/')
                val parts = path.split('/')
                check(path.isNotEmpty() && !path.startsWith('/') && !path.contains('\\') &&
                    parts.none { it.isEmpty() || it == "." || it == ".." || it.contains(':') }
                ) { "This archive contains an unsafe file path." }
                check(entry.isDirectory || entry.isFile) { "Links and special files are not supported." }
                check(!entry.isSymbolicLink && !entry.isLink && !entry.isSparse) { "Links and sparse files are not supported." }
                check(seen.add(path)) { "This archive contains duplicate file names." }
                val matching = allowed.firstOrNull {
                    parts[0] == it.downloadUrl.substringAfterLast('/').removeSuffix(".tar.bz2")
                } ?: error("Choose a supported speech-model .tar.bz2 downloaded using Get a model.")
                check(spec == null || spec?.id == matching.id) { "This archive mixes different models." }
                spec = matching
                check(entry.size in 0..expandedLimit) { "This archive contains a file that is too large." }
                if (entry.isDirectory) continue
                // Samples/readme files are ignored. Only direct model inputs can be installed.
                val name = parts.last()
                val keep = parts.size == 2 && (name.endsWith(".onnx") || name.endsWith("tokens.txt"))
                if (keep) {
                    check(entry.size > 0) { "This archive contains an empty speech-model file." }
                    check(stage.usableSpace > entry.size + 32L * 1024 * 1024) { "Not enough phone storage to import this model." }
                    File(stage, name).outputStream().use { output -> tar.copyTo(output, 64 * 1024) }
                }
            }
        }
        val selected = spec ?: error("This archive does not contain a supported speech model.")
        val files = ModelImportFiles.resolve(selected, stage.list()?.toList().orEmpty()) {
            File(stage, it).absolutePath
        } ?: error("The archive is incomplete. Download the complete .tar.bz2 and try again.")
        val required = files.paths().toSet()
        stage.listFiles()?.filter { it.absolutePath !in required }?.forEach {
            check(it.delete()) { "Could not finish preparing the imported model." }
        }
        return selected
    }

    /** Counts bytes even while tar skips ignored entries, so archive bombs remain bounded. */
    private class BoundedInput(input: InputStream, private val limit: Long, private val cancelled: () -> Boolean,
                               private val progress: (Long) -> Unit = {}) : FilterInputStream(input) {
        private var count = 0L
        private fun counted(n: Int): Int {
            check(!cancelled()) { "Cancelled" }
            if (n > 0) {
                count += n
                check(count <= limit) { "This speech-model archive is too large." }
                progress(count)
            }
            return n
        }
        override fun read(): Int = super.read().also { if (it >= 0) counted(1) }
        override fun read(bytes: ByteArray, offset: Int, length: Int): Int = counted(`in`.read(bytes, offset, length))
        override fun skip(n: Long): Long {
            val buffer = ByteArray(8192)
            var total = 0L
            while (total < n) {
                val got = read(buffer, 0, minOf(buffer.size.toLong(), n - total).toInt())
                if (got < 0) break
                total += got
            }
            return total
        }
    }
}
