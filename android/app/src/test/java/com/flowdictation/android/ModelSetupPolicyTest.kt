package com.flowdictation.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelSetupPolicyTest {
    @Test fun firstLaunchShowsSetupButAnUpgradeWithUsableModelDoesNot() {
        assertTrue(ModelSetupPolicy.showSetup(emptySet(), setupPending = false))
        assertFalse(ModelSetupPolicy.showSetup(setOf("whisper-tiny.en"), setupPending = false))
    }

    @Test fun interruptedRecommendedSetupRemainsVisibleAfterParakeetWasInstalled() {
        assertTrue(ModelSetupPolicy.showSetup(setOf(ModelCatalog.RECOMMENDED_MODEL_ID), setupPending = true))
    }

    @Test fun successfulSetupPreservesAnAlreadyUsableUserChoice() {
        assertEquals("whisper-tiny.en", ModelSetupPolicy.selectedAfterSetup(
            currentModelId = "whisper-tiny.en",
            availableModelIds = setOf("whisper-tiny.en", ModelCatalog.RECOMMENDED_MODEL_ID),
            recommendedModelId = ModelCatalog.RECOMMENDED_MODEL_ID,
        ))
        assertEquals(ModelCatalog.RECOMMENDED_MODEL_ID, ModelSetupPolicy.selectedAfterSetup(
            currentModelId = ModelCatalog.DEFAULT_MODEL_ID,
            availableModelIds = setOf(ModelCatalog.RECOMMENDED_MODEL_ID),
            recommendedModelId = ModelCatalog.RECOMMENDED_MODEL_ID,
        ))
    }
}
