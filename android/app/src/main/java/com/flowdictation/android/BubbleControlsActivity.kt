package com.flowdictation.android

import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.button.MaterialButton
import com.google.android.material.slider.Slider

/** Dedicated settings page for the floating button's size and gestures. */
class BubbleControlsActivity : FlowActivity() {
    private lateinit var controls: BubbleControlsPrefs
    private lateinit var sizeLabel: TextView
    private lateinit var longPressButton: Button
    private lateinit var doubleTapButton: Button
    private lateinit var tripleTapButton: Button

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        controls = BubbleControlsPrefs(this)
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(16), dp(24), dp(24))
        }
        val scroll = ScrollView(this).apply { addView(content) }
        setContentView(scroll)
        applyInsets()

        content.addView(TextView(this).apply {
            text = "Floating button"
            textSize = 28f
            setTextColor(getColor(R.color.flow_text))
        })
        content.addView(TextView(this).apply {
            text = "Tap once to start or stop. Double and triple taps work when you’re not recording. By default, triple-tap, then pinch to resize."
            textSize = 16f
            setTextColor(getColor(R.color.flow_muted))
            setPadding(0, dp(8), 0, dp(16))
        })

        sizeLabel = TextView(this).apply { textSize = 16f; setTextColor(getColor(R.color.flow_text)) }
        content.addView(sizeLabel)
        content.addView(Slider(this).apply {
            id = R.id.bubble_size_slider
            valueFrom = BubbleSizePolicy.MIN_DP.toFloat()
            valueTo = BubbleSizePolicy.MAX_DP.toFloat()
            stepSize = 1f
            value = controls.bubbleSizeDp.toFloat()
            contentDescription = "Floating button visible size"
            addOnChangeListener { _, value, fromUser ->
                if (fromUser) {
                    controls.bubbleSizeDp = value.toInt()
                    updateSizeLabel()
                    refreshBubble()
                }
            }
        })
        content.addView(TextView(this).apply {
            text = "The button can be smaller while its invisible touch area stays easy to tap."
            textSize = 14f
            setTextColor(getColor(R.color.flow_muted))
            setPadding(0, 0, 0, dp(16))
        })

        longPressButton = addActionRow(content, "Long press") {
            chooseAction("Long press action", BubbleGestureAction.values().toList(), controls.longPressAction) {
                controls.longPressAction = it
                updateActionLabels()
            }
        }
        doubleTapButton = addActionRow(content, "Double tap") {
            chooseAction("Double tap action", tapActions(), controls.doubleTapAction) {
                controls.doubleTapAction = it
                updateActionLabels()
            }
        }
        tripleTapButton = addActionRow(content, "Triple tap") {
            chooseAction("Triple tap action", tapActions(), controls.tripleTapAction) {
                controls.tripleTapAction = it
                updateActionLabels()
            }
        }
        content.addView(TextView(this).apply {
            text = "Hold to talk starts while idle and finishes when released. While listening, holding pauses and releasing resumes."
            textSize = 14f
            setTextColor(getColor(R.color.flow_muted))
            setPadding(0, dp(12), 0, dp(16))
        })
        content.addView(MaterialButton(this).apply {
            text = "Done"
            minHeight = dp(48)
            setOnClickListener { finish() }
        })
        updateSizeLabel()
        updateActionLabels()
    }

    private fun addActionRow(parent: LinearLayout, title: String, open: () -> Unit): Button {
        val density = resources.displayMetrics.density
        val header = TextView(this).apply {
            text = title
            textSize = 18f
            setTextColor(getColor(R.color.flow_text))
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, (12 * density).toInt(), 0, (4 * density).toInt())
        }
        parent.addView(header)
        return MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            minHeight = (56 * density).toInt()
            setOnClickListener { open() }
        }.also { parent.addView(it) }
    }

    private fun tapActions() = BubbleGestureAction.values().filter { BubbleGesturePolicy.isAllowedIdleTapAction(it) }

    private fun chooseAction(
        title: String,
        actions: List<BubbleGestureAction>,
        selected: BubbleGestureAction,
        onChoose: (BubbleGestureAction) -> Unit,
    ) {
        MaterialAlertDialogBuilder(this)
            .setTitle(title)
            .setSingleChoiceItems(actions.map(::actionLabel).toTypedArray(), actions.indexOf(selected)) { dialog, index ->
                onChoose(actions[index])
                dialog.dismiss()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun actionLabel(action: BubbleGestureAction) = when (action) {
        BubbleGestureAction.HOLD_TO_TALK -> "Hold to talk / pause while listening"
        BubbleGestureAction.RESIZE -> "Resize while idle"
        BubbleGestureAction.PAUSE_RESUME -> "Pause or resume while listening"
        BubbleGestureAction.DISCARD -> "Discard recording while listening"
        BubbleGestureAction.OPEN_FLOW -> "Open Flow"
        BubbleGestureAction.OPEN_SETTINGS -> "Open settings"
        BubbleGestureAction.NONE -> "Do nothing"
    }

    private fun updateSizeLabel() {
        sizeLabel.text = "Button size: ${controls.bubbleSizeDp}"
    }

    private fun updateActionLabels() {
        longPressButton.text = actionLabel(controls.longPressAction)
        doubleTapButton.text = actionLabel(controls.doubleTapAction)
        tripleTapButton.text = actionLabel(controls.tripleTapAction)
    }

    private fun refreshBubble() {
        if (Prefs(this).bubbleEnabled) {
            runCatching { startService(DictationService.refreshAutoBubbleIntent(this)) }
        }
    }
}
