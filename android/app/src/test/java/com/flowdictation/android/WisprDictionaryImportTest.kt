package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WisprDictionaryImportTest {
    private fun transfer(vararg rows: WisprDictionaryItem) = WisprDictionaryTransfer(rows.toList())

    @Test fun parsesWisprWordsAndCorrectionDirection() {
        val imported = WisprDictionaryPortableImport.parse(
            """{"format":"${WisprDictionaryPortableImport.FORMAT}","version":1,"entries":[{"phrase":"NorthStar","replacement":null},{"phrase":"north store","replacement":"NorthStar"}]}"""
        )

        assertEquals(
            transfer(WisprDictionaryItem("NorthStar", null), WisprDictionaryItem("north store", "NorthStar")),
            imported,
        )
        val preview = WisprDictionaryPortableImport.preview(emptyList(), imported)
        assertEquals(listOf(VocabularyEntry("NorthStar", listOf("north store"))), preview.additions)
        val vocabulary = WisprDictionaryPortableImport.apply(emptyList(), preview)
        assertEquals("Send it to NorthStar.", TranscriptProcessing.process(
            "Send it to north store.", vocabulary, commands = false, cleanup = false,
        ))
    }

    @Test fun correctionsWithOneDestinationKeepAllDistinctAliases() {
        val imported = transfer(
            WisprDictionaryItem("north star", "NorthStar"),
            WisprDictionaryItem("north store", "NorthStar"),
        )

        val preview = WisprDictionaryPortableImport.preview(emptyList(), imported)

        assertEquals(1, preview.newWordCount)
        assertEquals(2, preview.newCorrectionCount)
        assertEquals(listOf(VocabularyEntry("NorthStar", listOf("north star", "north store"))), preview.additions)
        assertEquals(0, preview.conflictCount)
    }

    @Test fun newCorrectionForExistingWordPreservesItsBoostAndSavedAliases() {
        val existing = listOf(VocabularyEntry("NorthStar", listOf("north star"), boost = 2.4))
        val imported = transfer(WisprDictionaryItem("north store", "NorthStar"))

        val preview = WisprDictionaryPortableImport.preview(existing, imported)
        val applied = WisprDictionaryPortableImport.apply(existing, preview)

        assertEquals(0, preview.newWordCount)
        assertEquals(1, preview.newCorrectionCount)
        assertEquals(listOf(VocabularyEntry("NorthStar", listOf("north star", "north store"), 2.4)), applied)
    }

    @Test fun aliasCollisionWithAnotherDestinationIsReportedAndSkipped() {
        val existing = listOf(VocabularyEntry("Acme", listOf("ack me")))
        val imported = transfer(WisprDictionaryItem("ack me", "OtherCo"))

        val preview = WisprDictionaryPortableImport.preview(existing, imported)
        val applied = WisprDictionaryPortableImport.apply(existing, preview)

        assertEquals(1, preview.newWordCount)
        assertEquals(0, preview.newCorrectionCount)
        assertEquals(1, preview.conflictCount)
        assertEquals(listOf(VocabularyEntry("Acme", listOf("ack me")), VocabularyEntry("OtherCo")), applied)
    }

    @Test fun exactDuplicatesDoNotChangeExistingWords() {
        val existing = listOf(VocabularyEntry("NorthStar", listOf("north star"), boost = 2.0))
        val imported = transfer(
            WisprDictionaryItem("NorthStar", null),
            WisprDictionaryItem("north star", "NorthStar"),
            WisprDictionaryItem("north star", "NorthStar"),
        )

        val preview = WisprDictionaryPortableImport.preview(existing, imported)
        val applied = WisprDictionaryPortableImport.apply(existing, preview)

        assertEquals(0, preview.newWordCount)
        assertEquals(0, preview.newCorrectionCount)
        assertEquals(3, preview.duplicateCount)
        assertEquals(0, preview.conflictCount)
        assertEquals(existing, applied)
    }

    @Test fun oneSpellingMappedToDifferentDestinationsIsReportedAsConflict() {
        val preview = WisprDictionaryPortableImport.preview(
            emptyList(),
            transfer(WisprDictionaryItem("same heard form", "First Word"), WisprDictionaryItem("same heard form", "Second Word")),
        )

        assertEquals(2, preview.newWordCount)
        assertEquals(0, preview.newCorrectionCount)
        assertEquals(1, preview.conflictCount)
    }

    @Test fun malformedOrWrongFormatFilesFailAsAWhole() {
        val wrongFormat = """{"format":"other","version":1,"entries":[]}"""
        val wrongVersion = """{"format":"${WisprDictionaryPortableImport.FORMAT}","version":2,"entries":[{"phrase":"Good"}]}"""
        val badSecondRow = """{"format":"${WisprDictionaryPortableImport.FORMAT}","version":1,"entries":[{"phrase":"Good"},{"phrase":4}]}"""
        val oversizedTerm = "a".repeat(201)
        val unsupportedText = """{"format":"${WisprDictionaryPortableImport.FORMAT}","version":1,"entries":[{"phrase":"$oversizedTerm"}]}"""

        listOf("not json", wrongFormat, wrongVersion, badSecondRow, unsupportedText).forEach { text ->
            val error = runCatching { WisprDictionaryPortableImport.parse(text) }.exceptionOrNull()
            assertTrue("expected a clear import error", error is IllegalArgumentException && !error.message.isNullOrBlank())
        }
    }

    @Test fun emptyAndOversizedFilesAreRejected() {
        val empty = """{"format":"${WisprDictionaryPortableImport.FORMAT}","version":1,"entries":[]}"""
        assertTrue(runCatching { WisprDictionaryPortableImport.parse(empty) }.isFailure)
        assertTrue(runCatching { WisprDictionaryPortableImport.parse(" ".repeat(WisprDictionaryPortableImport.MAX_BYTES + 1)) }.isFailure)
    }
}
