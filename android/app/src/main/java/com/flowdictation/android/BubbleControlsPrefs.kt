package com.flowdictation.android

import android.content.Context
import android.content.SharedPreferences

/** Floating-button sizing and gesture settings, kept separate from general app preferences. */
internal class BubbleControlsPrefs(context: Context) {
    private val store: SharedPreferences =
        context.getSharedPreferences("flow_dictation", Context.MODE_PRIVATE)

    var bubbleSizeDp: Int
        get() = BubbleSizePolicy.clamp(store.getInt(KEY_SIZE, BubbleSizePolicy.DEFAULT_DP))
        set(value) { store.edit().putInt(KEY_SIZE, BubbleSizePolicy.clamp(value)).apply() }

    var longPressAction: BubbleGestureAction
        get() = action(KEY_LONG_PRESS, BubbleGestureAction.HOLD_TO_TALK)
        set(value) = saveAction(KEY_LONG_PRESS, value)

    var doubleTapAction: BubbleGestureAction
        get() = action(KEY_DOUBLE_TAP, BubbleGestureAction.NONE)
            .takeIf { BubbleGesturePolicy.isAllowedIdleTapAction(it) } ?: BubbleGestureAction.NONE
        set(value) = saveAction(KEY_DOUBLE_TAP,
            value.takeIf { BubbleGesturePolicy.isAllowedIdleTapAction(it) } ?: BubbleGestureAction.NONE)

    var tripleTapAction: BubbleGestureAction
        get() = action(KEY_TRIPLE_TAP, BubbleGestureAction.RESIZE)
            .takeIf { BubbleGesturePolicy.isAllowedIdleTapAction(it) } ?: BubbleGestureAction.NONE
        set(value) = saveAction(KEY_TRIPLE_TAP,
            value.takeIf { BubbleGesturePolicy.isAllowedIdleTapAction(it) } ?: BubbleGestureAction.NONE)

    private fun action(key: String, default: BubbleGestureAction) =
        store.getString(key, default.name)?.let { runCatching { BubbleGestureAction.valueOf(it) }.getOrNull() } ?: default

    private fun saveAction(key: String, action: BubbleGestureAction) {
        store.edit().putString(key, action.name).apply()
    }

    companion object {
        const val KEY_SIZE = "bubble_size_dp"
        const val KEY_LONG_PRESS = "bubble_long_press_action"
        const val KEY_DOUBLE_TAP = "bubble_double_tap_action"
        const val KEY_TRIPLE_TAP = "bubble_triple_tap_action"
    }
}
