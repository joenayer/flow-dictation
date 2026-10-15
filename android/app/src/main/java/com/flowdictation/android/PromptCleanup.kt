package com.flowdictation.android

/**
 * Small, on-device edits for a transcript when the user asks Flow to clean it up.
 *
 * Drops speech fillers, exact restarts and selected accidental stutters, and
 * tidies prose spacing. Pause-marked corrections are limited to short noun
 * fragments; ambiguous repairs remain literal. Single-word emphasis and
 * negation stay intact. Literal code, URLs and supplied vocabulary spellings
 * are protected. Sentence capitalization is explicit for existing callers.
 * These rules cannot recognize every programming language or infer grammar.
 * Everything runs locally without a network or language model.
 */
object PromptCleanup {
    private val lineLeadingFiller = Regex(
        "(?im)^[ \\t]*(?:um|uh|erm)\\b[,]?[ \\t]*",
    )
    private val inlineFiller = Regex(
        "(?i)[ \\t]*,?[ \\t]*(?<![\\p{L}\\p{N}_])(?:um|uh|erm)\\b[,]?[ \\t]*",
    )
    private val cutOffRepeat = Regex(
        "(?i)([\\p{L}][\\p{L}\\p{N}_']*(?:[ \\t]+[\\p{L}][\\p{L}\\p{N}_']*){0,2})" +
            "([ \\t]*(?:—|–|\\.\\.\\.)[ \\t]*)(\\1)\\b",
    )
    // Only these short, commonly accidental stutters are collapsed when they
    // have no punctuation between them. Words with useful emphasis or grammar
    // ("no no", "very very", "that that", "had had") are intentionally absent.
    private val repeatedFunctionWord = Regex(
        "(?i)\\b(i|we|they|he|she|it|a|an|the|to|of|in|on|for|and|but|is|are|was|were|have|has|do|does|did|can|could|would|will)([ \\t]+)\\1\\b",
    )
    private val repeatedPhrase = Regex(
        "(?i)\\b((?:[\\p{L}][\\p{L}\\p{N}_']*[ \\t]+){1,3}[\\p{L}][\\p{L}\\p{N}_']*)" +
            "[ \\t]+(\\1)(?=[ \\t]+[\\p{L}])",
    )
    private val obviousCode = Regex(
        "(?s)(```|`|\\{|\\}|=>|::|(?m)^\\s*(?:val|var|const|let|fun|class|import|package|return|throw|break|continue|yield)\\s+|" +
            "^\\s*[A-Za-z_$][\\w$]*\\s*=(?!=)|\\b[A-Za-z_$][\\w$]*\\([^\\n]*\\))",
    )

    /** Returns a lightly tidied transcript, preserving its original text where possible. */
    fun clean(
        text: String,
        protectedTerms: Collection<String> = emptyList(),
        capitalizeSentences: Boolean = false,
    ): String {
        if (text.isEmpty()) return text
        val protected = TextProtection.protect(text, protectedTerms)
        if (obviousCode.containsMatchIn(protected.text)) return text
        var cleaned = lineLeadingFiller.replace(protected.text, "")
        // Discourse fillers are removed only at the beginning of a sentence or
        // line. "Like" requires a comma so comparisons remain intact.
        val discourse = Regex("(?im)(^|[.!?][ \\t]+)[ \\t]*(?:(?:so[ \\t]+basically|you[ \\t]+know|i[ \\t]+mean)\\b[,]?[ \\t]*|like,[ \\t]*)")
        while (true) {
            val next = discourse.replace(cleaned) { it.groupValues[1] }
            if (next == cleaned) break
            cleaned = next
        }
        // The replacement consumes only horizontal spacing and the filler
        // token's optional comma; line breaks and sentence punctuation survive.
        cleaned = inlineFiller.replace(cleaned) { match ->
            val previous = cleaned.substring(0, match.range.first).trimEnd().lastOrNull()
            // A short "um" after a number can be a measurement, and a token
            // after a dot can be a member name. Keep both unchanged.
            val dotIsPartOfToken = previous == '.' && match.value.firstOrNull()?.isWhitespace() != true
            val nextPunctuation = cleaned.getOrNull(match.range.last + 1)
            val isolatedSentenceFiller = previous == '.' && nextPunctuation?.let { it in ".!?" } == true
            val fillerAtLineEnd = nextPunctuation == null || nextPunctuation == '\n' || nextPunctuation == '\r'
            if (previous?.isDigit() == true || dotIsPartOfToken || previous == '$') {
                match.value
            } else if (isolatedSentenceFiller) {
                match.value
            } else if (fillerAtLineEnd || nextPunctuation?.let { it in ".!?;:" } == true) {
                ""
            } else {
                " "
            }
        }
        cleaned = cutOffRepeat.replace(cleaned) { match -> match.groupValues[3] }
        // Remove only a two-to-four-word exact restart whose second copy has
        // continuation text. This avoids flattening single-word emphasis and
        // complete repeated phrases at the end of a sentence.
        cleaned = repeatedPhrase.replace(cleaned) { match -> match.groupValues[2] }

        // Repeat until an utterance such as "I I I think" has no adjacent
        // stutter left. This is limited to the explicit list above.
        while (true) {
            val next = repeatedFunctionWord.replace(cleaned) { match ->
                match.groupValues[1]
            }
            if (next == cleaned) break
            cleaned = next
        }

        // Require two explicit pause commas and a short entire sentence/line
        // fragment. This deliberately leaves ambiguous mid-sentence repairs alone.
        val correction = Regex("(?im)(^|[.!?][ \\t]+)([\\p{L}][\\p{L}\\p{N}_'-]*(?:[ \\t]+[\\p{L}][\\p{L}\\p{N}_'-]*){0,3}),[ \\t]*(?:no|i mean),[ \\t]+(?=[\\p{L}])")
        cleaned = correction.replace(cleaned) {
            val fragment = it.groupValues[2]
            val words = fragment.split(Regex("[ \\t]+"))
            val nounFragment = words.size == 1 || words.first().lowercase() in setOf("a", "an", "the") ||
                words.all { word -> word.first().isUpperCase() }
            if (!nounFragment || Regex("(?i)\\b(?:no|not|never|don't|cannot|can't)\\b").containsMatchIn(fragment)) it.value
            else it.groupValues[1]
        }
        cleaned = cleaned.replace(Regex("[ \\t]+([,.;:!?])"), "$1")
            .replace(Regex("[ \\t]{2,}"), " ")
        // Preserve initialisms while fixing clearly missing prose spacing.
        // Decimal points and thousands separators have digits on both sides
        // and therefore never match these rules. Code/URLs are already masked.
        val abbreviations = mutableListOf<String>()
        cleaned = Regex("\\b(?:[A-Za-z]\\.){2,}|\\bPh\\.D\\.").replace(cleaned) {
            abbreviations.add(it.value)
            "\uE002${abbreviations.lastIndex}\uE003"
        }
        cleaned = cleaned
            .replace(Regex("([,;:!?])(?=[\\p{L}])"), "$1 ")
            .replace(Regex("(?<=[\\p{L}])([,;:!?])(?=[\\p{N}])"), "$1 ")
            .replace(Regex("(?<=[\\p{L}])\\.(?!(?:um|uh|erm)\\b)(?=[\\p{L}])", RegexOption.IGNORE_CASE), ". ")
        if (capitalizeSentences) {
            cleaned = Regex("(^|[.!?][ \\t]+|\\n[ \\t]*)([\\p{Ll}])").replace(cleaned) {
                it.groupValues[1] + it.groupValues[2].uppercase()
            }
        }
        cleaned = Regex("\uE002(\\d+)\uE003").replace(cleaned) { abbreviations[it.groupValues[1].toInt()] }
        return protected.restore(cleaned)
    }
}
