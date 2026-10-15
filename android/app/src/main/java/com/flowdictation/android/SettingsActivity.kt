package com.flowdictation.android
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.RadioGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatDelegate
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.radiobutton.MaterialRadioButton
import com.google.android.material.switchmaterial.SwitchMaterial

class SettingsActivity : FlowActivity() {
    private lateinit var prefs: Prefs
    private lateinit var repository: ModelImportRepository
    private var displayedModels: String? = null
    private val importListener: () -> Unit = { refreshModels() }
    private val inputListener: () -> Unit = { refreshAutomaticTyping() }
    private var updatingAutomaticTyping = false
    private var pendingAutomaticBubble = false
    private lateinit var updater: AppUpdater
    override fun onResume() {
        super.onResume()
        AutoInputBridge.addListener(inputListener)
        AutoInputBridge.refresh()
        if (pendingAutomaticBubble && prefs.autoInputEnabled && Settings.canDrawOverlays(this)) {
            pendingAutomaticBubble = false
            enableAutomaticBubble()
        } else if (prefs.autoInputEnabled && prefs.bubbleEnabled && Settings.canDrawOverlays(this)) {
            syncBubble(true)
        }
        refreshAutomaticTyping()
        refreshDebugLine()
    }
    override fun onPause() {
        AutoInputBridge.removeListener(inputListener)
        super.onPause()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("pending_automatic_bubble", pendingAutomaticBubble)
        super.onSaveInstanceState(outState)
    }
    override fun onStart() { super.onStart(); ModelImportJob.register(importListener) }
    override fun onStop() { ModelImportJob.unregister(importListener); super.onStop() }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(R.layout.activity_settings)
        applyInsets()
        prefs = Prefs(this)
        findViewById<Button>(R.id.vocabulary).setOnClickListener {
            startActivity(Intent(this, VocabularyActivity::class.java))
        }
        findViewById<SwitchMaterial>(R.id.learn_edits_switch).apply {
            isChecked = prefs.learnFromEdits
            setOnCheckedChangeListener { _, checked -> prefs.learnFromEdits = checked }
        }
        findViewById<SwitchMaterial>(R.id.boost_quiet_switch).apply {
            isChecked = prefs.boostQuietVoice
            setOnCheckedChangeListener { _, checked ->
                prefs.boostQuietVoice = checked
                findViewById<SwitchMaterial>(R.id.sensitive_vad_switch).isChecked = prefs.sensitiveVad
            }
        }
        findViewById<SwitchMaterial>(R.id.sensitive_vad_switch).apply {
            isChecked = prefs.sensitiveVad
            setOnCheckedChangeListener { _, checked -> prefs.sensitiveVad = checked }
        }
        findViewById<SwitchMaterial>(R.id.spoken_commands_switch).apply {
            isChecked = prefs.spokenCommands
            setOnCheckedChangeListener { _, checked -> prefs.spokenCommands = checked }
        }
        findViewById<TextView>(R.id.parakeet_credit).apply {
            val credit = android.text.SpannableString(getString(R.string.parakeet_credit))
            credit.setSpan(android.text.style.URLSpan("https://creativecommons.org/licenses/by/4.0/"),
                0, credit.length, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            text = credit
            movementMethod = android.text.method.LinkMovementMethod.getInstance()
        }
        updater = AppUpdater(this)
        repository = ModelImportRepository(applicationContext)
        pendingAutomaticBubble = state?.getBoolean("pending_automatic_bubble") ?: false
        findViewById<SwitchMaterial>(R.id.automatic_typing_switch).setOnCheckedChangeListener { _, checked ->
            if (!updatingAutomaticTyping) {
                prefs.autoInputEnabled = checked
                if (checked) enableAutomaticBubble() else {
                    pendingAutomaticBubble = false
                    prefs.bubbleEnabled = false
                    syncBubble(false)
                }
                AutoInputBridge.refresh()
                refreshAutomaticTyping()
            }
        }
        findViewById<Button>(R.id.automatic_typing_settings).setOnClickListener {
            if (prefs.autoInputEnabled && !Settings.canDrawOverlays(this)) enableAutomaticBubble()
            else try { startActivity(AutoInputBridge.settingsIntent(this)) }
            catch (_: Exception) { message(getString(R.string.automatic_typing_open_settings_failed)) }
        }
        findViewById<Button>(R.id.automatic_typing_restricted_help).setOnClickListener {
            MaterialAlertDialogBuilder(this).setTitle(R.string.automatic_typing_restricted_help)
                .setMessage(R.string.automatic_typing_restricted_message)
                .setNegativeButton(R.string.automatic_typing_got_it, null)
                .setPositiveButton(R.string.automatic_typing_app_settings) { _, _ ->
                    try {
                        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.parse("package:" + packageName)))
                    } catch (_: Exception) { message(getString(R.string.automatic_typing_open_settings_failed)) }
                }.show()
        }
        findViewById<Button>(R.id.check_updates).setOnClickListener {
            checkUpdates()
        }
        findViewById<SwitchMaterial>(R.id.cleanup_prompt_switch).apply {
            isChecked = prefs.cleanupPrompt
            setOnCheckedChangeListener { _, checked -> prefs.cleanupPrompt = checked }
        }
        findViewById<Button>(R.id.idle_unload).apply {
            text = "Free speech model after ${prefs.idleUnloadMinutes} min idle"
            setOnClickListener {
                MaterialAlertDialogBuilder(this@SettingsActivity).setTitle("Free speech model after")
                    .setSingleChoiceItems(IdleUnloadPolicy.MINUTES.map { "$it min idle" }.toTypedArray(),
                        IdleUnloadPolicy.MINUTES.indexOf(prefs.idleUnloadMinutes)) { dialog, index ->
                        prefs.idleUnloadMinutes = IdleUnloadPolicy.MINUTES[index]
                        text = "Free speech model after ${prefs.idleUnloadMinutes} min idle"
                        refreshBubbleSettings()
                        dialog.dismiss()
                    }.setNegativeButton("Cancel", null).show()
            }
        }
        refreshAutomaticTyping()
        findViewById<Button>(R.id.back).setOnClickListener { finish() }
        findViewById<Button>(R.id.bubble_controls).setOnClickListener {
            startActivity(Intent(this, BubbleControlsActivity::class.java))
        }
        val themeGroup = findViewById<RadioGroup>(R.id.theme_mode_group)
        when (prefs.themeMode) {
            Prefs.THEME_MODE_DARK -> themeGroup.check(R.id.theme_dark)
            Prefs.THEME_MODE_SYSTEM -> themeGroup.check(R.id.theme_system)
            else -> themeGroup.check(R.id.theme_light)
        }
        themeGroup.setOnCheckedChangeListener { _, checkedId ->
            val mode = when (checkedId) {
                R.id.theme_dark -> Prefs.THEME_MODE_DARK
                R.id.theme_system -> Prefs.THEME_MODE_SYSTEM
                else -> Prefs.THEME_MODE_LIGHT
            }
            if (prefs.themeMode != mode) {
                prefs.themeMode = mode
                AppCompatDelegate.setDefaultNightMode(when (mode) {
                    Prefs.THEME_MODE_DARK -> AppCompatDelegate.MODE_NIGHT_YES
                    Prefs.THEME_MODE_SYSTEM -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
                    else -> AppCompatDelegate.MODE_NIGHT_NO
                })
            }
        }
        findViewById<SwitchMaterial>(R.id.hold_switch).apply {
            isChecked = prefs.holdToTalk
            setOnCheckedChangeListener { _, checked -> prefs.holdToTalk = checked }
        }
        findViewById<SwitchMaterial>(R.id.history_switch).apply {
            isChecked = prefs.historyEnabled
            setOnCheckedChangeListener { _, checked -> prefs.historyEnabled = checked }
        }
        findViewById<Button>(R.id.clear_history).setOnClickListener {
            MaterialAlertDialogBuilder(this).setTitle("Delete all history?")
                .setMessage("All saved dictations will be removed from Flow. Export them from History first if you need a copy.")
                .setNegativeButton("Keep history", null).setPositiveButton("Delete all") { _, _ ->
                    runCatching { HistoryStore(this).clear() }
                        .onSuccess { message("History deleted.") }
                        .onFailure { message("Could not delete history. Try again.") }
                }.show()
        }
        findViewById<Button>(R.id.app_permissions).setOnClickListener {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + packageName)))
        }
        findViewById<Button>(R.id.model_download).setOnClickListener { chooseDownload() }
        findViewById<Button>(R.id.import_model).setOnClickListener { chooseImport() }
        findViewById<Button>(R.id.model_cancel).setOnClickListener { ModelImportJob.cancel() }
        @Suppress("DEPRECATION")
        val version = packageManager.getPackageInfo(packageName, 0).versionName
        findViewById<TextView>(R.id.app_version).text = "Flow $version · On-device English dictation"
        refreshModels()
        refreshDebugLine()
    }

    private fun refreshBubbleSettings() {
        if (prefs.bubbleEnabled) runCatching { startService(DictationService.refreshAutoBubbleIntent(this)) }
    }

    private fun refreshDebugLine() {
        if (!::prefs.isInitialized) return
        val loadTime = if (prefs.lastModelLoadMs < 0)
            "Speech model load time: not measured yet" else
            "Last speech model load: ${prefs.lastModelLoadMs} ms · ${prefs.lastLoadedModel}"
        findViewById<TextView>(R.id.model_load_time).text = "$loadTime\n\n${prefs.lastDictationTiming}"
    }

    private fun checkUpdates() {
        val button = findViewById<Button>(R.id.check_updates)
        button.isEnabled = false
        button.text = "Checking for updates…"
        updater.checkForUpdates(this) { result ->
            if (isFinishing || isDestroyed) return@checkForUpdates
            button.isEnabled = true
            button.setText(R.string.check_updates)
            when (result) {
                is AppUpdater.CheckResult.Available -> MaterialAlertDialogBuilder(this)
                    .setTitle("Flow ${result.update.versionName} is available")
                    .setMessage("Download the update, then approve installation on your phone. Your history and settings stay in Flow.")
                    .setNegativeButton("Later", null)
                    .setPositiveButton("Download and install") { _, _ ->
                        button.isEnabled = false
                        updater.downloadAndInstall(this, result.update, onProgress = { done, total ->
                            if (!isDestroyed) button.text = if (total > 0) "Downloading ${done * 100 / total}%" else "Downloading update…"
                        }) { install ->
                            if (!isDestroyed) {
                                button.isEnabled = true
                                button.setText(R.string.check_updates)
                                if (install is AppUpdater.InstallResult.Failed) message(install.message)
                            }
                        }
                    }.show()
                AppUpdater.CheckResult.UpToDate -> message("You have the latest Android version.")
                AppUpdater.CheckResult.BrowserFallback -> Unit
                is AppUpdater.CheckResult.Failed -> message(result.message)
            }
        }
    }

    private fun refreshAutomaticTyping() {
        updatingAutomaticTyping = true
        findViewById<SwitchMaterial>(R.id.automatic_typing_switch).isChecked = prefs.autoInputEnabled
        updatingAutomaticTyping = false
        val enabled = AutoInputBridge.isServiceEnabled(this)
        val overlay = Settings.canDrawOverlays(this)
        findViewById<TextView>(R.id.automatic_typing_status).setText(when {
            !prefs.autoInputEnabled -> R.string.automatic_typing_off
            !overlay -> R.string.automatic_typing_overlay_needed
            !enabled -> R.string.automatic_typing_permission_needed
            !prefs.bubbleEnabled -> R.string.automatic_typing_paused
            !AutoInputBridge.connected -> R.string.automatic_typing_connecting
            else -> R.string.automatic_typing_ready
        })
        findViewById<Button>(R.id.automatic_typing_restricted_help).visibility =
            if (prefs.autoInputEnabled && !enabled) View.VISIBLE else View.GONE
        findViewById<Button>(R.id.automatic_typing_settings).apply {
            isEnabled = prefs.autoInputEnabled || enabled
            setText(when {
                prefs.autoInputEnabled && !overlay -> R.string.automatic_typing_allow_overlay
                enabled -> R.string.automatic_typing_manage
                else -> R.string.automatic_typing_enable
            })
        }
    }

    private fun enableAutomaticBubble() {
        if (!Settings.canDrawOverlays(this)) {
            pendingAutomaticBubble = true
            try {
                startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + packageName)))
            } catch (_: Exception) { message("Open phone settings and allow Flow to appear on top.") }
            return
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        }
        prefs.bubbleEnabled = true
        if (!syncBubble(true)) prefs.bubbleEnabled = false
        refreshAutomaticTyping()
    }

    private fun syncBubble(enabled: Boolean): Boolean = try {
        if (enabled) startForegroundService(DictationService.setBubbleIntent(this, true))
        else startService(DictationService.setBubbleIntent(this, false))
        true
    } catch (_: Exception) {
        message("Could not update the floating microphone. Reopen Flow and try again.")
        false
    }

    private fun refreshModels() {
        val group = findViewById<RadioGroup>(R.id.rg_models)
        val info = findViewById<TextView>(R.id.tv_model_info)
        val available = ModelCatalog.models.associate { it.id to repository.isAvailable(it) }
        val stamp = available.toString() + ModelImportJob.isRunning + prefs.modelId
        if (displayedModels != stamp) {
            displayedModels = stamp
            group.setOnCheckedChangeListener(null)
            group.removeAllViews()
            ModelCatalog.models.forEach { spec ->
                group.addView(MaterialRadioButton(this).apply {
                    text = spec.displayName + if (available[spec.id] == true) "" else " (not installed)"
                    tag = spec.id
                    id = View.generateViewId()
                    isEnabled = available[spec.id] == true && !ModelImportJob.isRunning
                    minHeight = (56 * resources.displayMetrics.density).toInt()
                })
            }
            fun showModel(modelId: String) {
                ModelCatalog.spec(modelId)?.let {
                    info.text = it.blurb + "\nEnglish · " + it.license + " license · about " + it.approxSizeMb + " MB on device."
                }
            }
            val current = prefs.modelId.takeIf { available[it] == true }
                ?: available.entries.firstOrNull { it.value }?.key
            if (current != null) {
                prefs.modelId = current
                (0 until group.childCount).map { group.getChildAt(it) as MaterialRadioButton }
                    .firstOrNull { it.tag == current }?.isChecked = true
                showModel(current)
            } else info.text = "This installation is missing its bundled speech model. Install the complete preview APK."
            group.setOnCheckedChangeListener { _, checkedId ->
                val button = group.findViewById<MaterialRadioButton>(checkedId) ?: return@setOnCheckedChangeListener
                if (button.isEnabled) { prefs.modelId = button.tag as String; showModel(prefs.modelId) }
            }
        }
        findViewById<Button>(R.id.model_download).isEnabled = !ModelImportJob.isRunning
        findViewById<Button>(R.id.import_model).isEnabled = !ModelImportJob.isRunning
        findViewById<Button>(R.id.model_cancel).visibility = if (ModelImportJob.isRunning) View.VISIBLE else View.GONE
        val status = findViewById<TextView>(R.id.model_import_status)
        if (status.text.toString() != ModelImportJob.status) status.text = ModelImportJob.status
    }

    private fun chooseDownload() {
        if (!readyForModelWork()) return
        val missing = ModelCatalog.models.filter { !repository.isAvailable(it) }
        if (missing.isEmpty()) { message("All supported models are already installed."); return }
        MaterialAlertDialogBuilder(this).setTitle("Download a speech model")
            .setItems(missing.map { it.displayName }.toTypedArray()) { _, index ->
                val spec = missing[index]
                MaterialAlertDialogBuilder(this).setTitle(spec.displayName)
                    .setMessage(spec.blurb + "\n\nEnglish · " + spec.license + " license\nAbout " + spec.approxSizeMb +
                        " MB installed. Download: " + (spec.archiveSizeBytes / 1_000_000) + " MB.\nKeep about " +
                        spec.installationSpaceMb + " MB free while installing.\nThe download uses the internet; speech processing stays on your phone.")
                    .setNegativeButton("Cancel", null)
                    .setPositiveButton("Download") { _, _ -> ModelImportJob.download(this, spec) }.show()
            }.setNegativeButton("Cancel", null).show()
    }

    private fun readyForModelWork(): Boolean {
        if (DictationEvents.state != DictState.IDLE) {
            message("Finish or discard the recording before adding a model.")
            return false
        }
        return !ModelImportJob.isRunning
    }

    @Suppress("DEPRECATION")
    private fun chooseImport() {
        if (!readyForModelWork()) return
        try {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), IMPORT_MODEL)
        } catch (_: Exception) { message("No file picker is available on this phone.") }
    }

    @Deprecated("Framework result compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == IMPORT_MODEL && resultCode == Activity.RESULT_OK) {
            data?.data?.let { ModelImportJob.start(this, it) }
        }
    }
    companion object { private const val IMPORT_MODEL = 91 }
}
