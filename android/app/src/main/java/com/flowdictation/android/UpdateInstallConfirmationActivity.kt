package com.flowdictation.android

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Toast

/** Opens Android's installer confirmation after the user taps the update notification. */
class UpdateInstallConfirmationActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        UpdateInstallActivity.clearPendingConfirmation(this)
        val confirmation = if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(UpdateInstallActivity.EXTRA_CONFIRMATION_INTENT, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(UpdateInstallActivity.EXTRA_CONFIRMATION_INTENT)
        }
        if (confirmation == null) {
            Toast.makeText(this, "Android's install prompt is no longer available. Check for updates again.", Toast.LENGTH_LONG).show()
        } else {
            runCatching { startActivity(confirmation) }
                .onFailure {
                    Toast.makeText(this, "Android could not open the install prompt.", Toast.LENGTH_LONG).show()
                }
        }
        finish()
    }
}
