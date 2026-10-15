package com.flowdictation.android

import java.util.Locale
import com.google.android.material.dialog.MaterialAlertDialogBuilder

data class VocabularySuggestion(val term: String, val heard: String)

/** Bounded word LCS: unchanged context anchors independent substitutions. */
object EditLearning {
    private val token = Regex("[\\p{L}\\p{M}]+(?:['’\\-][\\p{L}\\p{M}]+)*")
    private val protected = Regex("```[\\s\\S]*?(?:```|$)|`[^`\\r\\n]*(?:`|(?=\\r?\\n)|$)|(?:[a-z][a-z0-9+.-]*://|www\\.|mailto:)[^\\s<>]+", RegexOption.IGNORE_CASE)
    fun candidates(old: String, new: String, commonWords: Set<String>): List<VocabularySuggestion> {
        val before = token.findAll(old).toList()
        val after = token.findAll(new).toList()
        val oldProtected = protected.findAll(old).map { it.range }.toList()
        val newProtected = protected.findAll(new).map { it.range }.toList()
        if (before.size > 600 || after.size > 600) return emptyList()
        val a = before.map { it.value.lowercase(Locale.ROOT) }
        val b = after.map { it.value.lowercase(Locale.ROOT) }
        val table = Array(a.size + 1) { IntArray(b.size + 1) }
        for (i in a.indices.reversed()) for (j in b.indices.reversed())
            table[i][j] = if (a[i] == b[j]) table[i + 1][j + 1] + 1 else maxOf(table[i + 1][j], table[i][j + 1])
        val result = mutableListOf<VocabularySuggestion>()
        var i = 0; var j = 0
        while (i < a.size || j < b.size) {
            if (i < a.size && j < b.size && a[i] == b[j]) { i++; j++; continue }
            val startI = i; val startJ = j
            while (i < a.size || j < b.size) {
                if (i < a.size && j < b.size && a[i] == b[j]) break
                if (i < a.size && (j == b.size || table[i + 1][j] >= table[i][j + 1])) i++ else j++
            }
            if (i - startI !in 1..3 || j - startJ !in 1..3) continue
            if (oldProtected.any { it.first <= before[i - 1].range.last && it.last >= before[startI].range.first } ||
                newProtected.any { it.first <= after[j - 1].range.last && it.last >= after[startJ].range.first }) continue
            if ((startJ until j).all { b[it] in commonWords }) continue
            val heard = old.substring(before[startI].range.first, before[i - 1].range.last + 1)
            val term = new.substring(after[startJ].range.first, after[j - 1].range.last + 1)
            // Do not suggest fragments of punctuation-heavy text, URLs, or code.
            if (!Regex("[\\p{L}\\p{M}'’\\-]+(?:\\s+[\\p{L}\\p{M}'’\\-]+){0,2}").matches(term) ||
                !Regex("[\\p{L}\\p{M}'’\\-]+(?:\\s+[\\p{L}\\p{M}'’\\-]+){0,2}").matches(heard)) continue
            if (!term.equals(heard, true)) result += VocabularySuggestion(term, heard)
        }
        return result.distinctBy { it.term.lowercase(Locale.ROOT) to it.heard.lowercase(Locale.ROOT) }
    }
}

object VocabularyLearning {
    @Volatile private var cachedCommon: Set<String>? = null
    fun offer(activity: FlowActivity, old: String, new: String) {
        if (!Prefs(activity).learnFromEdits || old == new) return
        Thread {
            val result = runCatching {
                val common = cachedCommon ?: activity.assets.open("common-english-20000.txt").bufferedReader().use {
                    it.lineSequence().toSet()
                }.also { cachedCommon = it }
                val existing = VocabularyStore(activity).load()
                EditLearning.candidates(old, new, common).filter { suggestion ->
                    existing.none { entry -> entry.term.equals(suggestion.term, true) && entry.aliases.any { it.equals(suggestion.heard, true) } }
                }.take(3)
            }.getOrDefault(emptyList())
            activity.runOnUiThread { showNext(activity, result, 0) }
        }.start()
    }
    private fun showNext(activity: FlowActivity, items: List<VocabularySuggestion>, index: Int) {
        if (index >= items.size || activity.isFinishing || activity.isDestroyed) return
        val item = items[index]
        MaterialAlertDialogBuilder(activity).setTitle(activity.getString(R.string.vocabulary_suggest_title, item.term))
            .setMessage(activity.getString(R.string.vocabulary_suggest_message, item.heard, item.term))
            .setNegativeButton(R.string.vocabulary_skip) { _, _ -> showNext(activity, items, index + 1) }
            .setPositiveButton(R.string.vocabulary_add) { _, _ ->
                runCatching {
                    val store = VocabularyStore(activity)
                    val previous = store.load().firstOrNull { it.term.equals(item.term, true) }
                    store.upsert(VocabularyEntry(previous?.term ?: item.term,
                        (previous?.aliases.orEmpty() + item.heard).distinct(), previous?.boost ?: 1.5))
                }.onSuccess { activity.message(activity.getString(R.string.vocabulary_added)) }
                    .onFailure { activity.message(it.message ?: activity.getString(R.string.vocabulary_save_error)) }
                showNext(activity, items, index + 1)
            }.show()
    }
}
