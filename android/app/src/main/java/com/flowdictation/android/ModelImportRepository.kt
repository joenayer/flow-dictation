package com.flowdictation.android

import android.content.Context
import java.io.File

/** Imported models stay in app-private storage; bundled assets always remain available. */
class ModelImportRepository(private val context: Context) {
    val root: File get() = File(context.filesDir, "speech-models")
    fun directory(id: String): File {
        require(ModelCatalog.spec(id) != null)
        return File(root, id)
    }
    fun isBundled(spec: ModelSpec): Boolean = runCatching {
        ModelImportFiles.resolve(spec, context.assets.list(ModelCatalog.assetDir(spec.id))?.toList().orEmpty()) { it } != null
    }.getOrDefault(false)
    fun isAvailable(spec: ModelSpec): Boolean = isBundled(spec) || runCatching {
        val directory = directory(spec.id)
        ModelImportFiles.resolve(spec, directory.list()?.toList().orEmpty()) { File(directory, it).path } != null
    }.getOrDefault(false)
}
