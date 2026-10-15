package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppUpdateVersionTest {
    @Test
    fun ordersNumericPartsAndPrereleaseNumbers() {
        val versions = listOf("1.3.0-rc.2", "1.2.10", "1.3.0-rc.10", "1.3.0")
            .mapNotNull { text -> AppUpdateVersion.parse(text)?.let { text to it } }
        assertEquals(
            listOf("1.2.10", "1.3.0-rc.2", "1.3.0-rc.10", "1.3.0"),
            versions.sortedBy { it.second }.map { it.first },
        )
    }

    @Test
    fun picksNewestNewerReleaseAndIncludesPrereleases() {
        val selected = AppUpdateVersion.newestAfter(
            "1.2.0",
            listOf("1.1.9" to "old", "1.3.0-rc.2" to "preview", "1.3.0-rc.10" to "newest"),
        )
        assertEquals("newest", selected)
    }

    @Test
    fun finalReleaseIsNewerThanItsPrereleaseAndInvalidVersionDoesNotMatch() {
        assertEquals(
            "final",
            AppUpdateVersion.newestAfter("1.3.0-rc.10", listOf("1.3.0" to "final", "broken" to "invalid")),
        )
        assertNull(AppUpdateVersion.newestAfter("dev", listOf("2.0.0" to "candidate")))
    }

    @Test
    fun selectsArm64ForArm64DevicesAndUniversalOtherwise() {
        val arm64 = setOf(
            "Flow-Dictation-1.4.1-arm64-v8a.apk",
            "Flow-Dictation-1.4.1-universal.apk",
            "Flow-Dictation-1.4.1-x86_64.apk",
        )
        assertEquals(
            "Flow-Dictation-1.4.1-arm64-v8a.apk",
            AppUpdateAssetSelection.selectAssetName("1.4.1", listOf("arm64-v8a", "armeabi-v7a"), arm64),
        )
        assertEquals(
            "Flow-Dictation-1.4.1-universal.apk",
            AppUpdateAssetSelection.selectAssetName("1.4.1", listOf("armeabi-v7a"), arm64),
        )
    }

    @Test
    fun onlyAllowsLegacyAssetNameForPreSplitReleases() {
        assertEquals(
            "Flow-Dictation-1.4.0.apk",
            AppUpdateAssetSelection.selectAssetName("1.4.0", listOf("arm64-v8a"), setOf("Flow-Dictation-1.4.0.apk")),
        )
        assertNull(
            AppUpdateAssetSelection.selectAssetName("1.4.1", listOf("arm64-v8a"), setOf("Flow-Dictation-1.4.1.apk")),
        )
        assertNull(
            AppUpdateAssetSelection.selectAssetName("1.4.1", listOf("arm64-v8a"), setOf("Flow-Dictation-1.4.1-x86_64.apk")),
        )
    }

    @Test
    fun updaterPointsToPublicFlowReleasesAndRejectsOtherRepositoryAssetUrls() {
        assertEquals("https://api.github.com/repos/joenayer/flow-releases/releases", AppUpdatePublicSource.RELEASES_API_URL)
        assertEquals("https://github.com/joenayer/flow-releases/releases", AppUpdatePublicSource.RELEASES_PAGE)
        assertTrue(
            AppUpdatePublicSource.isTrustedAssetUrl(
                "https://github.com/joenayer/flow-releases/releases/download/android-v1.4.1/Flow-Dictation-1.4.1-arm64-v8a.apk",
                "android-v1.4.1",
                "Flow-Dictation-1.4.1-arm64-v8a.apk",
            ),
        )
        assertFalse(
            AppUpdatePublicSource.isTrustedAssetUrl(
                "https://github.com/example/other-app/releases/download/android-v1.4.1/Flow-Dictation-1.4.1-arm64-v8a.apk",
                "android-v1.4.1",
                "Flow-Dictation-1.4.1-arm64-v8a.apk",
            ),
        )
    }

}
