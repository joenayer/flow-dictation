package com.flowdictation.android

/** Pure, ordered output pipeline. The caller keeps the original separately. */
object TranscriptProcessing {
    fun process(raw: String, vocabulary: List<VocabularyEntry>, commands: Boolean, cleanup: Boolean): String {
        val terms = vocabulary.map { it.term }
        val replaced = VocabularyReplacement.apply(raw, vocabulary)
        val formatted = if (commands) SpokenCommands.apply(replaced, terms) else replaced
        return if (cleanup) PromptCleanup.clean(formatted, terms, capitalizeSentences = true) else formatted
    }
}
