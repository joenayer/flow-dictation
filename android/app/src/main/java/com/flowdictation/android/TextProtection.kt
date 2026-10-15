package com.flowdictation.android

/** Keeps literal text out of speech-only edits. No Android dependencies. */
object TextProtection {
    private val literals = Regex("```[\\s\\S]*?(?:```|$)|`[^`\\r\\n]*(?:`|(?=\\r?\\n)|$)|(?:[a-z][a-z0-9+.-]*://|www\\.|mailto:)[^\\s<>]+", RegexOption.IGNORE_CASE)

    class Protected internal constructor(val text: String, private val values: List<String>, private val literalCount: Int) {
        fun containsLiteral(value: String): Boolean = Regex("\uE000(\\d+)\uE001").findAll(value)
            .any { it.groupValues[1].toInt() < literalCount }
        fun restore(value: String): String = Regex("\uE000(\\d+)\uE001").replace(value) {
            values.getOrNull(it.groupValues[1].toInt()) ?: it.value
        }
    }

    fun protect(text: String, terms: Collection<String> = emptyList()): Protected {
        val values = mutableListOf<String>()
        fun token(value: String): String {
            values.add(value)
            return "\uE000${values.lastIndex}\uE001"
        }
        var masked = literals.replace(text) { token(it.value) }
        val literalCount = values.size
        for (term in terms.filter { it.isNotBlank() }.distinct().sortedByDescending { it.length }) {
            val pattern = Regex("(?<![\\p{L}\\p{N}_\uE000\uE001])${Regex.escape(term)}(?![\\p{L}\\p{N}_\uE000\uE001])", RegexOption.IGNORE_CASE)
            masked = pattern.replace(masked) { token(it.value) }
        }
        return Protected(masked, values, literalCount)
    }
}
