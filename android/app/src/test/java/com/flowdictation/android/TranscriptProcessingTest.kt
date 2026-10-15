package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Test

class TranscriptProcessingTest {
    private val vocabulary = listOf(
        VocabularyEntry("NorthStar", listOf("north star")),
        VocabularyEntry("QRS", listOf("cue are ess")),
        VocabularyEntry("Parakeet", listOf("pair a keet")),
        VocabularyEntry("NeMo", listOf("knee moe")),
        VocabularyEntry("sherpa-onnx", listOf("sherpa onyx")),
    )

    @Test fun fiveRareTermsAreReplacedBeforeCleanup() {
        assertEquals("NorthStar QRS Parakeet NeMo sherpa-onnx.", TranscriptProcessing.process(
            "um, north star cue are ess pair a keet knee moe sherpa onyx.", vocabulary, true, true))
    }

    @Test fun disabledOptionsLeaveRawTextAlone() {
        val raw = "um, hello new line world"
        assertEquals(raw, TranscriptProcessing.process(raw, emptyList(), false, false))
    }

    @Test fun termWithoutHeardAsAliasDoesNotCorrectRecognizedWording() {
        assertEquals("north store", TranscriptProcessing.process(
            "north store", listOf(VocabularyEntry("NorthStar", boost = 3.0)),
            commands = false, cleanup = false,
        ))
    }

    @Test fun dictionaryTermsAreProtectedFromCommandsAndCleanup() {
        val terms = listOf(VocabularyEntry("New Line", listOf("new lyne")), VocabularyEntry("um", listOf("ummm")))
        assertEquals("New Line, um.", TranscriptProcessing.process("new lyne, ummm.", terms, true, true))
    }
}
