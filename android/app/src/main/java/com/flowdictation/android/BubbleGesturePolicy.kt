package com.flowdictation.android

/** Actions that can be assigned to a floating bubble gesture. */
internal enum class BubbleGestureAction {
    HOLD_TO_TALK,
    RESIZE,
    PAUSE_RESUME,
    DISCARD,
    OPEN_FLOW,
    OPEN_SETTINGS,
    NONE,
}

/** Side-effect-free decisions for touch handling and tap-sequence timing. */
internal object BubbleGesturePolicy {
    enum class Decision { NONE, PENDING, START, STOP, CANCEL, DISCARD, RESIZE, PAUSE_RESUME, OPEN_FLOW, OPEN_SETTINGS, PAUSE, RESUME }

    const val MULTI_TAP_GAP_MS = 300L
    const val ACTIVE_TAP_SUPPRESSION_MS = 500L

    fun onHold(recordingAtDown: Boolean, idleAtDown: Boolean, dragged: Boolean): Decision =
        when {
            dragged -> Decision.NONE
            recordingAtDown -> Decision.PAUSE
            idleAtDown -> Decision.START
            else -> Decision.NONE
        }

    /** A configured long hold toggles pause state; unlike hold-to-talk it survives release. */
    fun onPauseResumeToggle(currentlyPaused: Boolean): Decision =
        if (currentlyPaused) Decision.RESUME else Decision.PAUSE

    fun onHoldRelease(pauseFired: Boolean, holdFired: Boolean, dragged: Boolean): Decision =
        when {
            pauseFired -> Decision.RESUME
            holdFired -> Decision.STOP
            dragged -> Decision.NONE
            else -> Decision.NONE
        }

    fun onCancel(holdFired: Boolean, pauseFired: Boolean = false): Decision =
        if (pauseFired) Decision.RESUME else if (holdFired) Decision.CANCEL else Decision.NONE

    fun actionDecision(action: BubbleGestureAction): Decision = when (action) {
        BubbleGestureAction.RESIZE -> Decision.RESIZE
        BubbleGestureAction.PAUSE_RESUME -> Decision.PAUSE_RESUME
        BubbleGestureAction.DISCARD -> Decision.DISCARD
        BubbleGestureAction.OPEN_FLOW -> Decision.OPEN_FLOW
        BubbleGestureAction.OPEN_SETTINGS -> Decision.OPEN_SETTINGS
        BubbleGestureAction.NONE, BubbleGestureAction.HOLD_TO_TALK -> Decision.NONE
    }

    fun isAllowedIdleTapAction(action: BubbleGestureAction): Boolean = when (action) {
        BubbleGestureAction.RESIZE, BubbleGestureAction.OPEN_FLOW,
        BubbleGestureAction.OPEN_SETTINGS, BubbleGestureAction.NONE -> true
        else -> false
    }

    fun ownsPinch(resizeMode: Boolean, pointerCount: Int): Boolean =
        resizeMode && pointerCount >= 2

    fun exitsResizeModeOnRelease(resizeMode: Boolean, dragged: Boolean, pinched: Boolean, longPressed: Boolean): Boolean =
        resizeMode && !dragged && !pinched && !longPressed
}

/**
 * Recognizes idle tap sequences while keeping active Stop immediate. A lone idle
 * tap waits only long enough to distinguish the configured double/triple actions.
 * Active taps stop/cancel at once, then later taps in that same burst are ignored.
 */
internal class BubbleTapSequence(
    private val gapMs: Long = BubbleGesturePolicy.MULTI_TAP_GAP_MS,
    private val suppressionMs: Long = BubbleGesturePolicy.ACTIVE_TAP_SUPPRESSION_MS,
) {
    private var pendingCount = 0
    private var deadlineMs = 0L
    private var suppressUntilMs = 0L

    fun onTap(
        nowMs: Long,
        state: DictState,
        tripleTapAction: BubbleGestureAction,
    ): BubbleGesturePolicy.Decision {
        if (nowMs < suppressUntilMs) return BubbleGesturePolicy.Decision.NONE
        when (state) {
            DictState.RECORDING -> {
                clearPending()
                suppressUntilMs = nowMs + suppressionMs
                return BubbleGesturePolicy.Decision.STOP
            }
            DictState.PREPARING -> {
                clearPending()
                suppressUntilMs = nowMs + suppressionMs
                return BubbleGesturePolicy.Decision.CANCEL
            }
            DictState.TRANSCRIBING, DictState.DISCARDING -> {
                clearPending()
                return BubbleGesturePolicy.Decision.NONE
            }
            DictState.IDLE -> Unit
        }

        if (pendingCount > 0 && nowMs > deadlineMs) clearPending()
        pendingCount += 1
        deadlineMs = nowMs + gapMs
        if (pendingCount >= 3) {
            clearPending()
            return BubbleGesturePolicy.actionDecision(tripleTapAction)
        }
        return BubbleGesturePolicy.Decision.PENDING
    }

    fun onTimeout(nowMs: Long, doubleTapAction: BubbleGestureAction): BubbleGesturePolicy.Decision {
        if (pendingCount == 0 || nowMs < deadlineMs) return BubbleGesturePolicy.Decision.NONE
        val count = pendingCount
        clearPending()
        return when (count) {
            1 -> BubbleGesturePolicy.Decision.START
            2 -> BubbleGesturePolicy.actionDecision(doubleTapAction)
            else -> BubbleGesturePolicy.Decision.NONE
        }
    }

    fun cancelPending() = clearPending()

    fun pendingDeadlineMs(): Long? = if (pendingCount == 0) null else deadlineMs

    private fun clearPending() {
        pendingCount = 0
        deadlineMs = 0L
    }
}
