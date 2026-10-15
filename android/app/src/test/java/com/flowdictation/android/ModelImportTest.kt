package com.flowdictation.android

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FilterInputStream
import java.nio.file.Files
import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream
import org.apache.commons.compress.archivers.tar.TarConstants
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorOutputStream
import org.junit.Assert.*
import org.junit.Test

class ModelImportTest {
    private val spec = ModelCatalog.spec("whisper-tiny.en")!!
    private val root = "sherpa-onnx-whisper-tiny.en"
    private val required = listOf("tiny.en-encoder.int8.onnx", "tiny.en-decoder.int8.onnx", "tiny.en-tokens.txt")
    private fun archive(names: List<String>, symbolic: Boolean = false, payloadSize: Int = 16): ByteArray {
        val bytes = ByteArrayOutputStream()
        BZip2CompressorOutputStream(bytes).use { compressed ->
            TarArchiveOutputStream(compressed).use { tar ->
                names.forEach { name ->
                    val entry = if (symbolic) TarArchiveEntry(name, TarConstants.LF_SYMLINK).apply { linkName = "/outside" }
                        else TarArchiveEntry(name, true).apply { size = payloadSize.toLong() }
                    tar.putArchiveEntry(entry)
                    if (!symbolic) tar.write(ByteArray(payloadSize) { 1 })
                    tar.closeArchiveEntry()
                }
            }
        }
        return bytes.toByteArray()
    }
    private fun inFolder(block: (File) -> Unit) {
        val folder = Files.createTempDirectory("flow-model-test").toFile()
        try { block(folder) } finally { folder.deleteRecursively() }
    }
    private fun rejects(block: () -> Unit) {
        try { block(); fail("Invalid archive must be rejected") }
        catch (expected: IllegalStateException) { assertTrue(expected.message.orEmpty().isNotBlank()) }
        catch (expected: java.io.IOException) { assertTrue(expected.message.orEmpty().isNotBlank()) }
    }

    @Test fun validArchivePublishesOnlyInt8RequiredFilesAndCallsValidator() = inFolder { folder ->
        var validated = false
        val names = required.map { "$root/$it" } + "$root/tiny.en-encoder.onnx" + "$root/test_wavs/example.wav"
        val installed = ModelImportTransaction().install(ByteArrayInputStream(archive(names)), folder, listOf(spec)) { selected, stage ->
            assertEquals(spec, selected)
            assertEquals(required.toSet(), stage.list()!!.toSet())
            validated = true
        }
        assertEquals(spec, installed)
        assertTrue(validated)
        assertEquals(setOf(spec.id), folder.list()!!.toSet())
    }

    @Test fun validationFailureCleansStagingAndKeepsExistingModel() = inFolder { folder ->
        val working = File(folder, "working-default").apply { mkdir() }
        File(working, "keep").writeText("unchanged")
        rejects {
            ModelImportTransaction().install(ByteArrayInputStream(archive(required.map { "$root/$it" })), folder, listOf(spec)) { _, _ ->
                error("Native model validation failed")
            }
        }
        assertEquals(setOf("working-default"), folder.list()!!.toSet())
        assertEquals("unchanged", File(working, "keep").readText())
    }

    @Test fun installedModelCannotBeOverwritten() = inFolder { folder ->
        val existing = File(folder, spec.id).apply { mkdir() }
        File(existing, "keep").writeText("original")
        rejects { ModelImportTransaction().install(ByteArrayInputStream(archive(required.map { "$root/$it" })), folder, listOf(spec)) { _, _ -> fail("Must not validate a replacement") } }
        assertEquals("original", File(existing, "keep").readText())
        assertEquals(setOf(spec.id), folder.list()!!.toSet())
    }

    @Test fun traversalAbsolutePathsAndLinksAreRejected() {
        listOf("$root/../escape.onnx", "/$root/escape.onnx", "$root/evil\\path.onnx").forEach { path ->
            inFolder { stage -> rejects { ModelImportArchive().extract(ByteArrayInputStream(archive(listOf(path))), stage, listOf(spec)) } }
        }
        inFolder { stage -> rejects { ModelImportArchive().extract(ByteArrayInputStream(archive(listOf("$root/link"), symbolic = true)), stage, listOf(spec)) } }
    }

    @Test fun missingFilesWrongRootAndDuplicateNamesAreRejected() {
        listOf(listOf("$root/${required[0]}"), required.map { "unsupported/$it" },
            required.map { "$root/$it" } + "$root/${required[0]}").forEach { names ->
            inFolder { stage -> rejects { ModelImportArchive().extract(ByteArrayInputStream(archive(names)), stage, listOf(spec)) } }
        }
    }

    @Test fun expandedSizeAndEntryCountAreBounded() {
        inFolder { stage -> rejects { ModelImportArchive(expandedLimit = 2048).extract(ByteArrayInputStream(archive(required.map { "$root/$it" }, payloadSize = 8192)), stage, listOf(spec)) } }
        inFolder { stage -> rejects { ModelImportArchive(entryLimit = 1).extract(ByteArrayInputStream(archive(required.map { "$root/$it" })), stage, listOf(spec)) } }
    }

    @Test fun cancelledExtractionNeverPublishesAndCleansStaging() = inFolder { folder ->
        rejects { ModelImportTransaction(ModelImportArchive(cancelled = { true })).install(
            ByteArrayInputStream(archive(required.map { "$root/$it" })), folder, listOf(spec),
        ) { _, _ -> fail("Cancelled import must not validate") } }
        assertTrue(folder.list()!!.isEmpty())
    }


    @Test fun bitReaderUsesBufferedBlockReadsAndStillObservesCancellation() = inFolder { stage ->
        var singleReads = 0
        var blockReads = 0
        val input = object : FilterInputStream(ByteArrayInputStream(archive(required.map { "$root/$it" }))) {
            override fun read(): Int { singleReads++; return `in`.read() }
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
                blockReads++
                return `in`.read(bytes, offset, length)
            }
        }
        ModelImportArchive().extract(input, stage, listOf(spec))
        assertEquals("The bzip bit reader must not read the raw stream byte by byte", 0, singleReads)
        assertTrue("The raw stream must be refilled in blocks", blockReads > 0)
    }

    @Test fun cancellationAfterBufferedRefillStillCleansStaging() = inFolder { folder ->
        var cancel = false
        val parser = ModelImportArchive(cancelled = { cancel }, progress = { _, _ -> cancel = true })
        rejects { ModelImportTransaction(parser).install(ByteArrayInputStream(archive(required.map { "$root/$it" })), folder, listOf(spec)) { _, _ -> fail("Cancelled model must not validate") } }
        assertTrue(folder.list()!!.isEmpty())
    }

    @Test fun copiedArchiveDigestIsFromBytesAndTruncatedDownloadIsRejected() = inFolder { folder ->
        val target = File(folder, "archive")
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", ModelImportDownload.copyChecked(ByteArrayInputStream("abc".toByteArray()), target))
        rejects { ModelImportDownload.copyChecked(ByteArrayInputStream("abc".toByteArray()), target, expectedLength = 20) }
        rejects { ModelImportDownload.copyChecked(ByteArrayInputStream("abc".toByteArray()), target, cancelled = { true }) }
    }
}
