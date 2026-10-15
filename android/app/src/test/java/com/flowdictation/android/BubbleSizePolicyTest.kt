package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Test

class BubbleSizePolicyTest {
    @Test
    fun visibleCircleCanShrinkBelowTheMinimumTouchTarget() {
        assertEquals(32, BubbleSizePolicy.clamp(12))
        assertEquals(32, BubbleSizePolicy.clamp(32))
        assertEquals(96, BubbleSizePolicy.clamp(96))
        assertEquals(160, BubbleSizePolicy.clamp(220))
        assertEquals(48, BubbleSizePolicy.touchTargetDp(32))
        assertEquals(64, BubbleSizePolicy.touchTargetDp(64))
        assertEquals(160, BubbleSizePolicy.resizeCaptureTargetDp(32))
        assertEquals(160, BubbleSizePolicy.resizeCaptureTargetDp(160))
    }

    @Test
    fun pinchOutGrowsAndPinchInShrinksTheVisibleCircle() {
        assertEquals(84, BubbleSizePolicy.fromPinch(64, 20))
        assertEquals(44, BubbleSizePolicy.fromPinch(64, -20))
    }

    @Test
    fun pinchSizingClampsAtBothEnds() {
        assertEquals(BubbleSizePolicy.MAX_DP, BubbleSizePolicy.fromPinch(150, 50))
        assertEquals(BubbleSizePolicy.MIN_DP, BubbleSizePolicy.fromPinch(60, -100))
    }

    @Test
    fun verticalDragSizingAlsoRespectsTheSmallerRange() {
        assertEquals(84, BubbleSizePolicy.fromDrag(64, 20))
        assertEquals(BubbleSizePolicy.MIN_DP, BubbleSizePolicy.fromDrag(64, -100))
    }

    @Test
    fun transparentResizeTargetExpansionKeepsTheCircleCentered() {
        val topBeforeExpand = 300
        val expandOffset = BubbleSizePolicy.centerPreservingOffsetDp(48, 160)
        val topAfterExpand = topBeforeExpand + expandOffset
        assertEquals(-56, expandOffset)
        assertEquals(topBeforeExpand + 24, topAfterExpand + 80)

        val topAfterExit = topAfterExpand + BubbleSizePolicy.centerPreservingOffsetDp(160, 48)
        assertEquals(56, BubbleSizePolicy.centerPreservingOffsetDp(160, 48))
        assertEquals(topBeforeExpand + 24, topAfterExit + 24)
        assertEquals(0, BubbleSizePolicy.centerPreservingOffsetDp(160, 160))
    }

    @Test
    fun measuredWidthChangesKeepMicCenteredUntilScreenEdgeRequiresClamp() {
        val idleOrigin = BubbleSizePolicy.originForCenter(260, 64, 400, 12)
        assertEquals(228, idleOrigin)
        assertEquals(260, BubbleSizePolicy.centerAfterClamp(idleOrigin, 64))

        val activeOrigin = BubbleSizePolicy.originForCenter(260, 200, 400, 12)
        assertEquals(160, activeOrigin)
        assertEquals(260, BubbleSizePolicy.centerAfterClamp(activeOrigin, 200))

        val clampedOrigin = BubbleSizePolicy.originForCenter(390, 200, 400, 12)
        assertEquals(188, clampedOrigin)
        assertEquals(288, BubbleSizePolicy.centerAfterClamp(clampedOrigin, 200))
    }

    @Test
    fun measuredMultilineContentStaysAboveKeyboard() {
        assertEquals(420, BubbleSizePolicy.topForContent(500, 160, 600, 72, 20))
        assertEquals(72, BubbleSizePolicy.topForContent(500, 700, 600, 72, 20))
    }
}
