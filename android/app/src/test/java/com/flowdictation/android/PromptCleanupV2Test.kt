package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Test

class PromptCleanupV2Test {
    @Test fun removesLeadingDiscourseFillersAndTidiesSpacing() {
        assertEquals("send this, please.", PromptCleanup.clean("So basically, you know, I mean, like, send  this , please."))
        assertEquals("I like apples.", PromptCleanup.clean("I like apples."))
        assertEquals("Do you know the answer?", PromptCleanup.clean("Do you know the answer?"))
    }

    @Test fun correctionsRequireShortPauseMarkedFragments() {
        assertEquals("Tuesday.", PromptCleanup.clean("Monday, no, Tuesday."))
        assertEquals("Tuesday.", PromptCleanup.clean("Monday, I mean, Tuesday."))
        assertEquals("Please use the large blue box, no, bag.", PromptCleanup.clean("Please use the large blue box, no, bag."))
        assertEquals("No, no, leave it.", PromptCleanup.clean("No, no, leave it."))
        assertEquals("send on Monday, no, Tuesday.", PromptCleanup.clean("send on Monday, no, Tuesday."))
        assertEquals("the red box.", PromptCleanup.clean("the blue box, no, the red box."))
    }

    @Test fun protectedVocabularyAndLiteralsRemainExact() {
        assertEquals("Um, no, NorthStar.", PromptCleanup.clean("Um, no, NorthStar.", listOf("Um")))
        assertEquals("visit https://example.com/um and `uh`.", PromptCleanup.clean("Um, visit https://example.com/um and `uh`."))
        assertEquals("Um and NorthStar.", PromptCleanup.clean("Um and NorthStar.", listOf("Um", "NorthStar"), true))
    }

    @Test fun capitalizationIsExplicitForLegacyCallers() {
        assertEquals("Send it. Then wait.\nTry again.", PromptCleanup.clean("send it. then wait.\ntry again.", capitalizeSentences = true))
        assertEquals("send it.", PromptCleanup.clean("send it."))
    }

    @Test fun missingProseSpacesDoNotDamageNumbersInitialismsOrLiterals() {
        assertEquals("hello, world. hello. world! Again? Yes", PromptCleanup.clean("hello,world. hello.world!Again?Yes"))
        val literal = "3.14 and 1,000 and U.S.A. and e.g. and https://example.com/a,b and `hello,world`"
        assertEquals(literal, PromptCleanup.clean(literal))
        assertEquals("NorthStar, hello. world", PromptCleanup.clean("NorthStar,hello.world", listOf("NorthStar")))
    }
}
