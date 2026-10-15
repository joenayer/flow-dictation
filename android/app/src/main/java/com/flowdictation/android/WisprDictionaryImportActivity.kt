package com.flowdictation.android

import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.button.MaterialButton
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction

class WisprDictionaryImportActivity : FlowActivity() {
    private val store by lazy { VocabularyStore(this) }
    private lateinit var content: LinearLayout
    private lateinit var status: TextView
    private lateinit var importButton: Button
    private lateinit var chooseButton: Button
    private var normalStatusColor: Int = 0
    private var pendingTransfer: WisprDictionaryTransfer? = null
    private var importing = false
    private var reading = false
    private var readRequestId = 0

    private val chooseFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) readTransferFile(uri)
    }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (20 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        page.addView(TextView(this).apply {
            text = getString(R.string.wispr_import_title)
            textSize = 26f
        })
        page.addView(TextView(this).apply {
            text = getString(R.string.wispr_import_instructions)
            textSize = 16f
        })
        chooseButton = MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            text = getString(R.string.wispr_import_choose)
            setOnClickListener { chooseFile.launch(arrayOf("application/json", "text/plain", "application/octet-stream")) }
        }
        page.addView(chooseButton)
        status = TextView(this).apply {
            text = getString(R.string.wispr_import_no_file)
            textSize = 16f
            val top = (12 * resources.displayMetrics.density).toInt()
            setPadding(0, top, 0, top)
        }
        normalStatusColor = status.currentTextColor
        page.addView(status)
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        page.addView(content)
        importButton = MaterialButton(this).apply {
            text = getString(R.string.wispr_import_confirm, 0, 0)
            isEnabled = false
            setOnClickListener { importEntries() }
        }
        page.addView(importButton)
        page.addView(MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            text = getString(R.string.vocabulary_back)
            setOnClickListener { finish() }
        })
        setContentView(ScrollView(this).apply {
            isFillViewport = true
            addView(page)
        })
        applyInsets()
    }

    private fun readTransferFile(uri: android.net.Uri) {
        if (importing) return
        val requestId = ++readRequestId
        reading = true
        chooseButton.isEnabled = false
        pendingTransfer = null
        importButton.isEnabled = false
        status.setText(R.string.wispr_import_reading)
        content.removeAllViews()
        Thread {
            val result = runCatching {
                val text = contentResolver.openInputStream(uri)?.use { it.readUtf8Limited() }
                    ?: error(getString(R.string.vocabulary_open_error))
                val transfer = WisprDictionaryPortableImport.parse(text)
                val preview = WisprDictionaryPortableImport.preview(store.load(), transfer)
                transfer to preview
            }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (requestId != readRequestId) return@runOnUiThread
                reading = false
                chooseButton.isEnabled = !importing
                result.onSuccess { (transfer, preview) -> showPreview(transfer, preview) }
                    .onFailure { showError(it.message ?: getString(R.string.wispr_import_error)) }
            }
        }.start()
    }

    private fun showPreview(transfer: WisprDictionaryTransfer, preview: WisprDictionaryPreview) {
        pendingTransfer = transfer
        status.setTextColor(normalStatusColor)
        status.text = getString(
            R.string.wispr_import_preview_counts,
            preview.sourceCount,
            preview.newWordCount,
            preview.newCorrectionCount,
            preview.duplicateCount,
            preview.conflictCount,
        )
        content.removeAllViews()
        content.addView(TextView(this).apply { text = getString(R.string.wispr_import_preview_help) })
        val previewRows = preview.additions.map { entry ->
            entry.term to entry.aliases
        } + preview.updates.map { update -> update.existingTerm to update.aliases }
        previewRows.take(8).forEach { (term, aliases) ->
            content.addView(TextView(this).apply {
                text = term + if (aliases.isEmpty()) "" else
                    "\n" + getString(R.string.vocabulary_heard_as, aliases.joinToString(", "))
                val pad = (8 * resources.displayMetrics.density).toInt()
                setPadding(0, pad, 0, pad)
            })
        }
        if (previewRows.size > 8) content.addView(TextView(this).apply {
            text = getString(R.string.wispr_import_more, previewRows.size - 8)
        })
        importButton.text = getString(R.string.wispr_import_confirm, preview.newWordCount, preview.newCorrectionCount)
        importButton.isEnabled = preview.hasChanges
    }

    private fun showError(message: String) {
        pendingTransfer = null
        status.text = message
        status.setTextColor(getColor(com.google.android.material.R.color.design_default_color_error))
        content.removeAllViews()
        importButton.isEnabled = false
        chooseButton.isEnabled = !reading && !importing
    }

    private fun importEntries() {
        val transfer = pendingTransfer ?: return
        if (importing) return
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.wispr_import_confirm_title)
            .setMessage(R.string.wispr_import_confirm_help)
            .setNegativeButton(R.string.vocabulary_cancel, null)
            .setPositiveButton(R.string.wispr_import_confirm_action) { _, _ ->
                importing = true
                chooseButton.isEnabled = false
                importButton.isEnabled = false
                Thread {
                    val result = runCatching { store.importWispr(transfer) }
                    runOnUiThread {
                        if (isFinishing || isDestroyed) return@runOnUiThread
                        importing = false
                        chooseButton.isEnabled = !reading
                        result.onSuccess { saved ->
                            pendingTransfer = null
                            status.setTextColor(normalStatusColor)
                            status.text = getString(
                                R.string.wispr_imported,
                                saved.newWordCount,
                                saved.newCorrectionCount,
                                saved.duplicateCount,
                                saved.conflictCount,
                            )
                            content.removeAllViews()
                            importButton.text = getString(R.string.wispr_import_confirm, 0, 0)
                            importButton.isEnabled = false
                        }.onFailure {
                            showError(it.message ?: getString(R.string.wispr_import_error))
                        }
                    }
                }.start()
            }.show()
    }

    private fun java.io.InputStream.readUtf8Limited(): String {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(8_192)
        while (true) {
            val count = read(buffer)
            if (count < 0) break
            require(output.size() + count <= WisprDictionaryPortableImport.MAX_BYTES) {
                getString(R.string.vocabulary_size_error)
            }
            output.write(buffer, 0, count)
        }
        val decoder = Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
        return try { decoder.decode(ByteBuffer.wrap(output.toByteArray())).toString() }
        catch (_: Exception) { throw IllegalArgumentException(getString(R.string.wispr_import_encoding_error)) }
    }

}
