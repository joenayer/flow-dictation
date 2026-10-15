package com.flowdictation.android

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AutoBubblePolicyTest {
    @Test fun manualBubbleDoesNotRequireEditableTarget() {
        assertTrue(AutoBubblePolicy.shouldShow(true, false, false, false))
    }
    @Test fun automaticIdleBubbleRequiresEditableTarget() {
        assertFalse(AutoBubblePolicy.shouldShow(true, true, false, false))
        assertTrue(AutoBubblePolicy.shouldShow(true, true, true, false))
    }
    @Test fun keyboardOrFocusLossCannotHideActiveRecordingControls() {
        assertTrue(AutoBubblePolicy.shouldShow(true, true, false, true))
    }
    @Test fun explicitMasterDisableHidesBubble() {
        assertFalse(AutoBubblePolicy.shouldShow(false, true, true, true))
        assertFalse(AutoBubblePolicy.shouldShow(false, false, true, true))
    }
}
