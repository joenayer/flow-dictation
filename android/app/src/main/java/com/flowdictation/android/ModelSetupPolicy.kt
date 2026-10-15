package com.flowdictation.android

/** First-run setup is based on installed usable models, with an explicit pending state for restart recovery. */
object ModelSetupPolicy {
    fun showSetup(availableModelIds: Set<String>, setupPending: Boolean): Boolean =
        availableModelIds.isEmpty() || setupPending

    /** Keep a user's working model when it remains available; otherwise choose the completed recommendation. */
    fun selectedAfterSetup(currentModelId: String, availableModelIds: Set<String>, recommendedModelId: String): String =
        currentModelId.takeIf { it in availableModelIds } ?: recommendedModelId
}
