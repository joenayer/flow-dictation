package com.flowdictation.android

import org.json.JSONArray
import org.json.JSONObject
import java.util.LinkedHashMap
import java.util.Locale

data class WisprDictionaryItem(val phrase: String, val replacement: String?)
data class WisprDictionaryTransfer(val items: List<WisprDictionaryItem>) {
    val sourceCount: Int get() = items.size
}

data class WisprAliasUpdate(val existingTerm: String, val aliases: List<String>)

data class WisprDictionaryPreview(
    val sourceCount: Int,
    val additions: List<VocabularyEntry>,
    val updates: List<WisprAliasUpdate>,
    val duplicateCount: Int,
    val conflictCount: Int,
) {
    val newWordCount: Int get() = additions.size
    val newCorrectionCount: Int get() = additions.sumOf { it.aliases.size } + updates.sumOf { it.aliases.size }
    val hasChanges: Boolean get() = newWordCount > 0 || newCorrectionCount > 0
}

/** Parser for the versioned handoff file produced by scripts/export_wispr_dictionary.py. */
object WisprDictionaryPortableImport {
    const val FORMAT = "flow-dictation-wispr-dictionary"
    const val VERSION = 1
    const val MAX_BYTES = 2_000_000
    const val MAX_ENTRIES = 5_000

    fun parse(text: String): WisprDictionaryTransfer {
        require(text.toByteArray(Charsets.UTF_8).size <= MAX_BYTES) { "Choose a file smaller than 2 MB." }
        val root = try { JSONObject(text) } catch (_: Exception) {
            throw IllegalArgumentException("This is not a valid Wispr dictionary transfer file.")
        }
        require(root.opt("format") == FORMAT) { "Choose a Wispr dictionary transfer file made by the desktop helper." }
        require(root.opt("version") == VERSION) { "This Wispr transfer file version is not supported." }
        val rows = root.opt("entries") as? JSONArray
            ?: throw IllegalArgumentException("This transfer file has no dictionary entries.")
        require(rows.length() > 0) { "This transfer file contains no dictionary entries." }
        require(rows.length() <= MAX_ENTRIES) { "Use a transfer file with at most 5,000 dictionary entries." }

        val items = (0 until rows.length()).map { index ->
            val rowNumber = index + 1
            val row = rows.optJSONObject(index)
                ?: throw IllegalArgumentException("Entry $rowNumber is not a dictionary item.")
            val phrase = row.opt("phrase") as? String
                ?: throw IllegalArgumentException("Entry $rowNumber is missing its word.")
            val rawReplacement = row.opt("replacement")
            val replacement = when {
                rawReplacement == null || rawReplacement == JSONObject.NULL -> null
                rawReplacement is String -> rawReplacement.trim().takeIf { it.isNotEmpty() }
                else -> throw IllegalArgumentException("Entry $rowNumber has an invalid correction.")
            }
            try {
                val source = phrase.trim()
                require(source.isNotEmpty() && source.length <= 60) { "The word is empty or too long." }
                if (replacement == null) {
                    val normalized = VocabularyText.normalize(VocabularyEntry(source))
                    WisprDictionaryItem(normalized.term, null)
                } else {
                    require(replacement.length <= 4_000) { "The correction is too long." }
                    require(replacement.length <= 200) { "Flow supports corrections up to 200 characters." }
                    // Wispr stores correction rules as misspelling -> correct spelling.
                    // Flow vocabulary stores the desired spelling with what was heard as aliases.
                    val normalized = VocabularyText.normalize(VocabularyEntry(replacement, listOf(source)))
                    val cleanSource = VocabularyText.normalize(VocabularyEntry(source)).term
                    WisprDictionaryItem(cleanSource, normalized.term)
                }
            } catch (error: IllegalArgumentException) {
                throw IllegalArgumentException("Entry $rowNumber cannot be added: ${error.message ?: "check the spelling."}")
            }
        }
        return WisprDictionaryTransfer(items)
    }

    /** Shows new words, new corrections, exact duplicates, and spelling conflicts separately. */
    fun preview(existing: List<VocabularyEntry>, transfer: WisprDictionaryTransfer): WisprDictionaryPreview {
        val existingByTerm = existing.associateBy { it.term.lowercase(Locale.ROOT) }
        val existingOwner = mutableMapOf<String, String>()
        existing.forEach { entry ->
            val termKey = entry.term.lowercase(Locale.ROOT)
            (listOf(entry.term) + entry.aliases).forEach { existingOwner[it.lowercase(Locale.ROOT)] = termKey }
        }

        data class Group(
            val term: String,
            var plainRows: Int = 0,
            val aliases: LinkedHashMap<String, String> = linkedMapOf(),
            var duplicateAliasSpellings: Int = 0,
        )

        val groups = linkedMapOf<String, Group>()
        val uniqueRows = linkedSetOf<Pair<String, String?>>()
        var duplicates = 0
        transfer.items.forEach { item ->
            val rowKey = item.phrase.lowercase(Locale.ROOT) to item.replacement?.lowercase(Locale.ROOT)
            if (!uniqueRows.add(rowKey)) {
                duplicates++
                return@forEach
            }
            val term = item.replacement ?: item.phrase
            val termKey = term.lowercase(Locale.ROOT)
            val group = groups.getOrPut(termKey) { Group(term) }
            if (item.replacement == null) {
                group.plainRows++
            } else {
                val aliasKey = item.phrase.lowercase(Locale.ROOT)
                if (aliasKey == termKey) {
                    duplicates++
                } else if (aliasKey in group.aliases) {
                    group.duplicateAliasSpellings++
                } else {
                    group.aliases[aliasKey] = item.phrase
                }
            }
        }

        duplicates += groups.values.sumOf { maxOf(0, it.plainRows - 1) + it.duplicateAliasSpellings }

        val aliasTargets = mutableMapOf<String, MutableSet<String>>()
        groups.forEach { (termKey, group) ->
            group.aliases.keys.forEach { aliasKey -> aliasTargets.getOrPut(aliasKey) { mutableSetOf() } += termKey }
        }
        val allTargetTerms = groups.keys
        val conflictingAliases = aliasTargets.filter { (aliasKey, targets) ->
            targets.size > 1 || (aliasKey in allTargetTerms && aliasKey !in targets) ||
                targets.any { target -> existingOwner[aliasKey]?.let { it != target } == true }
        }.keys

        val additions = mutableListOf<VocabularyEntry>()
        val updates = mutableListOf<WisprAliasUpdate>()
        var conflicts = conflictingAliases.size

        groups.forEach { (termKey, group) ->
            val old = existingByTerm[termKey]
            val existingAliasOwner = existingOwner[termKey]
            if (old == null && existingAliasOwner != null) {
                conflicts++
                return@forEach
            }
            if (old != null && group.plainRows > 0) duplicates++

            val freshAliases = group.aliases
                .filterKeys { it !in conflictingAliases }
                .filterKeys { aliasKey -> existingOwner[aliasKey] != termKey }
                .values.toList()
            val alreadySavedAliases = group.aliases.keys.count { aliasKey ->
                aliasKey !in conflictingAliases && existingOwner[aliasKey] == termKey
            }
            duplicates += alreadySavedAliases

            if (old == null) {
                additions += VocabularyEntry(group.term, freshAliases)
            } else if (freshAliases.isNotEmpty()) {
                updates += WisprAliasUpdate(old.term, freshAliases)
            }
        }

        return WisprDictionaryPreview(transfer.sourceCount, additions, updates, duplicates, conflicts)
    }

    /** Applies only the explicitly previewed additions while keeping existing boosts and aliases. */
    fun apply(existing: List<VocabularyEntry>, preview: WisprDictionaryPreview): List<VocabularyEntry> {
        val updates = preview.updates.associateBy { it.existingTerm.lowercase(Locale.ROOT) }
        val merged = existing.map { current ->
            val update = updates[current.term.lowercase(Locale.ROOT)]
            if (update == null) current else current.copy(aliases = current.aliases + update.aliases)
        } + preview.additions
        return VocabularyText.validate(merged)
    }
}
