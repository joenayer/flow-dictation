package com.flowdictation.android

/** Only the current input field is inspected; snapshots are never persisted or logged. */
internal data class InputSnapshot(
    val packageName: String,
    val windowId: Int,
    val text: String,
    val selectionStart: Int,
    val selectionEnd: Int,
    val nativeEditText: Boolean = false,
)

internal data class InputReplacement(val text: String, val cursor: Int)

internal object AutoInputPolicy {
    // TextView exposes its hint as node.text when the actual field is empty.
    fun fieldText(exposedText: String?, showingHint: Boolean): String =
        if (showingHint) "" else exposedText.orEmpty()

    fun supportsTextActions(
        text: String,
        selectionStart: Int,
        selectionEnd: Int,
        canSetText: Boolean,
        canSetSelection: Boolean,
        nativeEditText: Boolean = false,
    ): Boolean {
        val selection = selectionBounds(text, selectionStart, selectionEnd, nativeEditText) ?: return false
        return canSetText && (canSetSelection ||
            // Native TextView advertises SET_SELECTION only once text is nonempty.
            // Empty content has only one legal insertion position.
            (nativeEditText && text.isEmpty() && selection.first == 0 && selection.second == 0))
    }

    fun replacement(original: InputSnapshot, current: InputSnapshot, transcript: String): InputReplacement? {
        if (original != current || transcript.isBlank()) return null
        val (start, end) = selectionBounds(original.text, original.selectionStart,
            original.selectionEnd, original.nativeEditText) ?: return null
        val before = original.text.substring(0, start)
        val after = original.text.substring(end)
        // Dictation returns trimmed phrases. Join separate phrases at a collapsed
        // cursor while leaving selected-range replacements exactly as dictated.
        val insertion = if (start == end) {
            (if (needsSeparator(before, transcript)) " " else "") + transcript +
                (if (needsSeparator(transcript, after)) " " else "")
        } else transcript
        return InputReplacement(before + insertion + after, start + insertion.length)
    }

    fun safeInputType(inputType: Int): Boolean {
        val klass = inputType and 0x0f
        val variation = inputType and 0x0ff0
        return !(klass == 1 && variation in setOf(0x80, 0x90, 0xe0)) &&
            !(klass == 2 && variation == 0x10)
    }

    private fun splitsSurrogate(text: String, offset: Int): Boolean =
        offset > 0 && offset < text.length && text[offset - 1].isHighSurrogate() && text[offset].isLowSurrogate()

    private fun selectionBounds(text: String, rawStart: Int, rawEnd: Int, nativeEditText: Boolean): Pair<Int, Int>? {
        // AOSP View omits selection metadata when TextView's actual text is empty.
        // Its unique insertion position is 0; retain raw -1/-1 in the snapshot so
        // subsequent metadata changes still invalidate the captured target.
        if (nativeEditText && text.isEmpty() && rawStart == -1 && rawEnd == -1) return 0 to 0
        val start = minOf(rawStart, rawEnd)
        val end = maxOf(rawStart, rawEnd)
        if (start < 0 || end > text.length) return null
        // Android selections count UTF-16 units. Reject positions inside a surrogate pair.
        if (splitsSurrogate(text, start) || splitsSurrogate(text, end)) return null
        return start to end
    }

    private fun needsSeparator(left: String, right: String): Boolean {
        val previous = left.lastOrNull() ?: return false
        val next = right.firstOrNull() ?: return false
        if (!next.isLetterOrDigit()) return false
        if (previous.isLetter()) return true
        if (previous.isDigit()) return next.isLetter() // Preserve numeric continuations.
        if (previous !in ".!?") return false
        if (previous == '.' && next.isDigit() && left.getOrNull(left.lastIndex - 1)?.isDigit() == true) return false
        return true
    }
}
