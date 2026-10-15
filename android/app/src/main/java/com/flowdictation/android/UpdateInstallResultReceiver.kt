package com.flowdictation.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.widget.Toast

/** Receives PackageInstaller outcomes, including Android's confirmation prompt when required. */
class UpdateInstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirmation = if (Build.VERSION.SDK_INT >= 33) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(Intent.EXTRA_INTENT)
                }
                if (confirmation != null) {
                    UpdateInstallActivity.handlePendingUserAction(context, confirmation)
                } else {
                    val message = "Android could not open the installation prompt."
                    UpdateInstallActivity.handleInstallFinished(context, message)
                    show(context, message)
                }
            }
            PackageInstaller.STATUS_SUCCESS -> {
                UpdateInstallActivity.handleInstallFinished(context, "Flow update installed.")
                show(context, "Flow update installed.")
            }
            else -> {
                val detail = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
                val message = when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
                    PackageInstaller.STATUS_FAILURE_BLOCKED -> "Android blocked this update. Check the install permission and try again."
                    PackageInstaller.STATUS_FAILURE_CONFLICT -> "Android could not replace this app. The update may use a different signing key."
                    PackageInstaller.STATUS_FAILURE_INCOMPATIBLE -> "This update is not compatible with this phone."
                    PackageInstaller.STATUS_FAILURE_INVALID -> "Android could not read this update file."
                    PackageInstaller.STATUS_FAILURE_STORAGE -> "There is not enough phone storage to install the update."
                    else -> detail?.takeIf { it.isNotBlank() } ?: "The update was not installed."
                }
                UpdateInstallActivity.handleInstallFinished(context, message)
                show(context, message)
            }
        }
    }

    private fun show(context: Context, message: String) {
        Toast.makeText(context.applicationContext, message, Toast.LENGTH_LONG).show()
    }
}
