package com.flowdictation.android

/** Sizing rules for the visible bubble and its independent accessible target. */
internal object BubbleSizePolicy {
    const val MIN_DP = 32
    const val MAX_DP = 160
    const val RESIZE_CAPTURE_DP = 160
    const val DEFAULT_DP = 64
    const val MIN_TOUCH_TARGET_DP = 48

    fun clamp(sizeDp: Int): Int = sizeDp.coerceIn(MIN_DP, MAX_DP)

    fun touchTargetDp(sizeDp: Int): Int = maxOf(MIN_TOUCH_TARGET_DP, clamp(sizeDp))

    fun resizeCaptureTargetDp(sizeDp: Int): Int = maxOf(RESIZE_CAPTURE_DP, clamp(sizeDp))

    /** Shift the overlay origin so expanding its transparent target keeps its center fixed. */
    fun centerPreservingOffsetDp(oldTargetDp: Int, newTargetDp: Int): Int =
        (oldTargetDp - newTargetDp) / 2

    /** Place a wrap-content overlay around the mic's tracked screen-space center. */
    fun originForCenter(centerX: Int, contentWidth: Int, screenWidth: Int, sideMargin: Int): Int =
        (centerX - contentWidth / 2).coerceIn(
            sideMargin,
            (screenWidth - contentWidth - sideMargin).coerceAtLeast(sideMargin),
        )

    /** Return the actual center after horizontal screen-edge clamping. */
    fun centerAfterClamp(originX: Int, contentWidth: Int): Int = originX + contentWidth / 2

    /** Keep all measured transient content above the keyboard and screen edge. */
    fun topForContent(topY: Int, contentHeight: Int, bottomBound: Int, topMargin: Int, bottomMargin: Int): Int =
        topY.coerceIn(topMargin, (bottomBound - contentHeight - bottomMargin).coerceAtLeast(topMargin))

    /** Dragging upward grows and dragging downward shrinks; caller supplies dp. */
    fun fromDrag(startSizeDp: Int, verticalDeltaDp: Int): Int =
        clamp(startSizeDp + verticalDeltaDp)

    /** Pinch-out grows and pinch-in shrinks; caller supplies the distance change in dp. */
    fun fromPinch(startSizeDp: Int, distanceDeltaDp: Int): Int =
        clamp(startSizeDp + distanceDeltaDp)
}
