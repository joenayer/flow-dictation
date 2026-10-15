package com.flowdictation.android

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import android.util.AtomicFile

/**
 * Simple file/JSON history store (internal storage, newest first, capped).
 */
class HistoryStore(context: Context) {
    private val file = File(context.filesDir, FILE_NAME)

    fun load(): List<HistoryEntry> = synchronized(STORE_LOCK) {
        if (!file.exists() && !File(file.path + ".bak").exists()) return@synchronized emptyList()
        try {
            val arr = JSONArray(AtomicFile(file).openRead().bufferedReader().use { it.readText() })
            List(arr.length()) { i -> fromJson(arr.getJSONObject(i)) }
        } catch (ignored: Exception) {
            emptyList()
        }
    }

    fun add(text: String, durationMs: Long, modelId: String, originalText: String = text): HistoryEntry = synchronized(STORE_LOCK) {
        val entries = load().toMutableList()
        val entry = HistoryEntry(
            id = maxOf(System.currentTimeMillis(), (entries.maxOfOrNull { it.id } ?: 0) + 1),
            timestampMs = System.currentTimeMillis(),
            text = text,
            durationMs = durationMs,
            modelId = modelId,
            originalText = originalText,
        )
        entries.add(0, entry)
        while (entries.size > MAX_ENTRIES) {
            entries.removeAt(entries.lastIndex)
        }
        save(entries)
        entry
    }

    fun clear() = synchronized(STORE_LOCK) {
        AtomicFile(file).delete()
    }

    fun update(id: Long, text: String) = synchronized(STORE_LOCK) {
        val entries = load()
        if (entries.none { it.id == id }) return@synchronized false
        save(entries.map { if (it.id == id) it.copy(text = text) else it })
        true
    }

    fun delete(id: Long) = synchronized(STORE_LOCK) {
        save(load().filterNot { it.id == id })
    }

    private fun save(entries: List<HistoryEntry>) {
        val arr = JSONArray()
        entries.forEach { arr.put(toJson(it)) }
        val atomic = AtomicFile(file)
        val output = atomic.startWrite()
        try {
            output.write(arr.toString().toByteArray(Charsets.UTF_8))
            atomic.finishWrite(output)
        } catch (e: Exception) {
            atomic.failWrite(output)
            throw e
        }
    }

    private fun toJson(e: HistoryEntry): JSONObject = JSONObject()
        .put("id", e.id)
        .put("timestampMs", e.timestampMs)
        .put("text", e.text)
        .put("durationMs", e.durationMs)
        .put("modelId", e.modelId)
        .put("originalText", e.originalText)

    private fun fromJson(o: JSONObject): HistoryEntry = HistoryEntry(
        id = o.optLong("id", 0L),
        timestampMs = o.optLong("timestampMs", 0L),
        text = o.optString("text", ""),
        durationMs = o.optLong("durationMs", 0L),
        modelId = o.optString("modelId", ""),
        originalText = o.optString("originalText", o.optString("text", "")),
    )

    companion object {
        private val STORE_LOCK = Any()
        private const val FILE_NAME = "history.json"
        private const val MAX_ENTRIES = 200
    }
}
