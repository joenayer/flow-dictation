package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.file.Files
import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorOutputStream

class ParakeetModelTest {
    private val spec = ModelCatalog.spec("nemo-parakeet-tdt-0.6b-v2-int8")!!
    private val names = listOf("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")

    @Test fun requiredJoinerAndInt8FilesCannotBeSubstituted() {
        assertEquals(names.toSet(), ModelImportFiles.resolve(spec, names) { it }!!.paths().toSet())
        assertNull(ModelImportFiles.resolve(spec, names - "joiner.int8.onnx") { it })
        assertNull(ModelImportFiles.resolve(spec, names - "encoder.int8.onnx" + "encoder.onnx") { it })
        assertEquals(64, spec.archiveSha256!!.length)
        assertTrue(spec.archiveSizeBytes < ModelImportDownload.MAX_BYTES)
    }

    @Test fun officialLayoutExtractsAndKeepsOnlyRequiredInputs() {
        val buffer = ByteArrayOutputStream()
        BZip2CompressorOutputStream(buffer).use { compressed ->
            TarArchiveOutputStream(compressed).use { archive ->
                (names + "README.md" + "test_wavs/sample.wav").forEach { name ->
                    archive.putArchiveEntry(TarArchiveEntry("sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/$name").apply { size = 4 })
                    archive.write(byteArrayOf(1, 2, 3, 4))
                    archive.closeArchiveEntry()
                }
            }
        }
        val folder = Files.createTempDirectory("parakeet-import").toFile()
        try {
            assertEquals(spec, ModelImportArchive().extract(ByteArrayInputStream(buffer.toByteArray()), folder, listOf(spec)))
            assertEquals(names.toSet(), folder.list()!!.toSet())
        } finally { folder.deleteRecursively() }
    }
}
