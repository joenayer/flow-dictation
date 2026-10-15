package com.flowdictation.android

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.ListView
import android.widget.TextView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import java.text.DateFormat
import java.util.Date

class HistoryActivity : FlowActivity() {
    private lateinit var store: HistoryStore
    private lateinit var query: EditText
    private lateinit var list: ListView
    private val adapter = Entries()
    private var all: List<HistoryEntry> = emptyList()
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(R.layout.activity_history)
        applyInsets()
        store = HistoryStore(this)
        query = findViewById(R.id.search_history)
        list = findViewById(R.id.list_history)
        list.adapter = adapter
        list.emptyView = findViewById(R.id.empty_history)
        findViewById<Button>(R.id.back).setOnClickListener { finish() }
        query.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun afterTextChanged(s: Editable?) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { filter() }
        })
        list.setOnItemClickListener { _, _, position, _ -> openEntry(adapter.items[position]) }
        findViewById<Button>(R.id.export_history).setOnClickListener {
            exportText(HistoryText.format(all), "Flow-history.txt")
        }
    }
    override fun onResume() { super.onResume(); reload() }
    private fun reload() {
        all = store.load()
        findViewById<Button>(R.id.export_history).isEnabled = all.isNotEmpty()
        filter()
    }
    private fun filter() {
        val search = query.text.toString().trim()
        adapter.items = HistoryText.search(all, search)
        findViewById<TextView>(R.id.empty_history).text =
            if (search.isNotBlank() && all.isNotEmpty()) "No matches. Try another word."
            else "No saved dictations yet. Record something to get started."
        adapter.notifyDataSetChanged()
    }
    private fun openEntry(entry: HistoryEntry) {
        val actions = arrayOf("Open and edit", "Copy text", "Share text", "Delete", getString(R.string.show_original))
        MaterialAlertDialogBuilder(this).setTitle("Saved dictation").setItems(actions) { _, which ->
            when (which) {
                0 -> editEntry(entry)
                1 -> if (TextOutput.copy(this, entry.text)) message("Copied. Paste into your app.")
                2 -> if (!TextOutput.share(this, entry.text)) message("Could not share text.")
                4 -> MaterialAlertDialogBuilder(this).setTitle(R.string.show_original)
                    .setMessage(entry.originalText).setPositiveButton("Close", null).show()
                3 -> MaterialAlertDialogBuilder(this).setTitle("Delete this dictation?")
                    .setMessage("This removes the saved text from Flow. Export or copy it first if you need it.")
                    .setNegativeButton("Keep", null).setPositiveButton("Delete") { _, _ ->
                        runCatching { store.delete(entry.id) }.onSuccess { reload(); message("Dictation deleted.") }
                            .onFailure { message("Could not delete this dictation. Try again.") }
                    }.show()
            }
        }.show()
    }
    private fun editEntry(entry: HistoryEntry) {
        val input = EditText(this).apply {
            setText(entry.text)
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE or android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            minLines = 4
            maxLines = 10
            val padding = (20 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
        }
        val dialog = MaterialAlertDialogBuilder(this).setTitle("Edit dictation").setView(input)
            .setNegativeButton("Cancel", null).setNeutralButton("Copy", null).setPositiveButton("Save", null).create()
        dialog.setOnShowListener {
            dialog.getButton(-3).setOnClickListener { TextOutput.copy(this, input.text.toString()); message("Copied.") }
            dialog.getButton(-1).setOnClickListener {
                if (input.text.isBlank()) { input.error = "Enter some text, or delete the entry."; return@setOnClickListener }
                runCatching { check(store.update(entry.id, input.text.toString())) }.onSuccess {
                    dialog.dismiss(); reload(); message("Edits saved.")
                    VocabularyLearning.offer(this, entry.text, input.text.toString())
                }.onFailure { input.error = "Could not save. Copy your text first." }
            }
        }
        dialog.show()
    }
    private inner class Entries : BaseAdapter() {
        var items: List<HistoryEntry> = emptyList()
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = items[position].id
        override fun getView(position: Int, reused: View?, parent: ViewGroup): View {
            val view = reused ?: layoutInflater.inflate(R.layout.item_history, parent, false)
            val entry = items[position]
            view.findViewById<TextView>(R.id.row_text).text = entry.text
            view.findViewById<TextView>(R.id.row_meta).text =
                DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(entry.timestampMs)) +
                    " · " + entry.durationMs / 1000 + "s"
            return view
        }
    }
}
