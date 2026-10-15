package com.flowdictation.android

import android.content.Context
import android.os.Looper

/** Outcome of one automatic insertion attempt, with a clipboard fallback when needed. */
data class DeliveryResult(
    val result: AutoInputResult,
    val inserted: Boolean,
    val copied: Boolean,
    val message: String,
)

/**
 * Delivers a recognized transcript to its captured field once. If insertion is
 * not confirmed, the transcript is copied for the user to paste manually.
 */
object AutoInputDelivery {
    fun deliver(context: Context, targetId: Long, text: String): DeliveryResult =
        AutoInputDeliveryPolicy.deliver(text,
            insert = {
                check(Looper.myLooper() == Looper.getMainLooper()) {
                    "Automatic insertion must be requested on the main thread"
                }
                AutoInputBridge.insertTranscript(targetId, text)
            },
            copy = { value -> TextOutput.copy(context, value) })
}

/** Injectable orchestration core for policy tests; it never retries insertion. */
internal object AutoInputDeliveryPolicy {
    fun deliver(
        text: String,
        insert: () -> AutoInputResult,
        copy: (String) -> Boolean,
    ): DeliveryResult {
        val result = try { insert() } catch (_: Exception) { AutoInputResult.UNSUPPORTED }
        val inserted = result == AutoInputResult.INSERTED ||
            result == AutoInputResult.INSERTED_CURSOR_UNCONFIRMED
        if (inserted) return DeliveryResult(result, inserted = true, copied = false, message = result.message)

        val copied = if (text.isNotEmpty()) try { copy(text) } catch (_: Exception) { false } else false
        val message = when {
            result == AutoInputResult.INSERTION_UNCONFIRMED && copied ->
                "Copied to clipboard. Check the field before pasting; typing was not confirmed."
            result == AutoInputResult.INSERTION_UNCONFIRMED ->
                "Check the field before pasting. Your text is available in Flow."
            copied -> "Copied to clipboard. Paste into your text field."
            text.isEmpty() -> "There was no text to copy."
            else -> "Typing failed. Your text is available in Flow."
        }
        return DeliveryResult(result, inserted = false, copied = copied, message = message)
    }
}
