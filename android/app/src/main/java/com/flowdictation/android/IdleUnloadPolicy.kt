package com.flowdictation.android

/** Monotonic idle deadline. Repeated bubble refreshes must not restart the clock. */
class IdleUnloadPolicy {
    private var idleSince: Long? = null

    @Synchronized fun beginIdle(nowMs: Long) { if (idleSince == null) idleSince = nowMs }
    @Synchronized fun beginWork() { idleSince = null }
    @Synchronized fun remainingMs(nowMs: Long, minutes: Int): Long? = idleSince?.let {
        val timeout = (minutes.takeIf { it in MINUTES } ?: 2) * 60_000L
        (timeout - (nowMs - it).coerceAtLeast(0)).coerceAtLeast(0)
    }
    @Synchronized fun shouldUnload(nowMs: Long, minutes: Int, busy: Boolean): Boolean =
        !busy && remainingMs(nowMs, minutes) == 0L

    companion object { val MINUTES = listOf(1, 2, 5, 10) }
}
