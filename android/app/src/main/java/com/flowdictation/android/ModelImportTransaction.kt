package com.flowdictation.android

import java.io.File
import java.io.InputStream
import java.util.UUID

/** Atomic publication: failed extraction or model validation cannot replace installed models. */
class ModelImportTransaction(private val archive: ModelImportArchive = ModelImportArchive()) {
    fun install(input: InputStream, root: File, allowed: List<ModelSpec>, validate: (ModelSpec, File) -> Unit): ModelSpec {
        check(root.isDirectory || root.mkdirs()) { "Could not create the speech-model folder." }
        val stage = File(root, ".import-${UUID.randomUUID()}")
        check(stage.mkdir()) { "Could not prepare phone storage for this import." }
        try {
            val spec = archive.extract(input, stage, allowed)
            val destination = File(root, spec.id)
            check(!destination.exists()) { "This model is already installed. Your existing model has been kept." }
            validate(spec, stage)
            check(!destination.exists() && stage.renameTo(destination)) { "Could not install this model. Existing models have been kept." }
            return spec
        } finally {
            if (stage.exists()) stage.deleteRecursively()
        }
    }
}
