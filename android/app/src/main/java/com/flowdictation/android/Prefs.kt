package com.flowdictation.android

import android.content.Context
import android.content.SharedPreferences

/** App settings persisted in SharedPreferences. Language is fixed to English. */
class Prefs(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var modelId: String
        get() = prefs.getString(KEY_MODEL, ModelCatalog.DEFAULT_MODEL_ID)
            ?: ModelCatalog.DEFAULT_MODEL_ID
        set(value) {
            prefs.edit().putString(KEY_MODEL, value).apply()
        }

    /** The app appearance is independent of the phone setting unless System is selected. */
    var themeMode: String
        get() = prefs.getString(KEY_THEME_MODE, THEME_MODE_LIGHT)
            ?.takeIf { it in THEME_MODES } ?: THEME_MODE_LIGHT
        set(value) {
            prefs.edit().putString(KEY_THEME_MODE, value.takeIf { it in THEME_MODES } ?: THEME_MODE_LIGHT).apply()
        }

    var bubbleEnabled: Boolean
        get() = prefs.getBoolean(KEY_BUBBLE, false)
        set(value) {
            prefs.edit().putBoolean(KEY_BUBBLE, value).apply()
        }

    /** Explicit consent for accessibility-based field detection and insertion. */
    var autoInputEnabled: Boolean
        get() = prefs.getBoolean("auto_input_enabled", false)
        set(value) { prefs.edit().putBoolean("auto_input_enabled", value).apply() }

    var holdToTalk: Boolean
        get() = prefs.getBoolean("hold_to_talk", false)
        set(value) { prefs.edit().putBoolean("hold_to_talk", value).apply() }

    var historyEnabled: Boolean
        get() = prefs.getBoolean("history_enabled", true)
        set(value) { prefs.edit().putBoolean("history_enabled", value).apply() }

    var bubbleSizeDp: Int
        get() = prefs.getInt("bubble_size_dp", 64).coerceIn(56, 160)
        set(value) { prefs.edit().putInt("bubble_size_dp", value.coerceIn(56, 160)).apply() }

    var idleUnloadMinutes: Int
        get() = prefs.getInt("idle_unload_minutes", 2).takeIf { it in IdleUnloadPolicy.MINUTES } ?: 2
        set(value) { prefs.edit().putInt("idle_unload_minutes", value.takeIf { it in IdleUnloadPolicy.MINUTES } ?: 2).apply() }

    var cleanupPrompt: Boolean
        get() = prefs.getBoolean("cleanup_prompt", false)
        set(value) { prefs.edit().putBoolean("cleanup_prompt", value).apply() }

    var learnFromEdits: Boolean
        get() = prefs.getBoolean("learn_from_edits", true)
        set(value) { prefs.edit().putBoolean("learn_from_edits", value).apply() }

    var boostQuietVoice: Boolean
        get() = prefs.getBoolean("boost_quiet_voice", true)
        set(value) { prefs.edit().putBoolean("boost_quiet_voice", value).apply() }

    var sensitiveVad: Boolean
        get() = prefs.getBoolean("sensitive_vad", boostQuietVoice)
        set(value) { prefs.edit().putBoolean("sensitive_vad", value).apply() }

    var spokenCommands: Boolean
        get() = prefs.getBoolean("spoken_commands", true)
        set(value) { prefs.edit().putBoolean("spoken_commands", value).apply() }

    var lastModelLoadMs: Long
        get() = prefs.getLong("last_model_load_ms", -1)
        set(value) { prefs.edit().putLong("last_model_load_ms", value).apply() }

    var lastLoadedModel: String
        get() = prefs.getString("last_loaded_model", "").orEmpty()
        set(value) { prefs.edit().putString("last_loaded_model", value).apply() }

    var lastDictationTiming: String
        get() = prefs.getString("last_dictation_timing", "Stop-to-text time: not measured yet").orEmpty()
        set(value) { prefs.edit().putString("last_dictation_timing", value).apply() }

    companion object {
        private const val PREFS_NAME = "flow_dictation"
        private const val KEY_MODEL = "model_id"
        private const val KEY_BUBBLE = "bubble_enabled"
        private const val KEY_THEME_MODE = "theme_mode"

        const val THEME_MODE_LIGHT = "light"
        const val THEME_MODE_DARK = "dark"
        const val THEME_MODE_SYSTEM = "system"
        private val THEME_MODES = setOf(THEME_MODE_LIGHT, THEME_MODE_DARK, THEME_MODE_SYSTEM)

        /** Language is fixed; there is intentionally no language setting. */
        const val LANGUAGE = "en"
    }
}
