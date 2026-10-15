package com.flowdictation.android

import java.util.Locale

/** One left-to-right pass over the original, so replacements never trigger other aliases. */
object VocabularyReplacement {
    private val protected = Regex("```[\\s\\S]*?(?:```|$)|`[^`\\r\\n]*(?:`|(?=\\r?\\n)|$)|(?:[a-z][a-z0-9+.-]*://|www\\.|mailto:)[^\\s<>]+", RegexOption.IGNORE_CASE)
    private fun word(codePoint: Int): Boolean = Character.isLetterOrDigit(codePoint) || codePoint == '_'.code || when (Character.getType(codePoint)) {
        Character.NON_SPACING_MARK.toInt(), Character.COMBINING_SPACING_MARK.toInt(), Character.ENCLOSING_MARK.toInt() -> true
        else -> false
    }
    fun apply(text: String, entries: List<VocabularyEntry>): String {
        val rules = entries.flatMap { entry -> entry.aliases.map { it to entry.term } }.sortedByDescending { it.first.length }
        if (rules.isEmpty()) return text
        val excluded = protected.findAll(text).map { it.range }.toList()
        val out = StringBuilder()
        var i = 0
        var rangeIndex = 0
        while (i < text.length) {
            while (rangeIndex < excluded.size && excluded[rangeIndex].last < i) rangeIndex++
            val range = excluded.getOrNull(rangeIndex)
            if (range != null && i in range) {
                out.append(text, i, range.last + 1); i = range.last + 1; continue
            }
            val rule = rules.firstOrNull { (alias, _) ->
                val end = i + alias.length
                end <= text.length && (range == null || end <= range.first) &&
                    text.regionMatches(i, alias, 0, alias.length, ignoreCase = true) &&
                    (i == 0 || !word(text.codePointBefore(i))) && (end == text.length || !word(text.codePointAt(end)))
            }
            if (rule == null) { out.append(text[i++]); continue }
            val heard = text.substring(i, i + rule.first.length)
            val canonical = rule.second
            // Preserve intentionally mixed brand spellings; ordinary words follow ALL CAPS / Title case.
            val mixed = canonical.any(Char::isUpperCase) && canonical.drop(1).any(Char::isUpperCase)
            val replacement = when {
                mixed -> canonical
                heard.any(Char::isLetter) && heard.filter(Char::isLetter).all(Char::isUpperCase) -> canonical.uppercase(Locale.ROOT)
                heard.firstOrNull()?.isUpperCase() == true -> canonical.replaceFirstChar { it.titlecase(Locale.ROOT) }
                else -> canonical
            }
            out.append(replacement); i += rule.first.length
        }
        return out.toString()
    }
}
