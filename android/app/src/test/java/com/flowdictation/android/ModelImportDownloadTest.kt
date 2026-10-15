package com.flowdictation.android

import java.io.ByteArrayInputStream
import java.io.File
import java.net.URL
import java.nio.file.Files
import java.security.MessageDigest
import java.security.Principal
import java.security.cert.Certificate
import java.util.ArrayDeque
import javax.net.ssl.HttpsURLConnection
import javax.security.auth.x500.X500Principal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelImportDownloadTest {
    private val bytes = "abcdef".toByteArray()
    private val digest get() = sha256(bytes)
    private val url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/test.onnx"

    @Test fun retriesInterruptedDownloadWithExactByteRangeAndKeepsArchive() = inFolder { folder ->
        val target = File(folder, "partial")
        val first = FakeResponse(200, bytes.copyOfRange(0, 3), contentLength = bytes.size.toLong())
        val resumed = FakeResponse(206, bytes.copyOfRange(3, 6), mapOf("Content-Range" to "bytes 3-5/6"), 3)
        val calls = ArrayDeque(listOf(first, resumed))
        val downloader = ModelImportDownload { requested ->
            assertEquals("github.com", requested.host)
            calls.removeFirst().connection(requested)
        }

        try {
            downloader.downloadPinned(url, digest, target, 100, bytes.size.toLong(), { false }) { _, _ -> }
            throw AssertionError("Short first response should be rejected")
        } catch (failure: IllegalStateException) {
            assertTrue(failure.message.orEmpty().contains("incomplete"))
        }
        assertEquals("abc", target.readText())

        assertEquals(digest, downloader.downloadPinned(url, digest, target, 100, bytes.size.toLong(), { false }) { _, _ -> })
        assertEquals("bytes=3-", resumed.requestedRange)
        assertEquals("abcdef", target.readText())
        assertTrue(calls.isEmpty())
    }

    @Test fun serverThatIgnoresRangeRestartsFromByteZero() = inFolder { folder ->
        val target = File(folder, "partial").apply { writeBytes("abc".toByteArray()) }
        val response = FakeResponse(200, bytes, contentLength = bytes.size.toLong())
        val downloader = ModelImportDownload { response.connection(it) }

        assertEquals(digest, downloader.downloadPinned(url, digest, target, 100, bytes.size.toLong(), { false }) { _, _ -> })
        assertEquals("bytes=3-", response.requestedRange)
        assertEquals("abcdef", target.readText())
    }

    @Test fun completeVerifiedCacheReturnsWithoutOpeningNetwork() = inFolder { folder ->
        val target = File(folder, "complete").apply { writeBytes(bytes) }
        var calls = 0
        val downloader = ModelImportDownload {
            calls++
            throw AssertionError("A verified complete cache should not need a request")
        }

        assertEquals(digest, downloader.downloadPinned(url, digest, target, 100, bytes.size.toLong(), { false }) { _, _ -> })
        assertEquals(0, calls)
    }

    @Test fun corruptCompleteCacheIsRedownloadedAndBadChecksumIsRejected() = inFolder { folder ->
        val target = File(folder, "complete").apply { writeBytes("xxxxxx".toByteArray()) }
        val response = FakeResponse(200, "xxxxxx".toByteArray(), contentLength = bytes.size.toLong())
        val downloader = ModelImportDownload { response.connection(it) }

        try {
            downloader.downloadPinned(url, digest, target, 100, bytes.size.toLong(), { false }) { _, _ -> }
            throw AssertionError("Wrong bytes must fail checksum validation")
        } catch (failure: IllegalStateException) {
            assertTrue(failure.message.orEmpty().contains("checksum"))
        }
        assertEquals(1, response.connections)
        assertFalse("Rejected cache must be removed", target.exists())
    }

    @Test fun productionAllowlistRejectsOtherHttpsHostsBeforeOpeningConnection() = inFolder { folder ->
        var calls = 0
        val downloader = ModelImportDownload {
            calls++
            throw AssertionError("Disallowed URL must be rejected before opening a connection")
        }
        try {
            downloader.downloadPinned("https://example.com/model", digest, File(folder, "partial"), 100,
                bytes.size.toLong(), { false }) { _, _ -> }
            throw AssertionError("Unapproved host should fail")
        } catch (failure: IllegalStateException) {
            assertTrue(failure.message.orEmpty().contains("Unsupported model download address"))
        }
        assertEquals(0, calls)
    }

    private fun inFolder(block: (File) -> Unit) {
        val folder = Files.createTempDirectory("flow-download-test").toFile()
        try { block(folder) } finally { folder.deleteRecursively() }
    }

    private fun sha256(input: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(input)
        .joinToString("") { "%02x".format(it) }

    private class FakeResponse(
        private val code: Int,
        private val body: ByteArray,
        private val headers: Map<String, String> = emptyMap(),
        contentLength: Long = body.size.toLong(),
    ) {
        private val declaredLength = contentLength
        var requestedRange: String? = null
            private set
        var connections = 0
            private set

        fun connection(url: URL): HttpsURLConnection {
            connections++
            return object : HttpsURLConnection(url) {
                override fun connect() = Unit
                override fun disconnect() = Unit
                override fun usingProxy(): Boolean = false
                override fun getResponseCode(): Int = code
                override fun getInputStream() = ByteArrayInputStream(body)
                override fun getHeaderField(name: String?): String? = when {
                    name == null -> null
                    name.equals("Content-Length", ignoreCase = true) -> declaredLength.toString()
                    else -> headers.entries.firstOrNull { it.key.equals(name, ignoreCase = true) }?.value
                }
                override fun setRequestProperty(key: String?, value: String?) {
                    super.setRequestProperty(key, value)
                    if (key.equals("Range", ignoreCase = true)) requestedRange = value
                }
                override fun getCipherSuite(): String = "TLS_FAKE_WITH_NULL_NULL"
                override fun getLocalCertificates(): Array<Certificate>? = null
                override fun getServerCertificates(): Array<Certificate> = emptyArray()
                override fun getPeerPrincipal(): Principal = X500Principal("CN=fake")
                override fun getLocalPrincipal(): Principal? = null
            }
        }
    }
}
