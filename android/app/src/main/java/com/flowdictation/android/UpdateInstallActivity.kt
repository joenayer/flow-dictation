package com.flowdictation.android

import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.lang.ref.WeakReference

/** Handles Android's per-app unknown-sources permission and starts a PackageInstaller session. */
class UpdateInstallActivity : Activity() {
    private lateinit var status: TextView
    private var permissionRequestLaunched = false
    private var checkingApk = false
    private var installStarted = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        status = TextView(this).apply {
            textSize = 18f
            gravity = Gravity.CENTER
            setPadding(32, 32, 32, 32)
        }
        setContentView(status)
        installStarted = savedInstanceState?.getBoolean(STATE_INSTALL_STARTED) ?: false
        if (installStarted) status.text = "Waiting for Android's install prompt…"
        else beginInstall()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean(STATE_INSTALL_STARTED, installStarted)
        super.onSaveInstanceState(outState)
    }

    override fun onResume() {
        super.onResume()
        foregroundActivity = WeakReference(this)
        val pending = pendingConfirmation ?: readPendingConfirmation(this)
        if (pending != null) launchConfirmation(pending)
    }

    override fun onPause() {
        if (foregroundActivity?.get() === this) foregroundActivity = null
        super.onPause()
    }

    private fun beginInstall() {
        val apk = updateFile() ?: return fail("The update file is no longer available. Check for updates again.")
        val digest = intent.getStringExtra(EXTRA_SHA256)
            ?: return fail("The update file could not be verified. Check for updates again.")
        if (checkingApk) return
        checkingApk = true
        status.text = "Checking the update file…"
        Thread({
            val error = runCatching { UpdateApkVerifier.verify(this, apk, expectedUpdate(), digest) }.exceptionOrNull()
            runOnUiThread {
                checkingApk = false
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (error != null) {
                    apk.delete()
                    fail(error.message ?: "The update could not be verified.")
                } else {
                    requestPermissionOrInstall(apk)
                }
            }
        }, "flow-update-verify").apply { isDaemon = true }.start()
    }

    private fun requestPermissionOrInstall(apk: File) {
        if (android.os.Build.VERSION.SDK_INT >= 26 && !packageManager.canRequestPackageInstalls()) {
            if (permissionRequestLaunched) return
            permissionRequestLaunched = true
            status.text = "Allow Flow to install the update, then return here."
            try {
                startActivityForResult(
                    Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")),
                    REQUEST_UNKNOWN_APPS,
                )
            } catch (_: Exception) {
                fail("Android could not open the install permission setting.")
            }
            return
        }

        if (!claimInstallSession()) {
            finish()
            return
        }
        status.text = "Preparing Android's install prompt…"
        installStarted = true
        Thread({
            val error = runCatching { PackageInstallerUpdate.install(this, apk) }.exceptionOrNull()
            if (error != null) releaseInstallSession()
            apk.delete()
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (error == null) status.text = "Waiting for Android's install prompt…"
                else {
                    installStarted = false
                    fail(error.message ?: "Android could not start the update installation.")
                }
            }
        }, "flow-package-installer").apply { isDaemon = true }.start()
    }

    @Deprecated("Android returns from the per-app install permission screen through this callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_UNKNOWN_APPS) return
        if (android.os.Build.VERSION.SDK_INT < 26 || packageManager.canRequestPackageInstalls()) {
            permissionRequestLaunched = false
            beginInstall()
        } else {
            fail("Allow Flow to install apps before continuing with the update.")
        }
    }

    private fun updateFile(): File? {
        val name = intent.getStringExtra(EXTRA_APK_PATH) ?: return null
        if (!name.matches(Regex("flow-update-[a-f0-9-]+\\.apk"))) return null
        val directory = File(filesDir, UPDATE_DIRECTORY).canonicalFile
        val file = File(directory, name).canonicalFile
        if (file.parentFile != directory) return null
        return file.takeIf { it.isFile }
    }

    private fun expectedUpdate(): AppUpdater.UpdateInfo {
        // The release version is carried separately so a replaced file cannot claim an arbitrary release.
        val versionName = intent.getStringExtra(EXTRA_VERSION_NAME)
            ?: error("The update version could not be checked.")
        return AppUpdater.UpdateInfo("", versionName, "", "")
    }

    private fun launchConfirmation(intent: Intent) {
        try {
            startActivity(intent)
            clearPendingConfirmation(this)
        } catch (_: Exception) {
            pendingConfirmation = intent
            persistPendingConfirmation(this, intent)
            showPendingConfirmationNotification(this, intent)
        }
    }

    private fun showInstallOutcome(message: String) {
        status.text = message
        status.postDelayed({ if (!isFinishing) finish() }, 3500)
    }

    private fun fail(message: String) {
        updateFile()?.delete()
        if (!::status.isInitialized) {
            Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        } else {
            status.text = message
            status.setOnClickListener { finish() }
            status.postDelayed({ if (!isFinishing) finish() }, 5000)
        }
    }

    companion object {
        internal const val EXTRA_APK_PATH = "update_apk_path"
        internal const val EXTRA_SHA256 = "update_sha256"
        internal const val EXTRA_VERSION_NAME = "update_version_name"
        internal const val EXTRA_CONFIRMATION_INTENT = "update_confirmation_intent"
        private const val STATE_INSTALL_STARTED = "update_install_started"
        private const val UPDATE_DIRECTORY = "updates"
        private const val REQUEST_UNKNOWN_APPS = 8103
        private const val NOTIFICATION_CHANNEL = "flow_update_install"
        private const val NOTIFICATION_ID = 8104
        private const val NOTIFICATION_REQUEST = 8105

        @Volatile private var foregroundActivity: WeakReference<UpdateInstallActivity>? = null
        @Volatile private var pendingConfirmation: Intent? = null
        private var installSessionClaimed = false

        @Synchronized private fun claimInstallSession(): Boolean {
            if (installSessionClaimed) return false
            installSessionClaimed = true
            return true
        }

        @Synchronized private fun releaseInstallSession() {
            installSessionClaimed = false
        }

        internal fun handlePendingUserAction(context: android.content.Context, confirmation: Intent) {
            pendingConfirmation = Intent(confirmation)
            persistPendingConfirmation(context, confirmation)
            val activity = foregroundActivity?.get()
            if (activity != null && !activity.isFinishing) {
                activity.runOnUiThread { activity.launchConfirmation(confirmation) }
            } else {
                showPendingConfirmationNotification(context, confirmation)
            }
        }

        internal fun clearPendingConfirmation() {
            pendingConfirmation = null
        }

        internal fun clearPendingConfirmation(context: android.content.Context) {
            clearPendingConfirmation()
            context.getSharedPreferences(PENDING_PREFS, android.content.Context.MODE_PRIVATE)
                .edit().remove(PENDING_CONFIRMATION_KEY).apply()
            context.getSystemService(NotificationManager::class.java)?.cancel(NOTIFICATION_ID)
        }

        internal fun handleInstallFinished(context: android.content.Context, message: String) {
            releaseInstallSession()
            clearPendingConfirmation(context)
            val activity = foregroundActivity?.get()
            if (activity != null && !activity.isFinishing) {
                activity.runOnUiThread { activity.showInstallOutcome(message) }
            }
            context.getSystemService(NotificationManager::class.java)?.cancel(NOTIFICATION_ID)
        }

        internal fun notifyUpdateReady(context: android.content.Context, launchIntent: Intent): Boolean =
            showInstallNotification(
                context,
                launchIntent,
                "Flow update downloaded",
                "Tap to review and install the update.",
            )

        private fun showInstallNotification(
            context: android.content.Context,
            actionIntent: Intent,
            title: String = "Flow update is ready",
            text: String = "Tap to review and install the update.",
        ): Boolean {
            val manager = context.getSystemService(NotificationManager::class.java) ?: return false
            if (Build.VERSION.SDK_INT >= 33 &&
                context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                val message = if (actionIntent.component?.className == UpdateInstallActivity::class.java.name) {
                    "Flow could not show a notification. Return to Flow and check for updates again."
                } else {
                    "Return to Flow to finish the installation."
                }
                Toast.makeText(context, message, Toast.LENGTH_LONG).show()
                return false
            }
            if (Build.VERSION.SDK_INT >= 26) {
                manager.createNotificationChannel(
                    NotificationChannel(NOTIFICATION_CHANNEL, "Flow updates", NotificationManager.IMPORTANCE_DEFAULT),
                )
            }
            if (!manager.areNotificationsEnabled() || (Build.VERSION.SDK_INT >= 26 &&
                    manager.getNotificationChannel(NOTIFICATION_CHANNEL)?.importance == NotificationManager.IMPORTANCE_NONE)
            ) {
                val message = if (actionIntent.component?.className == UpdateInstallActivity::class.java.name) {
                    "Flow could not show a notification. Return to Flow and check for updates again."
                } else {
                    "Return to Flow to finish the installation."
                }
                Toast.makeText(context, message, Toast.LENGTH_LONG).show()
                return false
            }
            val immutable = if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0
            val pending = PendingIntent.getActivity(
                context,
                NOTIFICATION_REQUEST,
                actionIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or immutable,
            )
            val notification = android.app.Notification.Builder(context, NOTIFICATION_CHANNEL)
                .setSmallIcon(com.flowdictation.android.R.drawable.ic_flow)
                .setContentTitle(title)
                .setContentText(text)
                .setContentIntent(pending)
                .setAutoCancel(true)
                .build()
            manager.notify(NOTIFICATION_ID, notification)
            return true
        }

        private fun showPendingConfirmationNotification(context: android.content.Context, confirmation: Intent) {
            val openConfirmation = Intent(context, UpdateInstallConfirmationActivity::class.java)
                .putExtra(EXTRA_CONFIRMATION_INTENT, confirmation)
            showInstallNotification(context, openConfirmation)
        }

        private fun persistPendingConfirmation(context: android.content.Context, confirmation: Intent) {
            val uri = runCatching { confirmation.toUri(Intent.URI_INTENT_SCHEME) }.getOrNull() ?: return
            context.getSharedPreferences(PENDING_PREFS, android.content.Context.MODE_PRIVATE)
                .edit().putString(PENDING_CONFIRMATION_KEY, uri).apply()
        }

        private fun readPendingConfirmation(context: android.content.Context): Intent? {
            val preferences = context.getSharedPreferences(PENDING_PREFS, android.content.Context.MODE_PRIVATE)
            val uri = preferences.getString(PENDING_CONFIRMATION_KEY, null) ?: return null
            return runCatching { Intent.parseUri(uri, Intent.URI_INTENT_SCHEME) }
                .onFailure { preferences.edit().remove(PENDING_CONFIRMATION_KEY).apply() }
                .getOrNull()
        }

        private const val PENDING_PREFS = "update_install_pending"
        private const val PENDING_CONFIRMATION_KEY = "confirmation_intent"
    }
}

/** Streams an already verified APK into Android's transactional package installer. */
internal object PackageInstallerUpdate {
    fun install(activity: Activity, apk: File) {
        val installer = activity.packageManager.packageInstaller
        val params = android.content.pm.PackageInstaller.SessionParams(
            android.content.pm.PackageInstaller.SessionParams.MODE_FULL_INSTALL,
        ).apply {
            setAppPackageName(activity.packageName)
            setSize(apk.length())
        }
        val sessionId = installer.createSession(params)
        try {
            installer.openSession(sessionId).use { session ->
                apk.inputStream().buffered().use { input ->
                    session.openWrite("base.apk", 0, apk.length()).use { output ->
                        input.copyTo(output, 64 * 1024)
                        session.fsync(output)
                    }
                }
                val status = Intent(activity, UpdateInstallResultReceiver::class.java)
                    .setPackage(activity.packageName)
                val mutableFlag = if (android.os.Build.VERSION.SDK_INT >= 31) android.app.PendingIntent.FLAG_MUTABLE else 0
                val pending = android.app.PendingIntent.getBroadcast(
                    activity,
                    sessionId,
                    status,
                    android.app.PendingIntent.FLAG_UPDATE_CURRENT or mutableFlag,
                )
                session.commit(pending.intentSender)
            }
        } catch (e: Exception) {
            runCatching { installer.abandonSession(sessionId) }
            throw e
        }
    }
}
