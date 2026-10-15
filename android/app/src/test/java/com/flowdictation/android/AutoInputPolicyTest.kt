package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test

class AutoInputPolicyTest {
    private fun field(text: String = "Hello world", start: Int = 6, end: Int = 6) =
        InputSnapshot("example.editor", 4, text, start, end, nativeEditText = true)

    @Test fun visibleHintIsNotInsertedAsExistingText() {
        val state = field(AutoInputPolicy.fieldText("Type a message", true), 0, 0)
        assertEquals(InputReplacement("Hello", 5), AutoInputPolicy.replacement(state, state, "Hello"))
        assertEquals("", AutoInputPolicy.fieldText(null, true))
    }

    @Test fun realTextMatchingHintRemainsUserContent() {
        val actual = AutoInputPolicy.fieldText("Type a message", false)
        val state = field(actual, actual.length, actual.length)
        assertEquals(InputReplacement("Type a message Hello", 20), AutoInputPolicy.replacement(state, state, "Hello"))
        assertEquals("", AutoInputPolicy.fieldText(null, false))
    }

    @Test fun emptyNativeFieldSupportsFirstInsertionWithoutSelectionAction() {
        listOf(AutoInputPolicy.fieldText("Type a message", true), AutoInputPolicy.fieldText(null, false)).forEach { text ->
            assertTrue(AutoInputPolicy.supportsTextActions(text, 0, 0, true, false, nativeEditText = true))
            val state = field(text, 0, 0)
            assertEquals(InputReplacement("Hello", 5), AutoInputPolicy.replacement(state, state, "Hello"))
        }
    }

    @Test fun nonemptyFieldStillRequiresSelectionAction() {
        assertFalse(AutoInputPolicy.supportsTextActions("Existing content", 0, 0, true, false))
        assertFalse(AutoInputPolicy.supportsTextActions(AutoInputPolicy.fieldText("Type a message", false), 0, 0, true, false))
        assertTrue(AutoInputPolicy.supportsTextActions("Hello", 5, 5, true, true))
        val state = field("Hello", 5, 5)
        assertEquals(InputReplacement("Hello world", 11), AutoInputPolicy.replacement(state, state, "world"))
    }

    @Test fun emptyFieldExceptionRejectsMixedInvalidSelectionAndMissingTextAction() {
        listOf(-1 to 0, 0 to -1, 0 to 1, 1 to 1, -2 to -2).forEach { (start, end) ->
            assertFalse(AutoInputPolicy.supportsTextActions("", start, end, true, false, nativeEditText = true))
        }
        assertFalse(AutoInputPolicy.supportsTextActions("", -1, -1, false, false, nativeEditText = true))
        assertFalse(AutoInputPolicy.supportsTextActions("", 0, 0, false, true, nativeEditText = true))
    }

    @Test fun nativeEmptyMissingSelectionMetadataHasUniqueInsertionPosition() {
        val state = field(AutoInputPolicy.fieldText("Type a message", true), -1, -1)
        assertTrue(AutoInputPolicy.supportsTextActions(state.text, -1, -1, true, false, nativeEditText = true))
        assertEquals(InputReplacement("Hello", 5), AutoInputPolicy.replacement(state, state, "Hello"))
        assertNull(AutoInputPolicy.replacement(state, state.copy(selectionStart = 0, selectionEnd = 0), "Hello"))
    }

    @Test fun missingSelectionNeverGuessesCursorInNonemptyOrUnknownWidget() {
        val nonempty = field("Existing content", -1, -1)
        assertFalse(AutoInputPolicy.supportsTextActions(nonempty.text, -1, -1, true, true, nativeEditText = true))
        assertNull(AutoInputPolicy.replacement(nonempty, nonempty, "Hello"))
        val unknown = field("", -1, -1).copy(nativeEditText = false)
        assertFalse(AutoInputPolicy.supportsTextActions("", -1, -1, true, false))
        assertFalse(AutoInputPolicy.supportsTextActions("", 0, 0, true, false))
        assertNull(AutoInputPolicy.replacement(unknown, unknown, "Hello"))
    }

    @Test fun insertsAtCursorPreservingBothSides() {
        val state = field()
        assertEquals(InputReplacement("Hello spoken world", 13), AutoInputPolicy.replacement(state, state, "spoken "))
    }
    @Test fun replacesOnlySelectedRangeIncludingReversedSelection() {
        val state = field(start = 11, end = 6)
        assertEquals(InputReplacement("Hello voice", 11), AutoInputPolicy.replacement(state, state, "voice"))
    }
    @Test fun emptyFieldAcceptsMultilineUnicodeWithoutAddingWhitespace() {
        val state = field("", 0, 0)
        val text = "Hi 🦊\nnext"
        assertEquals(InputReplacement(text, text.length), AutoInputPolicy.replacement(state, state, text))
    }
    @Test fun changedPackageWindowTextOrSelectionIsRejected() {
        val state = field()
        listOf(state.copy(packageName = "other.app"), state.copy(windowId = 5),
            state.copy(text = "User edited"), state.copy(selectionStart = 0),
            state.copy(selectionEnd = 8)).forEach {
            assertNull(AutoInputPolicy.replacement(state, it, "voice"))
        }
    }
    @Test fun invalidSelectionsAndSplitSurrogateAreRejected() {
        listOf(field(start = -1), field(end = 12), field("🦊", 1, 1)).forEach {
            assertNull(AutoInputPolicy.replacement(it, it, "voice"))
        }
    }
    @Test fun validUnicodeCursorPreservesWholeCharacters() {
        val state = field("a🦊b", 3, 3)
        assertEquals(InputReplacement("a🦊👋b", 5), AutoInputPolicy.replacement(state, state, "👋"))
    }
    @Test fun blankTranscriptCannotDeleteSelection() {
        val state = field(start = 0, end = 11)
        listOf("", " \n\t").forEach { assertNull(AutoInputPolicy.replacement(state, state, it)) }
    }
    @Test fun passwordsAreExcludedIncludingVisibleWebAndNumericVariations() {
        listOf(0x81, 0x91, 0xe1, 0x12, 0x20081).forEach {
            assertFalse("unsafe inputType=$it", AutoInputPolicy.safeInputType(it))
        }
        listOf(0, 1, 2, 0x21, 0x20001).forEach { assertTrue(AutoInputPolicy.safeInputType(it)) }
    }

    @Test fun consecutivePhrasesAndSentencesAreSeparated() {
        listOf("Hello" to "Hello world", "First." to "First. world", "Ready?" to "Ready? world").forEach { (old, expected) ->
            val state = field(old, old.length, old.length)
            assertEquals(InputReplacement(expected, expected.length), AutoInputPolicy.replacement(state, state, "world"))
        }
    }

    @Test fun insertionBetweenWordsAddsBothSeparatorsAndMovesPastTrailingSeparator() {
        val state = field("Helloworld", 5, 5)
        assertEquals(InputReplacement("Hello spoken world", 13), AutoInputPolicy.replacement(state, state, "spoken"))
        val continued = field("Hello spoken world", 13, 13)
        assertEquals(InputReplacement("Hello spoken next world", 18), AutoInputPolicy.replacement(continued, continued, "next"))
    }

    @Test fun explicitWhitespaceNewlinesAndPunctuationRemainExact() {
        data class Case(val old: String, val cursor: Int, val incoming: String, val expected: String, val finalCursor: Int)
        listOf(
            Case("Hello ", 6, "world", "Hello world", 11),
            Case("Hello", 5, " world", "Hello world", 11),
            Case("Hello\n", 6, "world\n", "Hello\nworld\n", 12),
            Case("(world)", 1, "spoken ", "(spoken world)", 8),
            Case("Hello, world", 5, "there", "Hello there, world", 11),
            Case("Hello)", 5, "there", "Hello there)", 11),
            Case("Hello", 5, ",", "Hello,", 6),
        ).forEach { case ->
            val state = field(case.old, case.cursor, case.cursor)
            assertEquals(InputReplacement(case.expected, case.finalCursor), AutoInputPolicy.replacement(state, state, case.incoming))
        }
    }

    @Test fun replacingSelectedTextDoesNotGenerateSeparators() {
        val state = field("Hello old world", 6, 9)
        assertEquals(InputReplacement("Hello new world", 9), AutoInputPolicy.replacement(state, state, "new"))
        val partial = field("unhappy", 2, 7)
        assertEquals(InputReplacement("unwell", 6), AutoInputPolicy.replacement(partial, partial, "well"))
    }

    @Test fun numericContinuationIsPreservedButWordsAndNumbersAreSeparated() {
        listOf("12" to "1234", "12." to "12.34").forEach { (old, expected) ->
            val state = field(old, old.length, old.length)
            assertEquals(InputReplacement(expected, expected.length), AutoInputPolicy.replacement(state, state, "34"))
        }
        val state = field("12", 2, 2)
        assertEquals(InputReplacement("12 apples", 9), AutoInputPolicy.replacement(state, state, "apples"))
        val beforeDigits = field("12", 0, 0)
        assertEquals(InputReplacement("apples 12", 7), AutoInputPolicy.replacement(beforeDigits, beforeDigits, "apples"))
    }
}
