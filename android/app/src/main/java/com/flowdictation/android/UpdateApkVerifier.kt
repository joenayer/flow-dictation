package com.flowdictation.android

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import java.io.File
import java.security.MessageDigest

/** Package, version, and certificate checks for an update APK before every install attempt. */
internal object UpdateApkVerifier {
    data class Installed(val versionCode: Long, val versionName: String)

    fun installedVersion(context: Context): Installed {
        val info = packageInfo(context, context.packageName, 0)
            ?: error("Could not read the installed Flow version.")
        return Installed(info.longVersionCodeCompat(), info.versionName.orEmpty())
    }

    fun verify(context: Context, apk: File, update: AppUpdater.UpdateInfo, expectedSha256: String) {
        check(apk.isFile && apk.length() in 1..MAX_APK_BYTES) { "The update file is missing or too large." }
        check(sha256(apk) == expectedSha256) { "The update file changed after it was checked." }

        val installed = packageInfo(context, context.packageName, SIGNING_FLAGS)
            ?: error("Could not read the installed Flow signing identity.")
        val candidate = packageManagerArchiveInfo(context, apk)
            ?: error("Android could not read the update file.")
        check(candidate.packageName == context.packageName) { "This update is for a different app." }
        check(candidate.longVersionCodeCompat() > installed.longVersionCodeCompat()) {
            "This update is not newer than the installed Flow version."
        }
        check(candidate.versionName == update.versionName) { "The update version does not match its GitHub release." }
        check(certificateDigests(installed) == certificateDigests(candidate)) {
            "This update was signed with a different key and cannot replace this Flow installation."
        }
    }

    private fun packageInfo(context: Context, packageName: String, flags: Int): PackageInfo? =
        if (Build.VERSION.SDK_INT >= 33) {
            context.packageManager.getPackageInfo(packageName, PackageManager.PackageInfoFlags.of(flags.toLong()))
        } else {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(packageName, flags)
        }

    private fun packageManagerArchiveInfo(context: Context, apk: File): PackageInfo? =
        if (Build.VERSION.SDK_INT >= 33) {
            context.packageManager.getPackageArchiveInfo(apk.absolutePath, PackageManager.PackageInfoFlags.of(SIGNING_FLAGS.toLong()))
        } else {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageArchiveInfo(apk.absolutePath, SIGNING_FLAGS)
        }

    private fun certificateDigests(info: PackageInfo): Set<String> {
        val certificates = if (Build.VERSION.SDK_INT >= 28) {
            info.signingInfo?.apkContentsSigners?.map { it.toByteArray() }
        } else {
            @Suppress("DEPRECATION")
            info.signatures?.map { it.toByteArray() }
        }
        check(!certificates.isNullOrEmpty()) { "The update has no verifiable signing certificate." }
        return certificates.map { bytes ->
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        }.toSet()
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val bytes = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(bytes)
                if (read < 0) break
                if (read > 0) digest.update(bytes, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    @Suppress("DEPRECATION")
    private fun PackageInfo.longVersionCodeCompat(): Long =
        if (Build.VERSION.SDK_INT >= 28) longVersionCode else versionCode.toLong()

    @Suppress("DEPRECATION")
    private val SIGNING_FLAGS: Int
        get() = if (Build.VERSION.SDK_INT >= 28) {
            PackageManager.GET_SIGNING_CERTIFICATES
        } else {
            PackageManager.GET_SIGNATURES
        }
    private const val MAX_APK_BYTES = 300L * 1024 * 1024
}
