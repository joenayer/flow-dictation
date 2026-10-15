package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BubbleGesturePolicyTest {
    @Test
    fun loneIdleTapStartsAfterTheMultiTapWindow() {
        val taps = BubbleTapSequence()
        assertEquals(BubbleGesturePolicy.Decision.PENDING,
            taps.onTap(0, DictState.IDLE, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTimeout(299, BubbleGestureAction.NONE))
        assertEquals(BubbleGesturePolicy.Decision.START,
            taps.onTimeout(300, BubbleGestureAction.NONE))
        assertNull(taps.pendingDeadlineMs())
    }

    @Test
    fun tripleTapRunsResizeAndNeverStartsDictation() {
        val taps = BubbleTapSequence()
        assertEquals(BubbleGesturePolicy.Decision.PENDING,
            taps.onTap(0, DictState.IDLE, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.PENDING,
            taps.onTap(100, DictState.IDLE, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.RESIZE,
            taps.onTap(200, DictState.IDLE, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTimeout(500, BubbleGestureAction.NONE))
    }

    @Test
    fun doubleTapActionWaitsToSeeWhetherTheSequenceBecomesTriple() {
        val taps = BubbleTapSequence()
        taps.onTap(0, DictState.IDLE, BubbleGestureAction.RESIZE)
        assertEquals(BubbleGesturePolicy.Decision.PENDING,
            taps.onTap(100, DictState.IDLE, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTimeout(399, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.RESIZE,
            taps.onTimeout(400, BubbleGestureAction.RESIZE))
    }

    @Test
    fun listeningStopIsImmediateAndTheRestOfThatBurstIsSuppressed() {
        val taps = BubbleTapSequence()
        assertEquals(BubbleGesturePolicy.Decision.STOP,
            taps.onTap(100, DictState.RECORDING, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTap(200, DictState.IDLE, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTap(500, DictState.IDLE, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.PENDING,
            taps.onTap(601, DictState.IDLE, BubbleGestureAction.RESIZE))
    }

    @Test
    fun preparationTapCancelsImmediatelyAndSuppressesTheBurst() {
        val taps = BubbleTapSequence()
        assertEquals(BubbleGesturePolicy.Decision.CANCEL,
            taps.onTap(100, DictState.PREPARING, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTap(200, DictState.IDLE, BubbleGestureAction.RESIZE))
    }

    @Test
    fun processingTapDoesNotQueueAnAccidentalStart() {
        val taps = BubbleTapSequence()
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTap(100, DictState.TRANSCRIBING, BubbleGestureAction.RESIZE))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTimeout(500, BubbleGestureAction.NONE))
    }

    @Test
    fun cancelClearsAnUnresolvedIdleTap() {
        val taps = BubbleTapSequence()
        taps.onTap(100, DictState.IDLE, BubbleGestureAction.RESIZE)
        taps.cancelPending()
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            taps.onTimeout(500, BubbleGestureAction.RESIZE))
    }

    @Test
    fun holdBehaviorStillSupportsPauseAndReleaseResume() {
        assertEquals(BubbleGesturePolicy.Decision.PAUSE,
            BubbleGesturePolicy.onHold(recordingAtDown = true, idleAtDown = false, dragged = false))
        assertEquals(BubbleGesturePolicy.Decision.RESUME,
            BubbleGesturePolicy.onHoldRelease(pauseFired = true, holdFired = false, dragged = true))
        assertEquals(BubbleGesturePolicy.Decision.CANCEL,
            BubbleGesturePolicy.onCancel(holdFired = true))
    }

    @Test
    fun configuredPauseResumeLongHoldTogglesAndReleaseOrCancelDoesNotUndoIt() {
        assertEquals(BubbleGesturePolicy.Decision.PAUSE,
            BubbleGesturePolicy.onPauseResumeToggle(currentlyPaused = false))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            BubbleGesturePolicy.onHoldRelease(pauseFired = false, holdFired = false, dragged = false))
        assertEquals(BubbleGesturePolicy.Decision.NONE,
            BubbleGesturePolicy.onCancel(holdFired = false, pauseFired = false))
        assertEquals(BubbleGesturePolicy.Decision.RESUME,
            BubbleGesturePolicy.onPauseResumeToggle(currentlyPaused = true))
    }

    @Test
    fun onlyResizeModeOwnsTwoFingerPinches() {
        assertEquals(false, BubbleGesturePolicy.ownsPinch(resizeMode = false, pointerCount = 2))
        assertEquals(false, BubbleGesturePolicy.ownsPinch(resizeMode = true, pointerCount = 1))
        assertEquals(true, BubbleGesturePolicy.ownsPinch(resizeMode = true, pointerCount = 2))
    }

    @Test
    fun aPlainTapExitsResizeModeWithoutRecording() {
        assertEquals(true,
            BubbleGesturePolicy.exitsResizeModeOnRelease(true, dragged = false, pinched = false, longPressed = false))
        assertEquals(false,
            BubbleGesturePolicy.exitsResizeModeOnRelease(true, dragged = false, pinched = true, longPressed = false))
        assertEquals(false,
            BubbleGesturePolicy.exitsResizeModeOnRelease(true, dragged = false, pinched = false, longPressed = true))
        assertEquals(false,
            BubbleGesturePolicy.exitsResizeModeOnRelease(false, dragged = false, pinched = false, longPressed = false))
    }

    @Test
    fun idleDoubleAndTripleTapChoicesCannotStartOrStopDictation() {
        assertEquals(true, BubbleGesturePolicy.isAllowedIdleTapAction(BubbleGestureAction.RESIZE))
        assertEquals(true, BubbleGesturePolicy.isAllowedIdleTapAction(BubbleGestureAction.OPEN_FLOW))
        assertEquals(true, BubbleGesturePolicy.isAllowedIdleTapAction(BubbleGestureAction.OPEN_SETTINGS))
        assertEquals(true, BubbleGesturePolicy.isAllowedIdleTapAction(BubbleGestureAction.NONE))
        assertEquals(false, BubbleGesturePolicy.isAllowedIdleTapAction(BubbleGestureAction.PAUSE_RESUME))
        assertEquals(false, BubbleGesturePolicy.isAllowedIdleTapAction(BubbleGestureAction.DISCARD))
        assertEquals(false, BubbleGesturePolicy.isAllowedIdleTapAction(BubbleGestureAction.HOLD_TO_TALK))
    }

    @Test
    fun tapActionsCanOpenFlowOrSettingsOnlyAfterTheIdleSequenceCompletes() {
        val taps = BubbleTapSequence()
        taps.onTap(0, DictState.IDLE, BubbleGestureAction.RESIZE)
        taps.onTap(100, DictState.IDLE, BubbleGestureAction.RESIZE)
        assertEquals(BubbleGesturePolicy.Decision.OPEN_FLOW,
            taps.onTimeout(400, BubbleGestureAction.OPEN_FLOW))

        taps.onTap(500, DictState.IDLE, BubbleGestureAction.RESIZE)
        taps.onTap(600, DictState.IDLE, BubbleGestureAction.RESIZE)
        assertEquals(BubbleGesturePolicy.Decision.OPEN_SETTINGS,
            taps.onTimeout(900, BubbleGestureAction.OPEN_SETTINGS))
    }
}
