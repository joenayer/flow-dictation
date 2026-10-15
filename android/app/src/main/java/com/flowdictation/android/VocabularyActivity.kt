package com.flowdictation.android

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.button.MaterialButton

class VocabularyActivity : FlowActivity() {
    private lateinit var rows: LinearLayout
    private val store by lazy { VocabularyStore(this) }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        root.addView(TextView(this).apply { text = getString(R.string.vocabulary_title); textSize = 26f })
        root.addView(TextView(this).apply { text = getString(R.string.vocabulary_help) })
        fun button(title: String, action: () -> Unit) { root.addView(MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply { text = title; setOnClickListener { action() } }) }
        button(getString(R.string.vocabulary_back)) { finish() }
        button(getString(R.string.vocabulary_add_phrase)) { edit(null) }
        button(getString(R.string.wispr_import_button)) { startActivity(Intent(this, WisprDictionaryImportActivity::class.java)) }
        button(getString(R.string.vocabulary_import)) { importFile() }
        button(getString(R.string.vocabulary_export)) { runCatching { exportText(VocabularyText.format(store.load()), "Flow-vocabulary.txt") }.onFailure { message(getString(R.string.vocabulary_read_error)) } }
        rows = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(rows)
        setContentView(ScrollView(this).apply {
            isFillViewport = true
            addView(root)
        }); applyInsets(); reload()
    }
    override fun onResume() { super.onResume(); if (::rows.isInitialized) reload() }
    private fun reload() {
        rows.removeAllViews()
        runCatching { store.load() }.onSuccess { entries ->
            if (entries.isEmpty()) rows.addView(TextView(this).apply { text = getString(R.string.vocabulary_empty) })
            entries.forEach { entry -> rows.addView(MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
                text = entry.term + if (entry.aliases.isEmpty()) "" else "\n" + getString(R.string.vocabulary_heard_as, entry.aliases.joinToString(", "))
                contentDescription = getString(R.string.vocabulary_edit_label, entry.term)
                setOnClickListener { edit(entry) }
            }) }
        }.onFailure { message(getString(R.string.vocabulary_read_error)) }
    }
    private fun edit(entry: VocabularyEntry?) {
        val form = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 0, 32, 0) }
        val term = EditText(this).apply { hint = getString(R.string.vocabulary_term); setText(entry?.term.orEmpty()) }
        val aliases = EditText(this).apply { hint = getString(R.string.vocabulary_aliases); setText(entry?.aliases?.joinToString(", ").orEmpty()) }
        val boost = EditText(this).apply { hint = getString(R.string.vocabulary_boost); inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL; setText((entry?.boost ?: 1.5).toString()) }
        fun labeled(field: EditText, label: Int) {
            field.id = android.view.View.generateViewId()
            form.addView(TextView(this).apply { text = getString(label); labelFor = field.id })
            form.addView(field)
        }
        labeled(term, R.string.vocabulary_term); labeled(aliases, R.string.vocabulary_aliases); labeled(boost, R.string.vocabulary_boost)
        val builder = MaterialAlertDialogBuilder(this).setTitle(if (entry == null) getString(R.string.vocabulary_add_title) else getString(R.string.vocabulary_edit_title))
            .setView(form).setNegativeButton(getString(R.string.vocabulary_cancel), null).setPositiveButton(getString(R.string.vocabulary_save), null)
        if (entry != null) builder.setNeutralButton(getString(R.string.vocabulary_delete)) { _, _ ->
            MaterialAlertDialogBuilder(this).setTitle(getString(R.string.vocabulary_delete_title, entry.term)).setNegativeButton(getString(R.string.vocabulary_keep), null)
                .setPositiveButton(getString(R.string.vocabulary_delete)) { _, _ -> runCatching { store.delete(entry.term) }.onSuccess { reload() }.onFailure { message(getString(R.string.vocabulary_delete_error)) } }.show()
        }
        val dialog = builder.create()
        dialog.setOnShowListener { dialog.getButton(-1).setOnClickListener {
            runCatching {
                val parsed = VocabularyText.parse("${term.text} | ${aliases.text} | ${boost.text}").single()
                store.upsert(parsed, entry?.term ?: parsed.term)
            }.onSuccess { dialog.dismiss(); reload() }.onFailure { term.error = it.message ?: getString(R.string.vocabulary_save_error) }
        } }
        dialog.show()
    }
    @Suppress("DEPRECATION")
    private fun importFile() {
        try { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("text/plain"), IMPORT) }
        catch (_: Exception) { message(getString(R.string.vocabulary_picker_error)) }
    }
    @Deprecated("Framework result compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != IMPORT || resultCode != Activity.RESULT_OK) return
        val uri = data?.data ?: return
        Thread {
            val result = runCatching { contentResolver.openInputStream(uri)?.bufferedReader(Charsets.UTF_8)?.use {
                val text = it.readTextLimited(2_000_000)
                VocabularyText.parse(text)
            } ?: error(getString(R.string.vocabulary_open_error)) }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                result.onSuccess { incoming ->
                MaterialAlertDialogBuilder(this).setTitle(getString(R.string.vocabulary_import_title, incoming.size))
                    .setMessage(getString(R.string.vocabulary_import_help))
                    .setNegativeButton(getString(R.string.vocabulary_cancel), null).setPositiveButton(getString(R.string.vocabulary_import_confirm)) { _, _ ->
                        runCatching {
                            val terms = incoming.map { it.term.lowercase(java.util.Locale.ROOT) }.toSet()
                            store.save(store.load().filterNot { it.term.lowercase(java.util.Locale.ROOT) in terms } + incoming)
                        }.onSuccess { reload(); message(getString(R.string.vocabulary_imported)) }.onFailure { message(it.message ?: getString(R.string.vocabulary_import_error)) }
                    }.show()
            }.onFailure { message(it.message ?: getString(R.string.vocabulary_import_error)) } }
        }.start()
    }
    private fun java.io.Reader.readTextLimited(limit: Int): String {
        val buffer = CharArray(4096); val output = StringBuilder()
        while (true) { val count = read(buffer); if (count < 0) break; require(output.length + count <= limit) { getString(R.string.vocabulary_size_error) }; output.append(buffer, 0, count) }
        return output.toString()
    }
    companion object { private const val IMPORT = 91 }
}
