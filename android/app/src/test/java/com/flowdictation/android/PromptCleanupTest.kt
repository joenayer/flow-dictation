package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Test

class PromptCleanupTest {
    @Test fun removesOnlyStandaloneFillerWordsAndTheirPauseCommas() {
        assertEquals(
            "I think we should go.\nlet's begin.",
            PromptCleanup.clean("Um, I think, uh, we should go.\nErm, let's begin."),
        )
        assertEquals("Thanks.", PromptCleanup.clean("Thanks, erm."))
        assertEquals("Thanks", PromptCleanup.clean("Thanks, um"))
        assertEquals("", PromptCleanup.clean("uh"))
    }

    @Test fun repairsAnExactPhraseRestartOnlyWhenItHasAnExplicitCutoff() {
        assertEquals(
            "I was going to call you.",
            PromptCleanup.clean("I was— I was going to call you."),
        )
        assertEquals(
            "Could you please send it?",
            PromptCleanup.clean("Could you please... Could you please send it?"),
        )
    }

    @Test fun removesImmediateRepeatedPhrasesWhenTheSecondCopyContinues() {
        assertEquals("I want to go.", PromptCleanup.clean("I want I want to go."))
        assertEquals("send the email tomorrow", PromptCleanup.clean("send the email send the email tomorrow"))

        // A single repeated word, a complete repeated phrase, or a pause-marked repeat
        // can carry emphasis, so this narrow phrase rule leaves those untouched.
        assertEquals("very very good.", PromptCleanup.clean("very very good."))
        assertEquals("I love you I love you.", PromptCleanup.clean("I love you I love you."))
        assertEquals("I want, I want to go.", PromptCleanup.clean("I want, I want to go."))
    }

    @Test fun collapsesOnlyListedUnpunctuatedFunctionWordStutters() {
        assertEquals("I think we should send it.", PromptCleanup.clean("I I think we we should send it."))
        assertEquals("The answer is ready.", PromptCleanup.clean("The the answer is is ready."))
        assertEquals("No, no, that that is very very good.", PromptCleanup.clean("No, no, that that is very very good."))
    }

    @Test fun preservesNegationNumbersSentenceBoundariesAndIdentifiers() {
        val original = "I do not want 12 items. Don't change foo_uh, uhCount or foo.um. 3 um is a unit.\nNo, no."
        assertEquals(original, PromptCleanup.clean(original))
        assertEquals("Wait. No, I said don't send it!", PromptCleanup.clean("Wait. No, I said don't send it!"))
        assertEquals("Wait. I said no.", PromptCleanup.clean("Wait. Uh, I said no."))
        assertEquals("Wait. Uh.", PromptCleanup.clean("Wait. Uh."))
    }

    @Test fun leavesObviousCodeExamplesUntouched() {
        val code = "val uh = 12\nprintln(uh)"
        assertEquals(code, PromptCleanup.clean(code))
        assertEquals("uh = 3", PromptCleanup.clean("uh = 3"))
        assertEquals("return uh", PromptCleanup.clean("return uh"))
        assertEquals("const uh = 3", PromptCleanup.clean("const uh = 3"))
        assertEquals("consume(uh)", PromptCleanup.clean("consume(uh)"))
        val fenced = "Use this example: ```\nval um = 1\n```"
        assertEquals(fenced, PromptCleanup.clean(fenced))
    }

    @Test fun doesNotInventSemanticOrGrammarChanges() {
        val original = "Maybe I was, I mean I might be ready."
        assertEquals(original, PromptCleanup.clean(original))
        assertEquals("The report was not ready.", PromptCleanup.clean("The report was, uh, not ready."))
    }
}
