package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test

class VocabularyTest {
    @Test fun plainTextAndJsonRoundTrip() {
        val entries = listOf(VocabularyEntry("NorthStar", listOf("north star", "north store"), 2.0), VocabularyEntry("QRS Brands"))
        assertEquals(entries, VocabularyText.parse(VocabularyText.format(entries)))
        assertEquals(entries, VocabularyJson.parse(VocabularyJson.format(entries)))
    }
    @Test fun importsDefaultsAndUnicode() {
        assertEquals(listOf(VocabularyEntry("Zoë Rivera", listOf("Zoe Rivera"))), VocabularyText.parse("  Zoë Rivera | Zoe Rivera  \n"))
        assertEquals(VocabularyEntry("Acme"), VocabularyJson.parse("[{\"term\":\"Acme\"}]").single())
    }
    @Test fun invalidImportNeverPartiallySucceeds() {
        listOf("Good\nBad | wrong | 4", "A | shared\nB | shared", "A | B\nB", "A || NaN", "A | alias || extra", " | alias").forEach {
            try { VocabularyText.parse(it); fail("accepted $it") } catch (_: IllegalArgumentException) { }
        }
    }
    @Test fun aliasesAreWholeWordsLongestAndNonCascading() {
        val entries = listOf(VocabularyEntry("NorthStar", listOf("north star")), VocabularyEntry("short", listOf("pepper")),
            VocabularyEntry("other", listOf("NorthStar")))
        assertEquals("NorthStar short peppercorn", VocabularyReplacement.apply("north star pepper peppercorn", entries))
    }
    @Test fun unicodeWordBoundariesAndCanonicalCase() {
        val entries = listOf(VocabularyEntry("café", listOf("caff")), VocabularyEntry("NorthStar", listOf("north star")))
        assertEquals("café CAFÉ Café caffé ecaff caff_1 NorthStar", VocabularyReplacement.apply("caff CAFF Caff caffé ecaff caff_1 NORTH STAR", entries))
        assertEquals("éclair", VocabularyReplacement.apply("éclaire", listOf(VocabularyEntry("éclair", listOf("éclaire")))))
        assertEquals("𐐀caff caff𐐀", VocabularyReplacement.apply("𐐀caff caff𐐀", entries))
    }
    @Test fun codeUrlsAndUnclosedFencesStayUntouched() {
        val entries = listOf(VocabularyEntry("Acme", listOf("ack me")))
        val input = "ack me `ack me` https://site.test/ack me\n```\nack me\n``` ack me\n```ack me"
        assertEquals("Acme `ack me` https://site.test/ack me\n```\nack me\n``` Acme\n```ack me", VocabularyReplacement.apply(input, entries))
    }
    @Test fun learningFindsIndependentShortSubstitutions() {
        assertEquals(listOf(VocabularySuggestion("NorthStar", "north star"), VocabularySuggestion("QRS", "cue are ess")),
            EditLearning.candidates("Send north star to cue are ess today", "Send NorthStar to QRS today", setOf("send", "to", "today")))
    }
    @Test fun learningIgnoresCommonWordsCasePunctuationInsertionsAndDeletions() {
        assertTrue(EditLearning.candidates("hello world", "Hello, world!", emptySet()).isEmpty())
        assertTrue(EditLearning.candidates("a red box", "a blue box", setOf("blue")).isEmpty())
        assertTrue(EditLearning.candidates("hello", "hello NorthStar", emptySet()).isEmpty())
        assertTrue(EditLearning.candidates("hello NorthStar", "hello", emptySet()).isEmpty())
        assertTrue(EditLearning.candidates("a b c d e end", "f g h i j end", emptySet()).isEmpty())
    }
    @Test fun learningBoundsLargeEdits() {
        assertTrue(EditLearning.candidates("hello ".repeat(601), "Acme", emptySet()).isEmpty())
    }
    @Test fun learningRejectsWordsInsideUrlsAndCode() {
        listOf(
            "visit https://example.test/pepper" to "visit https://example.test/NorthStar",
            "`pepper`" to "`NorthStar`",
            "```\npepper\n```" to "```\nNorthStar\n```",
            "`pepper\nnext line" to "`NorthStar\nnext line",
            "mail mailto:person@example.test" to "mail mailto:person@example.test"
        ).forEach { (old, new) -> assertTrue(EditLearning.candidates(old, new, emptySet()).isEmpty()) }
        assertEquals(listOf(VocabularySuggestion("NorthStar", "pepper")),
            EditLearning.candidates("`keep this` pepper", "`keep this` NorthStar", emptySet()))
    }
}
