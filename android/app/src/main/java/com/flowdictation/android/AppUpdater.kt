package com.flowdictation.android

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.lang.ref.WeakReference
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.UUID
import javax.net.ssl.HttpsURLConnection

/** Checks public GitHub releases and installs only a verified, newer Flow Preview APK. */
class AppUpdater(context: Context) {
    private val appContext = context.applicationContext

    data class UpdateInfo internal constructor(
        val tagName: String,
        val versionName: String,
        internal val assetUrl: String,
        internal val assetName: String,
        internal val expectedSha256: String? = null,
    )

    sealed class CheckResult {
        data class Available(val update: UpdateInfo) : CheckResult()
        data object UpToDate : CheckResult()
        /** The repository needs GitHub access; the releases page has been opened. */
        data object BrowserFallback : CheckResult()
        data class Failed(val message: String) : CheckResult()
    }

    sealed class InstallResult {
        data object Started : InstallResult()
        data class Failed(val message: String) : InstallResult()
    }

    /** The callback always runs on the main thread. This method performs all network work in the background. */
    fun checkForUpdates(activity: Activity, callback: (CheckResult) -> Unit) {
        val activityRef = WeakReference(activity)
        io.execute {
            val result = try {
                checkReleases()
            } catch (e: HttpStatusException) {
                if (e.statusCode == 401 || e.statusCode == 404) CheckResult.BrowserFallback
                else CheckResult.Failed("Could not check for updates. Try again later.")
            } catch (_: Exception) {
                CheckResult.Failed("Could not check for updates. Check your connection and try again.")
            }
            main.post {
                if (result == CheckResult.BrowserFallback) openReleasesPage(activityRef.get())
                callback(result)
            }
        }
    }

    /** Call after the user chooses to install an available update. */
    fun downloadAndInstall(
        activity: Activity,
        update: UpdateInfo,
        onProgress: (downloadedBytes: Long, totalBytes: Long) -> Unit = { _, _ -> },
        callback: (InstallResult) -> Unit,
    ) {
        val activityRef = WeakReference(activity)
        io.execute {
            var lastProgressAt = 0L
            val result = try {
                val directory = File(appContext.filesDir, UPDATE_DIRECTORY).apply { mkdirs() }
                check(directory.isDirectory) { "Could not prepare update storage." }
                val apk = File(directory, "flow-update-${UUID.randomUUID()}.apk")
                try {
                    val digest = downloadAsset(update, apk) { done, total ->
                        val now = SystemClock.elapsedRealtime()
                        if (done == total || now - lastProgressAt >= PROGRESS_INTERVAL_MS) {
                            lastProgressAt = now
                            main.post { onProgress(done, total) }
                        }
                    }
                    UpdateApkVerifier.verify(appContext, apk, update, digest)
                    check(update.expectedSha256 == null || digest.equals(update.expectedSha256, ignoreCase = true)) {
                        "The update file does not match GitHub's published SHA-256 digest."
                    }
                    val launch = Intent(appContext, UpdateInstallActivity::class.java)
                        .putExtra(UpdateInstallActivity.EXTRA_APK_PATH, apk.name)
                        .putExtra(UpdateInstallActivity.EXTRA_SHA256, digest)
                        .putExtra(UpdateInstallActivity.EXTRA_VERSION_NAME, update.versionName)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    main.post {
                        try {
                            val liveActivity = activityRef.get()
                            if (liveActivity != null && !liveActivity.isFinishing && liveActivity.hasWindowFocus()) {
                                launch.removeFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                liveActivity.startActivity(launch)
                                callback(InstallResult.Started)
                            } else if (UpdateInstallActivity.notifyUpdateReady(appContext, launch)) {
                                callback(InstallResult.Started)
                            } else {
                                apk.delete()
                                callback(InstallResult.Failed("Flow could not open the install step. Return to Flow and try again."))
                            }
                        } catch (_: Exception) {
                            apk.delete()
                            callback(InstallResult.Failed("Android could not open the install step."))
                        }
                    }
                    return@execute
                } catch (e: Exception) {
                    apk.delete()
                    throw e
                }
            } catch (e: Exception) {
                InstallResult.Failed(e.message?.takeIf { it.isNotBlank() } ?: "The update could not be installed.")
            }
            main.post { callback(result) }
        }
    }

    private fun checkReleases(): CheckResult {
        val current = UpdateApkVerifier.installedVersion(appContext)
        val releases = mutableListOf<Release>()
        var hasMorePages = false
        for (page in 1..MAX_RELEASE_PAGES) {
            val body = githubGet(
                "$RELEASES_API_URL?per_page=$RELEASES_PER_PAGE&page=$page",
                MAX_JSON_BYTES,
            )
            val array = JSONArray(body)
            for (index in 0 until array.length()) parseRelease(array.optJSONObject(index))?.let(releases::add)
            if (array.length() < RELEASES_PER_PAGE) {
                hasMorePages = false
                break
            }
            hasMorePages = true
        }
        if (hasMorePages) return CheckResult.Failed("There are too many releases to check safely. Try again later.")

        if (AppUpdateVersion.parse(current.versionName) == null) {
            return CheckResult.Failed("This Flow version cannot be compared with the releases.")
        }
        val newer = AppUpdateVersion.newestAfter(
            current.versionName,
            releases.map { it.versionName to it },
        )
            ?: return CheckResult.UpToDate
        return newer.update?.let { CheckResult.Available(it) }
            ?: CheckResult.Failed("A newer GitHub release is listed, but its update file is not available yet.")
    }

    private fun parseRelease(json: JSONObject?): Release? {
        if (json == null) return null
        val tag = json.optString("tag_name")
        val versionText = tag.removePrefix("android-v")
        if (!tag.startsWith("android-v")) return null
        if (AppUpdateVersion.parse(versionText) == null) return null
        val assets = json.optJSONArray("assets") ?: return Release(versionText, null)
        val availableNames = buildSet {
            for (index in 0 until assets.length()) {
                assets.optJSONObject(index)?.optString("name")?.takeIf(String::isNotBlank)?.let(::add)
            }
        }
        val expectedName = AppUpdateAssetSelection.selectAssetName(
            versionText,
            Build.SUPPORTED_ABIS.toList(),
            availableNames,
        ) ?: return Release(versionText, null)
        for (index in 0 until assets.length()) {
            val asset = assets.optJSONObject(index) ?: continue
            if (asset.optString("name") != expectedName) continue
            val url = asset.optString("browser_download_url")
            if (!AppUpdatePublicSource.isTrustedAssetUrl(url, tag, expectedName)) return Release(versionText, null)
            val digest = if (asset.isNull("digest")) null else asset.optString("digest")
            val expectedSha256 = when {
                digest == null -> null
                digest.matches(Regex("sha256:[a-fA-F0-9]{64}")) -> digest.substringAfter(':')
                else -> return Release(versionText, null)
            }
            return Release(
                versionText,
                UpdateInfo(tag, versionText, url, expectedName, expectedSha256),
            )
        }
        return Release(versionText, null)
    }

    private fun githubGet(address: String, maxBytes: Long): String {
        val parsed = URL(address)
        check(parsed.protocol == "https" && parsed.host == "api.github.com") { "Unsupported update address." }
        val connection = parsed.openConnection() as HttpsURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.setRequestProperty("Accept", "application/vnd.github+json")
            connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
            connection.setRequestProperty("User-Agent", "Flow-Android-Updater")
            val code = connection.responseCode
            if (code != 200) throw HttpStatusException(code)
            val deadline = SystemClock.elapsedRealtime() + API_REQUEST_TIMEOUT_MS
            return connection.inputStream.use { readTextBounded(it, connection.contentLengthLong, maxBytes, deadline) }
        } finally {
            connection.disconnect()
        }
    }

    private fun downloadAsset(update: UpdateInfo, target: File, progress: (Long, Long) -> Unit): String {
        var address = URL(update.assetUrl)
        val startedAt = SystemClock.elapsedRealtime()
        repeat(MAX_REDIRECTS + 1) { hop ->
            check(AppUpdatePublicSource.isTrustedAssetUrl(address.toString(), update.tagName, update.assetName)) {
                "The update download address is not trusted."
            }
            val connection = address.openConnection() as HttpsURLConnection
            try {
                connection.instanceFollowRedirects = false
                connection.connectTimeout = CONNECT_TIMEOUT_MS
                connection.readTimeout = READ_TIMEOUT_MS
                connection.setRequestProperty("Accept", "application/octet-stream")
                connection.setRequestProperty("User-Agent", "Flow-Android-Updater")
                when (val code = connection.responseCode) {
                    200 -> {
                        val length = connection.contentLengthLong
                        check(length == -1L || length in 1..MAX_APK_BYTES) { "The update file is missing or too large." }
                        return connection.inputStream.use { input ->
                            copyApk(input, target, length, startedAt, progress)
                        }
                    }
                    301, 302, 303, 307, 308 -> {
                        check(hop < MAX_REDIRECTS) { "Too many update download redirects." }
                        val location = connection.getHeaderField("Location") ?: error("The update download link is incomplete.")
                        address = URL(address, location)
                    }
                    else -> error("GitHub could not provide the update file (HTTP $code).")
                }
            } finally {
                connection.disconnect()
            }
        }
        error("Could not download the update file.")
    }

    private fun copyApk(
        input: InputStream,
        target: File,
        expectedLength: Long,
        startedAt: Long,
        progress: (Long, Long) -> Unit,
    ): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val bytes = ByteArray(64 * 1024)
        var count = 0L
        target.outputStream().buffered().use { output ->
            while (true) {
                check(SystemClock.elapsedRealtime() - startedAt <= DOWNLOAD_TIMEOUT_MS) {
                    "The update download took too long. Try again on a stronger connection."
                }
                val read = input.read(bytes)
                if (read < 0) break
                if (read == 0) continue
                count += read
                check(count <= MAX_APK_BYTES) { "The update file is too large." }
                check(target.usableSpace > read + MIN_FREE_SPACE_BYTES) { "There is not enough free space for the update." }
                output.write(bytes, 0, read)
                digest.update(bytes, 0, read)
                progress(count, expectedLength)
            }
        }
        check(expectedLength < 0 || count == expectedLength) { "The update download is incomplete. Try again." }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun readTextBounded(input: InputStream, expected: Long, limit: Long, deadline: Long): String {
        check(expected <= limit) { "The GitHub response is too large." }
        val bytes = input.readBytesBounded(limit, deadline)
        check(bytes.isNotEmpty() && (expected < 0 || bytes.size.toLong() == expected)) {
            "The GitHub response was incomplete."
        }
        return bytes.toString(Charsets.UTF_8)
    }

    private fun InputStream.readBytesBounded(limit: Long, deadline: Long): ByteArray {
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(16 * 1024)
        var count = 0L
        while (true) {
            check(SystemClock.elapsedRealtime() <= deadline) { "GitHub took too long to respond." }
            val read = read(buffer)
            if (read < 0) break
            if (read == 0) continue
            count += read
            check(count <= limit) { "The GitHub response is too large." }
            output.write(buffer, 0, read)
        }
        return output.toByteArray()
    }

    private fun openReleasesPage(activity: Activity?) {
        if (activity == null || activity.isFinishing) return
        runCatching {
            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(RELEASES_PAGE)))
        }
    }

    private data class Release(val versionName: String, val update: UpdateInfo?)
    private class HttpStatusException(val statusCode: Int) : Exception()

    companion object {
        const val RELEASES_PAGE = AppUpdatePublicSource.RELEASES_PAGE
        private const val OWNER = AppUpdatePublicSource.OWNER
        private const val REPO = AppUpdatePublicSource.REPO
        internal const val RELEASES_API_URL = AppUpdatePublicSource.RELEASES_API_URL
        private const val UPDATE_DIRECTORY = "updates"
        private const val RELEASES_PER_PAGE = 100
        private const val MAX_RELEASE_PAGES = 5
        private const val MAX_JSON_BYTES = 2L * 1024 * 1024
        private const val MAX_APK_BYTES = 300L * 1024 * 1024
        private const val MIN_FREE_SPACE_BYTES = 32L * 1024 * 1024
        private const val CONNECT_TIMEOUT_MS = 15_000
        private const val READ_TIMEOUT_MS = 20_000
        private const val API_REQUEST_TIMEOUT_MS = 45_000L
        private const val DOWNLOAD_TIMEOUT_MS = 5 * 60 * 1000L
        private const val PROGRESS_INTERVAL_MS = 400L
        private const val MAX_REDIRECTS = 5
        private val io = Executors.newSingleThreadExecutor { runnable -> Thread(runnable, "flow-update").apply { isDaemon = true } }
        private val main = Handler(Looper.getMainLooper())

    }
}
