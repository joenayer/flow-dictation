package com.flowdictation.android

/** Visibility alone never starts microphone capture. Active controls remain reachable. */
internal object AutoBubblePolicy {
    fun shouldShow(enabled: Boolean, automatic: Boolean, eligible: Boolean, active: Boolean): Boolean =
        enabled && (!automatic || eligible || active)
}
