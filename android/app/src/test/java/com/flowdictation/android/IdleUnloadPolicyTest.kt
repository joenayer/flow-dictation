package com.flowdictation.android

import org.junit.Assert.*
import org.junit.Test

class IdleUnloadPolicyTest {
    @Test fun defaultDeadlineAndRepeatedRefresh() {
        val policy = IdleUnloadPolicy()
        assertFalse(policy.shouldUnload(200_000, 2, false))
        policy.beginIdle(1000)
        policy.beginIdle(80_000)
        assertFalse(policy.shouldUnload(120_999, 2, false))
        assertTrue(policy.shouldUnload(121_000, 2, false))
    }
    @Test fun recordingAndNewWorkProtectRecognizer() {
        val policy = IdleUnloadPolicy()
        policy.beginIdle(0)
        assertFalse(policy.shouldUnload(120_000, 2, true))
        policy.beginWork()
        assertFalse(policy.shouldUnload(300_000, 2, false))
        policy.beginIdle(300_000)
        assertFalse(policy.shouldUnload(419_999, 2, false))
        assertTrue(policy.shouldUnload(420_000, 2, false))
    }
    @Test fun everySettingAndChangedDeadline() {
        IdleUnloadPolicy.MINUTES.forEach { minutes ->
            val policy = IdleUnloadPolicy().apply { beginIdle(50) }
            assertFalse(policy.shouldUnload(minutes * 60_000L + 49, minutes, false))
            assertTrue(policy.shouldUnload(minutes * 60_000L + 50, minutes, false))
        }
        val policy = IdleUnloadPolicy().apply { beginIdle(0) }
        assertEquals(480_000L, policy.remainingMs(120_000, 10))
        assertTrue(policy.shouldUnload(120_000, 1, false))
        assertEquals(120_000L, policy.remainingMs(0, 99))
        assertEquals(120_000L, policy.remainingMs(-10, 2))
    }
}
