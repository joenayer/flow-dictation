package com.flowdictation.android

import java.net.URL

/** Semantic-version parsing and ordering kept separate so release selection can be tested without Android. */
internal data class AppUpdateVersion private constructor(
    private val numbers: List<Int>,
    private val prerelease: List<String>?,
) : Comparable<AppUpdateVersion> {
    override fun compareTo(other: AppUpdateVersion): Int {
        for (index in 0 until maxOf(numbers.size, other.numbers.size)) {
            val compared = (numbers.getOrNull(index) ?: 0).compareTo(other.numbers.getOrNull(index) ?: 0)
            if (compared != 0) return compared
        }
        if (prerelease == null) return if (other.prerelease == null) 0 else 1
        if (other.prerelease == null) return -1
        for (index in 0 until maxOf(prerelease.size, other.prerelease.size)) {
            val left = prerelease.getOrNull(index) ?: return -1
            val right = other.prerelease.getOrNull(index) ?: return 1
            val leftNumber = left.toIntOrNull()
            val rightNumber = right.toIntOrNull()
            val compared = when {
                leftNumber != null && rightNumber != null -> leftNumber.compareTo(rightNumber)
                leftNumber != null -> -1
                rightNumber != null -> 1
                else -> left.compareTo(right)
            }
            if (compared != 0) return compared
        }
        return 0
    }

    companion object {
        private val FORMAT = Regex("^([0-9]+(?:\\.[0-9]+){0,3})(?:-([0-9A-Za-z.-]+))?(?:\\+[0-9A-Za-z.-]+)?$")

        fun parse(text: String): AppUpdateVersion? {
            val match = FORMAT.matchEntire(text) ?: return null
            val numbers = match.groupValues[1].split('.').map { it.toIntOrNull() ?: return null }
            val prereleaseText = match.groupValues[2]
            if (prereleaseText.isNotEmpty() && prereleaseText.split('.').any { it.isEmpty() }) return null
            return AppUpdateVersion(numbers, prereleaseText.takeIf { it.isNotEmpty() }?.split('.'))
        }

        /** Returns the newest valid release strictly newer than the installed version. */
        fun <T> newestAfter(installedVersion: String, candidates: List<Pair<String, T>>): T? {
            val installed = parse(installedVersion) ?: return null
            return candidates.asSequence()
                .mapNotNull { (version, value) -> parse(version)?.let { it to value } }
                .filter { (version, _) -> version > installed }
                .maxByOrNull { it.first }
                ?.second
        }
    }
}

/** Chooses only assets whose ABI is known to be safe for this device. */
internal object AppUpdateAssetSelection {
    private val splitAssetVersion = AppUpdateVersion.parse("1.4.1")!!

    fun selectAssetName(versionName: String, supportedAbis: List<String>, availableNames: Set<String>): String? {
        val version = AppUpdateVersion.parse(versionName) ?: return null
        val prefix = "Flow-Dictation-$versionName"
        val candidates = buildList {
            if ("arm64-v8a" in supportedAbis) add("$prefix-arm64-v8a.apk")
            add("$prefix-universal.apk")
            // Releases before the ABI-split package used one generic APK name.
            if (version < splitAssetVersion) add("$prefix.apk")
        }
        return candidates.firstOrNull(availableNames::contains)
    }
}

/** Public update endpoints and the GitHub asset URL allowlist, kept Android-free for unit tests. */
internal object AppUpdatePublicSource {
    const val OWNER = "joenayer"
    const val REPO = "flow-releases"
    const val RELEASES_PAGE = "https://github.com/$OWNER/$REPO/releases"
    const val RELEASES_API_URL = "https://api.github.com/repos/$OWNER/$REPO/releases"

    fun isTrustedAssetUrl(address: String, tag: String, name: String): Boolean {
        val url = runCatching { URL(address) }.getOrNull() ?: return false
        if (url.protocol != "https" || url.userInfo != null || url.ref != null || (url.port != -1 && url.port != 443)) return false
        return when (url.host.lowercase()) {
            "github.com" -> url.path == "/$OWNER/$REPO/releases/download/$tag/$name"
            "release-assets.githubusercontent.com", "objects.githubusercontent.com" -> true
            else -> false
        }
    }
}
