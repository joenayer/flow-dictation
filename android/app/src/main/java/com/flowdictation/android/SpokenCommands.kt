package com.flowdictation.android

/** Conservative speech formatting, applied before optional concise cleanup. */
object SpokenCommands {
    private val command = Regex("(?i)(?<![\\p{L}\\p{N}_])(new paragraph|new line|scratch that|question mark|period|comma)(?![\\p{L}\\p{N}_])")
    private val trailingCommand = Regex("(?i)^(?:new paragraph|new line|scratch that|question mark|period|comma)\\b")

    fun apply(text: String, protectedTerms: Collection<String> = emptyList()): String {
        val protected = TextProtection.protect(text, protectedTerms)
        val source = protected.text
        val result = StringBuilder()
        var offset = 0
        for (match in command.findAll(source)) {
            result.append(source.substring(offset, match.range.first))
            val before = result.toString().trimEnd()
            val after = source.substring(match.range.last + 1).trimStart()
            val name = match.value.lowercase()
            val ordinaryUse = when (name) {
                "period" -> Regex("(?i)^(?:of|drama|piece|costume|pain|cycle|is|was)\\b").containsMatchIn(after)
                "comma" -> Regex("(?i)^(?:separated|splice|is|was)\\b").containsMatchIn(after)
                "question mark" -> Regex("(?i)^(?:is|was|means)\\b").containsMatchIn(after)
                "new line", "new paragraph" -> Regex("(?i)^(?:of|in|is|was)\\b").containsMatchIn(after)
                "scratch that" -> Regex("(?i)^(?:idea|thought|proposal|plan|from|off)\\b").containsMatchIn(after)
                else -> false
            }
            val atBoundary = !ordinaryUse && (before.isEmpty() || before.last() in ".!?,;:\n" ||
                after.isEmpty() || after.first() in ".!?,;:\n" || trailingCommand.containsMatchIn(after))
            // Formatting phrases can occur in ordinary prose too. Require a
            // boundary for all commands, including "a new line of products".
            if (!atBoundary) {
                result.append(match.value)
            } else {
                when (name) {
                    "new line", "new paragraph" -> {
                        trimHorizontal(result)
                        trimPause(result)
                        result.append(if (name == "new paragraph") "\n\n" else "\n")
                    }
                    "scratch that" -> {
                        trimHorizontal(result)
                        trimPause(result)
                        val current = result.toString()
                        val end = current.trimEnd().removeSuffix(".").removeSuffix("!").removeSuffix("?")
                        val boundary = end.indexOfLast { it in ".!?\n" }
                        // Never delete a literal code span or URL with a command.
                        if (!protected.containsLiteral(current.substring(boundary + 1))) {
                            result.setLength(boundary + 1)
                            while (result.isNotEmpty() && result.last().isWhitespace()) result.setLength(result.length - 1)
                        } else result.append(" ").append(match.value)
                    }
                    else -> {
                        trimHorizontal(result)
                        trimPause(result)
                        result.append(when (name) { "period" -> "."; "comma" -> ","; else -> "?" })
                    }
                }
            }
            offset = match.range.last + 1
            // ASR often adds punctuation to a spoken command itself. That pause
            // is not an extra blank-line sentence or a new sentence to erase.
            if (atBoundary && offset < source.length && source[offset] in ",.;:!?") offset++
        }
        result.append(source.substring(offset))
        val formatted = result.toString()
            .replace(Regex("[ \\t]*\\n[ \\t]*"), "\n")
            .trim(' ', '\t', '\r')
        return protected.restore(formatted)
    }

    private fun trimHorizontal(value: StringBuilder) {
        while (value.isNotEmpty() && (value.last() == ' ' || value.last() == '\t')) value.setLength(value.length - 1)
    }

    private fun trimPause(value: StringBuilder) {
        if (value.isNotEmpty() && value.last() in ",;:") value.setLength(value.length - 1)
    }
}
