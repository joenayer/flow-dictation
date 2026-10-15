package com.flowdictation.android

import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Process-owned model work survives screen recreation; pinned partials survive process death. */
object ModelImportJob {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val listeners = mutableSetOf<() -> Unit>()
    private var cancellation = AtomicBoolean(false)
    @Volatile var isRunning = false
        private set
    @Volatile var progressPercent = -1
        private set
    @Volatile var status = ""
        private set
    @Volatile private var lastProgressUpdateNs = 0L

    fun register(listener: () -> Unit) { listeners.add(listener); listener() }
    fun unregister(listener: () -> Unit) { listeners.remove(listener) }
    private fun update(message: String, running: Boolean, progress: Int = -1) {
        status = message
        isRunning = running
        progressPercent = progress
        listeners.toList().forEach { it() }
    }
    fun cancel() {
        if (isRunning) { cancellation.set(true); update("Cancelling model installation…", true, progressPercent) }
    }
    fun download(context: Context, spec: ModelSpec) = run(context, spec, null)
    fun start(context: Context, uri: Uri) = run(context, null, uri)
    fun downloadRecommended(context: Context) = run(context, ModelCatalog.recommended(), null, includeVad = true)

    fun hasResumableSetup(context: Context): Boolean {
        val repo = ModelImportRepository(context.applicationContext)
        val partial = partialArchive(repo, ModelCatalog.recommended())
        val vad = SileroVadRepository(context.applicationContext)
        val pending = context.getSharedPreferences(SETUP_PREFS, Context.MODE_PRIVATE).getBoolean(SETUP_PENDING, false)
        return pending || partial.length() > 0 ||
            (!vad.isDownloaded() && File(File(context.filesDir, "speech-models"), SileroVadRepository.FILE_NAME + ".partial").length() > 0)
    }

    private fun run(context: Context, requested: ModelSpec?, uri: Uri?, includeVad: Boolean = false) {
        if (isRunning) return
        if (DictationEvents.state != DictState.IDLE) {
            update("Finish or discard the recording before adding a model.", false)
            return
        }
        if (includeVad) appPrefs(context).edit().putBoolean(SETUP_PENDING, true).apply()
        val app = context.applicationContext
        cancellation = AtomicBoolean(false)
        val cancelled = cancellation
        update(if (includeVad) "Preparing recommended speech setup…" else if (requested != null) "Downloading ${requested.displayName}…" else "Reading model archive…", true)
        worker.execute {
            val importTemp = File(app.cacheDir, "model-${UUID.randomUUID()}.tar.bz2")
            var persistentArchive: File? = null
            var installed: ModelSpec? = null
            val outcome = runCatching {
                val repository = ModelImportRepository(app)
                // Recover abandoned staging folders only; resumable downloads stay in private storage.
                repository.root.listFiles()?.filter { it.name.startsWith(".import-") }?.forEach { it.deleteRecursively() }
                val allowed = ModelCatalog.models.filter { !repository.isAvailable(it) }
                val target = requested
                if (target != null && !repository.isAvailable(target)) {
                    check(target in allowed) { "This model is already installed." }
                    repository.root.mkdirs()
                    if (app.cacheDir.usableSpace <= target.installationSpaceMb * 1_000_000L) {
                        check(repository.root.usableSpace > target.installationSpaceMb * 1_000_000L) {
                            "Keep about ${target.installationSpaceMb} MB of phone storage free for this installation."
                        }
                    }
                    persistentArchive = partialArchive(repository, target).also { it.parentFile?.mkdirs() }
                    val digest = ModelImportDownload().download(target, persistentArchive!!, cancelled::get) { bytes, total ->
                        updateProgress(if (total > 0) "Downloading ${target.displayName}" else "Downloading ${target.displayName}", bytes, total, cancelled)
                    }
                    check(!cancelled.get()) { "Cancelled" }
                    installed = installArchive(app, repository, persistentArchive!!, listOf(target), digest, target, cancelled)
                    persistentArchive!!.delete()
                } else if (target == null) {
                    val candidates = ModelCatalog.models.filter { !repository.isAvailable(it) }
                    check(candidates.isNotEmpty()) { "All supported models are already installed." }
                    var lastProgress = 0L
                    val progress: (Long, Long) -> Unit = { bytes, total ->
                        val now = System.nanoTime()
                        if (now - lastProgress > 200_000_000L) {
                            lastProgress = now
                            main.post { if (!cancelled.get()) update(if (total > 0) "Reading model archive · ${bytes * 100 / total}%" else "Reading model archive · ${bytes / (1024 * 1024)} MB", true) }
                        }
                    }
                    val digest = (app.contentResolver.openInputStream(uri!!) ?: error("Could not open that file. Download it again.")).use {
                        ModelImportDownload.copyChecked(it, importTemp, cancelled = cancelled::get, progress = progress)
                    }
                    val verified = candidates.firstOrNull { it.archiveSha256 == digest }
                        ?: error("The model checksum did not match. Use the original supported .tar.bz2 archive.")
                    installed = installArchive(app, repository, importTemp, listOf(verified), digest, null, cancelled)
                }

                if (includeVad) {
                    val vadRepo = SileroVadRepository(app)
                    if (!vadRepo.isDownloaded()) {
                        val partial = File(vadRepo.downloadedFile.parentFile, vadRepo.downloadedFile.name + ".partial")
                        partial.parentFile?.mkdirs()
                        ModelImportDownload().downloadPinned(
                            SileroVadRepository.URL, SileroVadRepository.SHA256, partial,
                            maxBytes = SileroVadRepository.SIZE_BYTES, expectedBytes = SileroVadRepository.SIZE_BYTES,
                            cancelled = cancelled::get,
                        ) { bytes, total -> updateProgress("Downloading Silero pause detection", bytes, total, cancelled) }
                        check(!cancelled.get()) { "Cancelled" }
                        if (vadRepo.downloadedFile.exists()) vadRepo.downloadedFile.delete()
                        check(partial.renameTo(vadRepo.downloadedFile)) { "Could not save Silero pause detection. Reopen setup to retry." }
                    }
                    val prefs = Prefs(app)
                    val availableIds = ModelCatalog.models.filter { repository.isAvailable(it) }.map { it.id }.toSet()
                    prefs.modelId = ModelSetupPolicy.selectedAfterSetup(prefs.modelId, availableIds, ModelCatalog.RECOMMENDED_MODEL_ID)
                    appPrefs(app).edit().putBoolean(SETUP_PENDING, false).apply()
                }
            }
            importTemp.delete()
            main.post {
                val detail = outcome.fold(
                    { if (includeVad) "Recommended speech setup is ready. Parakeet is selected for dictation." else "${installed?.displayName ?: requested?.displayName ?: "Model"} installed. Select it above to use it." },
                    { if (cancelled.get()) "Setup paused. Your download is kept and can resume when you return." else "Could not finish setup: ${it.message ?: "the download could not be read"}. Tap to retry; completed files are kept." },
                )
                update(detail, false)
            }
        }
    }

    private fun installArchive(app: Context, repository: ModelImportRepository, archive: File, candidates: List<ModelSpec>, digest: String,
                               requested: ModelSpec?, cancelled: AtomicBoolean): ModelSpec {
        check(!cancelled.get()) { "Cancelled" }
        val spec = candidates.firstOrNull { it.archiveSha256 == digest }
            ?: error("The model checksum did not match. Use the original supported .tar.bz2 archive.")
        check(requested == null || requested.id == spec.id) { "The archive contains a different model." }
        val unpackStarted = SystemClock.elapsedRealtime()
        Log.i("FlowModelImport", "Unpacking ${spec.id}")
        main.post { if (!cancelled.get()) update("Unpacking the model…", true) }
        var lastProgress = 0L
        val unpackProgress: (Long, Long) -> Unit = { bytes, total ->
            val now = System.nanoTime()
            if (now - lastProgress > 500_000_000L) {
                lastProgress = now
                val label = if (total > 0) "${(bytes * 100 / total).coerceAtMost(100)}%" else "${bytes / (1024 * 1024)} MB"
                main.post { if (!cancelled.get()) update("Unpacking model · $label", true) }
            }
        }
        archive.inputStream().use { input ->
            ModelImportTransaction(ModelImportArchive(cancelled = cancelled::get, progress = unpackProgress)).install(input, repository.root, listOf(spec)) { selected, stage ->
                check(selected.archiveSha256 == digest) { "The model checksum did not match. Use the original supported .tar.bz2 archive." }
                check(!cancelled.get()) { "Cancelled" }
                Log.i("FlowModelImport", "Unpacked ${selected.id} in ${SystemClock.elapsedRealtime() - unpackStarted} ms")
                main.post { if (!cancelled.get()) update("Checking model compatibility…", true) }
                val validationStarted = SystemClock.elapsedRealtime()
                Transcriber.validateImport(selected, stage)
                Log.i("FlowModelImport", "Validated ${selected.id} in ${SystemClock.elapsedRealtime() - validationStarted} ms")
                check(!cancelled.get()) { "Cancelled" }
            }
        }
        return spec
    }

    private fun updateProgress(label: String, bytes: Long, total: Long, cancelled: AtomicBoolean) {
        val percent = if (total > 0) (bytes * 100 / total).toInt().coerceIn(0, 100) else -1
        val now = System.nanoTime()
        if (percent < 100 && now - lastProgressUpdateNs < 250_000_000L) return
        lastProgressUpdateNs = now
        main.post { if (!cancelled.get()) update(if (percent >= 0) "$label · $percent%" else "$label · ${bytes / (1024 * 1024)} MB", true, percent) }
    }

    private fun partialArchive(repository: ModelImportRepository, spec: ModelSpec): File =
        File(File(repository.root, ".downloads"), "${spec.id}.tar.bz2.partial")

    private fun appPrefs(context: Context) = context.getSharedPreferences(SETUP_PREFS, Context.MODE_PRIVATE)

    private const val SETUP_PREFS = "recommended_model_setup"
    private const val SETUP_PENDING = "pending"
}
