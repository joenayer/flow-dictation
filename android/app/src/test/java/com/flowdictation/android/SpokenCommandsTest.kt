package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Test

class SpokenCommandsTest {
    @Test fun terminalFormattingAndOrdinaryPunctuationArePreserved() {
        assertEquals("hello\n", SpokenCommands.apply("hello new line"))
        assertEquals("hello\n\n", SpokenCommands.apply("hello new paragraph"))
        assertEquals("What?! Really...", SpokenCommands.apply("What?! Really..."))
        assertEquals("ftp://example/period mailto:person@example.test", SpokenCommands.apply("ftp://example/period mailto:person@example.test"))
        assertEquals("`new line\nhello", SpokenCommands.apply("`new line\nhello"))
    }
    @Test fun formatsCommandsAtExplicitPhraseBoundaries() {
        assertEquals("Hello, how are you?", SpokenCommands.apply("Hello, comma, how are you question mark"))
        assertEquals("First.\nSecond.\n\nThird.", SpokenCommands.apply("First period new line Second period new paragraph Third period"))
    }

    @Test fun scratchRemovesPreviousSentenceOrUnfinishedSegment() {
        assertEquals("Keep this. Try again.", SpokenCommands.apply("Keep this. Wrong sentence. scratch that Try again."))
        assertEquals("", SpokenCommands.apply("Wrong unfinished segment scratch that"))
        assertEquals("Keep this.", SpokenCommands.apply("Keep this. new line Wrong. scratch that"))
    }

    @Test fun ordinaryLanguageAndWordPartsSurvive() {
        val prose = "The period of time was short. A new line of products. Comma separated values."
        assertEquals(prose, SpokenCommands.apply(prose))
        assertEquals("periodic commaCount newline", SpokenCommands.apply("periodic commaCount newline"))
    }

    @Test fun codeAndUrlsStayLiteral() {
        val literal = "`new line period` https://example.com/new-line/period ```\ncomma\n```"
        assertEquals(literal, SpokenCommands.apply(literal))
        assertEquals("`keep()` scratch that", SpokenCommands.apply("`keep()` scratch that"))
    }

    @Test fun vocabularyCannotBecomeACommand() {
        assertEquals("Use New Line", SpokenCommands.apply("Use New Line", listOf("New Line")))
        assertEquals("Keep this.", SpokenCommands.apply("Keep this. Call NorthStar. scratch that", listOf("NorthStar")))
    }

    @Test fun commandPausePunctuationDoesNotLeaveStraySentences() {
        assertEquals("First.\nSecond.", SpokenCommands.apply("First. new line. Second."))
        assertEquals("Keep this. Next.", SpokenCommands.apply("Keep this. Wrong. scratch that. Next."))
        assertEquals("Scratch that idea from the plan.", SpokenCommands.apply("Scratch that idea from the plan."))
    }
}
