package com.flowdictation.android

import android.content.Context
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

data class VocabularyEntry(val term: String, val aliases: List<String> = emptyList(), val boost: Double = 1.5)

/** Portable text format deliberately rejects separators rather than silently losing data. */
object VocabularyText {
    private fun phrase(value: String): String {
        val clean = value.trim().replace(Regex("\\s+"), " ")
        require(clean.isNotEmpty() && clean.length <= 200 && clean.none { it == '|' || it == ',' || it.isISOControl() }) {
            "Use a word or short phrase without commas or |."
        }
        return clean
    }
    fun normalize(entry: VocabularyEntry): VocabularyEntry {
        require(entry.boost.isFinite() && entry.boost in 1.0..3.0) { "Boost must be between 1.0 and 3.0." }
        val term = phrase(entry.term)
        return VocabularyEntry(term, entry.aliases.map(::phrase)
            .filterNot { it.equals(term, true) }.distinctBy { it.lowercase(Locale.ROOT) }, entry.boost)
    }
    fun validate(entries: List<VocabularyEntry>): List<VocabularyEntry> {
        require(entries.size <= 5000) { "Use at most 5,000 vocabulary entries." }
        val result = entries.map(::normalize)
        val owners = mutableMapOf<String, String>()
        result.forEach { entry ->
            (entry.aliases + entry.term).forEach { spelling ->
                val key = spelling.lowercase(Locale.ROOT)
                require(owners.put(key, entry.term) == null) { "The spelling '$spelling' is already used."
                }
            }
        }
        return result
    }
    fun parse(text: String): List<VocabularyEntry> = validate(text.lineSequence().filter { it.isNotBlank() }.mapIndexed { index, line ->
        val parts = line.split('|')
        require(parts.size <= 3) { "Line ${index + 1}: use term | aliases | boost."
        }
        val aliases = parts.getOrNull(1)?.trim().orEmpty().let {
            if (it.isBlank()) emptyList() else it.split(',').map(String::trim)
        }
        val score = parts.getOrNull(2)?.trim()?.takeIf { it.isNotEmpty() }?.let {
            it.toDoubleOrNull() ?: throw IllegalArgumentException("Line ${index + 1}: invalid boost.")
        } ?: 1.5
        VocabularyEntry(parts[0], aliases, score)
    }.toList())
    fun format(entries: List<VocabularyEntry>): String = validate(entries).joinToString("\n", postfix = if (entries.isEmpty()) "" else "\n") {
        "${it.term} | ${it.aliases.joinToString(", ")} | ${it.boost}"
    }
}

object VocabularyJson {
    fun format(entries: List<VocabularyEntry>): String = JSONArray().apply {
        VocabularyText.validate(entries).forEach { entry ->
            put(JSONObject().put("term", entry.term).put("aliases", JSONArray(entry.aliases)).put("boost", entry.boost))
        }
    }.toString(2)
    fun parse(text: String): List<VocabularyEntry> {
        val array = JSONArray(text)
        return VocabularyText.validate((0 until array.length()).map { i ->
            val row = array.getJSONObject(i)
            val aliases = if (row.has("aliases")) row.getJSONArray("aliases") else JSONArray()
            VocabularyEntry(row.getString("term"), (0 until aliases.length()).map(aliases::getString),
                if (row.has("boost")) row.getDouble("boost") else 1.5)
        })
    }
}

/** A damaged file fails visibly; no operation overwrites it with an empty fallback. */
class VocabularyStore(context: Context) {
    private val file = AtomicFile(File(context.filesDir, "vocabulary.json"))
    fun load(): List<VocabularyEntry> = synchronized(LOCK) {
        if (!file.baseFile.exists() && !File(file.baseFile.path + ".bak").exists()) emptyList()
        else file.openRead().bufferedReader(Charsets.UTF_8).use { VocabularyJson.parse(it.readText()) }
    }
    fun save(entries: List<VocabularyEntry>) = synchronized(LOCK) {
        val bytes = VocabularyJson.format(entries).toByteArray(Charsets.UTF_8)
        val stream = file.startWrite()
        try { stream.write(bytes); file.finishWrite(stream) }
        catch (error: Throwable) { file.failWrite(stream); throw error }
    }
    fun upsert(entry: VocabularyEntry, previousTerm: String = entry.term) = synchronized(LOCK) {
        save(load().filterNot { it.term.equals(previousTerm, true) } + entry)
    }
    /** Rechecks conflicts under the store lock, then atomically applies new words and aliases. */
    fun importWispr(transfer: WisprDictionaryTransfer): WisprDictionaryPreview = synchronized(LOCK) {
        val current = load()
        val preview = WisprDictionaryPortableImport.preview(current, transfer)
        if (preview.hasChanges) save(WisprDictionaryPortableImport.apply(current, preview))
        preview
    }
    fun delete(term: String) = synchronized(LOCK) { save(load().filterNot { it.term.equals(term, true) }) }
    fun revision(): Long = file.baseFile.lastModified()
    companion object { private val LOCK = Any() }
}
