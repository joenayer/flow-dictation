package com.flowdictation.android

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import kotlin.math.hypot

/**
 * WhisperFlow-style floating bubble: a draggable mic overlay shown over other
 * apps (TYPE_APPLICATION_OVERLAY).
 *
 * - Drag to move; tap starts/stops; press-and-hold follows its selected action.
 * - While recording the bubble turns red and shows a live level meter.
 * - On result it expands into a transcript card with Open Flow / Copy / Close,
 *   then collapses back to the mic bubble.
 *
 * All methods must be called on the main thread. Dictation itself runs in
 * [DictationService]; this class only sends it commands and renders
 * [DictationEvents].
 */
class BubbleManager(private val appContext: Context) : DictationListener {

    private val windowManager =
        appContext.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val main = Handler(Looper.getMainLooper())
    private val inflater = LayoutInflater.from(appContext)
    private val touchSlop = ViewConfiguration.get(appContext).scaledTouchSlop
    private val controls = BubbleControlsPrefs(appContext)

    private var collapsed: View? = null
    private var expanded: View? = null
    private var params: WindowManager.LayoutParams? = null
    private var micButton: ImageButton? = null
    private var touchTarget: FrameLayout? = null
    private var waveform: BubbleWaveformView? = null
    private var statusLabel: TextView? = null
    private var timer: TextView? = null
    private var timerSeconds = -1L
    private val timerTick = object : Runnable {
        override fun run() {
            if (collapsed == null || DictationEvents.state != DictState.RECORDING) return
            val seconds = DictationEvents.recordingDurationMs() / 1000
            if (timerSeconds != seconds) {
                timerSeconds = seconds
                timer?.text = "${seconds / 60}:${(seconds % 60).toString().padStart(2, '0')}"
            }
            main.postDelayed(this, 250L)
        }
    }
    private var paused = false
    private var quiet = false
    var onPause: () -> Unit = {}
    var onResume: () -> Unit = {}

    fun setPaused(value: Boolean) {
        // An already queued pause event can arrive after Stop/Discard.
        paused = value && DictationEvents.state == DictState.RECORDING
        if (paused) setQuiet(false)
        syncVisual(DictationEvents.state)
    }

    fun setQuiet(value: Boolean) {
        quiet = value && !paused && DictationEvents.state == DictState.RECORDING
        waveform?.setQuiet(quiet)
        constrainPlacement()
    }
    private var resizeHint: TextView? = null
    private var resizeMode = false
    private var pinchDistancePx = 0f
    private var pinchStartSizeDp = BubbleSizePolicy.DEFAULT_DP
    private var didPinch = false
    private var collapsedAnchor: Pair<Int, Int>? = null
    /** Horizontal center of the mic in screen coordinates; survives wrap-content width changes. */
    private var bubbleCenterX: Int? = null
    private val savedAnchors = mutableMapOf<Boolean, Pair<Int, Int>>()
    private var automatic = false
    private var keyboardTop: Int? = null
    private var previewSizeDp: Int? = null
    private val tapSequence = BubbleTapSequence()
    private val tapTimeout = Runnable {
        performTapDecision(tapSequence.onTimeout(SystemClock.uptimeMillis(), controls.doubleTapAction))
        schedulePendingTapTimeout()
    }
    private val resizeModeTimeout = Runnable { exitResizeMode() }

    private fun dp(value: Int) = (value * appContext.resources.displayMetrics.density).toInt()

    val isShowing: Boolean
        get() = collapsed != null || expanded != null

    fun canShow(): Boolean = Settings.canDrawOverlays(appContext)

    /**
     * Shows the bubble. Returns false when the overlay permission is missing.
     */
    // InflateParams is intentional: overlay views are parentless by design;
    // WindowManager.LayoutParams (not layout XML) position them.
    @SuppressLint("InflateParams")
    fun show(autoInput: Boolean = false, keyboardTop: Int? = null): Boolean {
        if (automatic != autoInput && isShowing) hide()
        automatic = autoInput
        this.keyboardTop = if (autoInput) keyboardTop else null
        if (!canShow()) return false
        if (collapsed != null || expanded != null) {
            refreshSize()
            return true
        }
        DictationEvents.register(this)
        val p = WindowManager.LayoutParams().apply {
            width = WindowManager.LayoutParams.WRAP_CONTENT
            height = WindowManager.LayoutParams.WRAP_CONTENT
            type = WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
            if (autoInput) {
                // Automatic placement uses the same screen origin as IME
                // bounds. Manual placement retains its existing content-frame
                // origin, including the status-bar offset above its 72 dp y.
                flags = flags or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING
            }
            format = PixelFormat.TRANSLUCENT
            gravity = Gravity.START or Gravity.TOP
            // Right edge, below the app toolbar. The content center is clamped after measurement.
            bubbleCenterX = savedAnchors[automatic]?.first
                ?: (appContext.resources.displayMetrics.widthPixels - dp(36))
            x = (bubbleCenterX!! - dp(BubbleSizePolicy.touchTargetDp(controls.bubbleSizeDp)) / 2)
            y = dp(72)
            savedAnchors[automatic]?.let { (_, savedY) -> y = savedY }
        }
        val view = inflater.inflate(R.layout.bubble_collapsed, null)
        configureCollapsed(view)
        attachGestureHandlers(view)
        try {
            windowManager.addView(view, p)
        } catch (_: RuntimeException) {
            DictationEvents.unregister(this)
            micButton = null
            waveform = null
            touchTarget = null
            return false
        }
        collapsed = view
        params = p
        view.addOnLayoutChangeListener { _, _, _, _, _, oldLeft, oldTop, oldRight, oldBottom ->
            if ((oldRight - oldLeft) != view.width || (oldBottom - oldTop) != view.height) constrainPlacement()
        }
        constrainPlacement()
        syncVisual(DictationEvents.state)
        return true
    }

    /** Wires touch and accessibility click handling to the >=48dp target. */
    // ClickableViewAccessibility: taps DO route through performClick(), but
    // inside onBubbleTouch() after gesture discrimination, which lint's
    // intra-procedural check cannot see.
    @SuppressLint("ClickableViewAccessibility")
    private fun attachGestureHandlers(view: View) {
        view.setOnTouchListener { v, event -> onBubbleTouch(v, event) }
        view.setOnClickListener { acceptTap() }
        touchTarget?.setOnTouchListener { v, event -> onBubbleTouch(v, event) }
        touchTarget?.setOnClickListener { acceptTap() }
    }

    fun hide() {
        if (resizeMode) exitResizeMode()
        if (pauseFired) onResume()
        pauseFired = false
        params?.let { p -> savedAnchors[automatic] = (bubbleCenterX ?: (p.x + (collapsed?.width ?: 0) / 2)) to (collapsedAnchor?.second ?: p.y) }
        DictationEvents.unregister(this)
        main.removeCallbacksAndMessages(null)
        removeView(collapsed)
        removeView(expanded)
        collapsed = null
        expanded = null
        params = null
        micButton = null
        waveform = null
        statusLabel = null
        timer = null
        touchTarget = null
        resizeHint = null
        collapsedAnchor = null
        bubbleCenterX = null
    }

    // -- DictationListener (all calls already on the main thread) ----------

    override fun onStateChanged(state: DictState) {
        if (state != DictState.RECORDING) {
            paused = false
            setQuiet(false)
        }
        if ((state == DictState.RECORDING || state == DictState.PREPARING) &&
            expanded != null
        ) {
            collapse()
        }
        syncVisual(state)
    }

    override fun onLevel(level01: Float) {
        val display = waveform ?: return
        if (collapsed == null) return
        display.setLevel(level01)
    }

    override fun onAudioStatus(status: AudioSignalStatus) {
        waveform?.setAudioStatus(status)
        if (DictationEvents.state == DictState.RECORDING) {
            statusLabel?.text = if (paused) "Paused" else status.label
            statusLabel?.setTextColor(when (status) {
                AudioSignalStatus.CLIPPING -> appContext.getColor(R.color.flow_error)
                AudioSignalStatus.TOO_QUIET, AudioSignalStatus.NOISY -> appContext.getColor(R.color.flow_warning)
                AudioSignalStatus.LISTENING -> appContext.getColor(R.color.flow_text)
            })
        }
    }

    override fun onPaused(paused: Boolean) = setPaused(paused)
    override fun onQuiet(quiet: Boolean) = setQuiet(quiet)

    override fun onResult(text: String, durationMs: Long) {
        if (automatic) return
        expand(text)
    }

    override fun onAutoResult(text: String, durationMs: Long, inserted: Boolean) {
        if (expanded != null) collapse()
    }

    /** Keep user placement, clamped above the keyboard when its bounds are known. */
    fun updatePlacement(keyboardTop: Int?) {
        this.keyboardTop = keyboardTop
        refreshSize()
    }

    /** Reapply the saved preference when settings change while the overlay is visible. */
    fun refreshSize() {
        if (collapsed != null) setBubbleSize(controls.bubbleSizeDp)
        else constrainPlacement()
    }

    private fun constrainPlacement() {
        val view = collapsed ?: return
        val p = params ?: return
        val metrics = appContext.resources.displayMetrics
        val targetDp = if (resizeMode) BubbleSizePolicy.resizeCaptureTargetDp(previewSizeDp ?: controls.bubbleSizeDp)
            else BubbleSizePolicy.touchTargetDp(previewSizeDp ?: controls.bubbleSizeDp)
        val active = DictationEvents.state == DictState.RECORDING
        val processing = DictationEvents.state == DictState.PREPARING || DictationEvents.state == DictState.TRANSCRIBING
        val contentWidth = maxOf(view.measuredWidth, view.width).takeIf { it > 0 } ?: dp(targetDp)
        val contentHeight = maxOf(view.measuredHeight, view.height).takeIf { it > 0 }
            ?: dp(targetDp + METER_HEIGHT_DP + 2 + (if (active) 20 else 0)) +
                if (active || processing) dp(36) else 0
        val center = bubbleCenterX ?: (p.x + contentWidth / 2)
        p.x = BubbleSizePolicy.originForCenter(center, contentWidth, metrics.widthPixels, dp(12))
        bubbleCenterX = BubbleSizePolicy.centerAfterClamp(p.x, contentWidth)
        val bottom = keyboardTop ?: metrics.heightPixels
        p.y = BubbleSizePolicy.topForContent(p.y, contentHeight, bottom, dp(72), dp(12))
        windowManager.updateViewLayout(view, p)
    }

    override fun onError(message: String) {
        Toast.makeText(appContext, message, Toast.LENGTH_LONG).show()
        if (expanded != null) collapse()
    }

    // -- Touch: drag vs tap vs hold ----------------------------------------

    private var downRawX = 0f
    private var downRawY = 0f
    private var offsetX = 0
    private var offsetY = 0
    private var dragging = false
    private var holdFired = false
    private var longPressConsumed = false
    private var pauseFired = false
    private var stateAtDown = DictState.IDLE
    private var resizing = false
    private var tapDownAtMs = 0L
    private var tapDownWithinSequence = false
    private var tapTimeOverrideMs: Long? = null
    private val holdRunnable = Runnable {
        if (dragging) return@Runnable
        tapSequence.cancelPending()
        main.removeCallbacks(tapTimeout)
        longPressConsumed = true
        when (controls.longPressAction) {
            BubbleGestureAction.HOLD_TO_TALK -> when (BubbleGesturePolicy.onHold(
                recordingAtDown = stateAtDown == DictState.RECORDING && DictationEvents.state == DictState.RECORDING,
                idleAtDown = stateAtDown == DictState.IDLE && DictationEvents.state == DictState.IDLE,
                dragged = false,
            )) {
                BubbleGesturePolicy.Decision.START -> { holdFired = true; commandStart() }
                BubbleGesturePolicy.Decision.PAUSE -> { pauseFired = true; onPause() }
                else -> Unit
            }
            BubbleGestureAction.RESIZE -> if (DictationEvents.state == DictState.IDLE) enterResizeMode()
            BubbleGestureAction.PAUSE_RESUME -> {
                if (DictationEvents.state == DictState.RECORDING) {
                    when (BubbleGesturePolicy.onPauseResumeToggle(paused)) {
                        BubbleGesturePolicy.Decision.PAUSE -> onPause()
                        BubbleGesturePolicy.Decision.RESUME -> onResume()
                        else -> Unit
                    }
                }
            }
            BubbleGestureAction.DISCARD -> {
                if (DictationEvents.state == DictState.RECORDING || DictationEvents.state == DictState.PREPARING) {
                    commandCancel()
                }
            }
            BubbleGestureAction.OPEN_FLOW -> openFlow()
            BubbleGestureAction.OPEN_SETTINGS -> openSettings()
            BubbleGestureAction.NONE -> Unit
        }
    }

    private fun onBubbleTouch(view: View, event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                didPinch = false
                val now = SystemClock.uptimeMillis()
                val deadline = tapSequence.pendingDeadlineMs()
                val expiredTap = tapSequence.onTimeout(now, controls.doubleTapAction)
                performTapDecision(expiredTap)
                tapDownAtMs = now
                tapDownWithinSequence = deadline != null && now <= deadline
                downRawX = event.rawX
                downRawY = event.rawY
                val p = params
                offsetX = if (p != null) (event.rawX - p.x).toInt() else 0
                offsetY = if (p != null) (event.rawY - p.y).toInt() else 0
                dragging = false
                holdFired = false
                longPressConsumed = false
                pauseFired = false
                stateAtDown = DictationEvents.state
                main.removeCallbacks(tapTimeout)
                if (!resizeMode) main.postDelayed(holdRunnable, HOLD_MS)
            }
            MotionEvent.ACTION_POINTER_DOWN -> {
                if (BubbleGesturePolicy.ownsPinch(resizeMode, event.pointerCount)) {
                    didPinch = true
                    resizing = true
                    tapSequence.cancelPending()
                    main.removeCallbacks(tapTimeout)
                    main.removeCallbacks(resizeModeTimeout)
                    pinchStartSizeDp = controls.bubbleSizeDp
                    pinchDistancePx = pointerDistance(event)
                    main.removeCallbacks(holdRunnable)
                }
            }
            MotionEvent.ACTION_MOVE -> {
                if (resizing && event.pointerCount >= 2) {
                    val deltaDp = ((pointerDistance(event) - pinchDistancePx) /
                        appContext.resources.displayMetrics.density).toInt()
                    setBubbleSize(BubbleSizePolicy.fromPinch(pinchStartSizeDp, deltaDp), persist = false)
                    return true
                }
                val dist = hypot((event.rawX - downRawX).toDouble(), (event.rawY - downRawY).toDouble())
                if (!didPinch && !resizeMode && !dragging && dist > touchSlop) {
                    dragging = true
                    main.removeCallbacks(holdRunnable)
                    main.removeCallbacks(tapTimeout)
                }
                if (dragging) {
                    params?.let { p ->
                        val metrics = appContext.resources.displayMetrics
                        p.x = ((event.rawX - offsetX).toInt()).coerceIn(
                            0, (metrics.widthPixels - (collapsed?.width ?: 0)).coerceAtLeast(0),
                        )
                        p.y = ((event.rawY - offsetY).toInt()).coerceIn(
                            0, (metrics.heightPixels - (collapsed?.height ?: 0)).coerceAtLeast(0),
                        )
                        bubbleCenterX = p.x + ((collapsed?.measuredWidth ?: collapsed?.width ?: 0) / 2)
                        constrainPlacement()
                        savedAnchors[automatic] = (bubbleCenterX ?: p.x) to p.y
                    }
                }
            }
            MotionEvent.ACTION_POINTER_UP -> {
                if (resizing) finishPinch(commit = true)
            }
            MotionEvent.ACTION_UP -> {
                main.removeCallbacks(holdRunnable)
                if (resizing) finishPinch(commit = true)
                when (BubbleGesturePolicy.onHoldRelease(pauseFired, holdFired, dragging)) {
                    BubbleGesturePolicy.Decision.RESUME -> onResume()
                    BubbleGesturePolicy.Decision.STOP -> {
                        // A hold owns its stop even if the pointer moved after it fired.
                        val state = DictationEvents.state
                        if (state == DictState.RECORDING || state == DictState.PREPARING) commandStop()
                    }
                    else -> when {
                        BubbleGesturePolicy.exitsResizeModeOnRelease(resizeMode, dragging, didPinch, longPressConsumed) -> exitResizeMode()
                        !dragging && !didPinch && !longPressConsumed && !resizeMode -> {
                            tapTimeOverrideMs = if (tapDownWithinSequence) tapDownAtMs else null
                            view.performClick()
                            tapTimeOverrideMs = null
                        }
                    }
                }
                dragging = false
                holdFired = false
                longPressConsumed = false
                pauseFired = false
                tapDownWithinSequence = false
                schedulePendingTapTimeout()
            }
            MotionEvent.ACTION_CANCEL -> {
                main.removeCallbacks(holdRunnable)
                main.removeCallbacks(tapTimeout)
                if (resizing) finishPinch(commit = false)
                if (resizeMode) exitResizeMode()
                // Gesture aborted by the system: discard, don't transcribe.
                when (BubbleGesturePolicy.onCancel(holdFired, pauseFired)) {
                    BubbleGesturePolicy.Decision.CANCEL -> commandCancel()
                    BubbleGesturePolicy.Decision.RESUME -> onResume()
                    else -> Unit
                }
                dragging = false
                holdFired = false
                longPressConsumed = false
                pauseFired = false
                schedulePendingTapTimeout()
            }
        }
        return true
    }

    private fun pointerDistance(event: MotionEvent): Float {
        if (event.pointerCount < 2) return 0f
        val dx = event.getX(0) - event.getX(1)
        val dy = event.getY(0) - event.getY(1)
        return hypot(dx.toDouble(), dy.toDouble()).toFloat()
    }

    private fun finishPinch(commit: Boolean) {
        if (!resizing) return
        if (commit) controls.bubbleSizeDp = previewSizeDp ?: pinchStartSizeDp
        else setBubbleSize(pinchStartSizeDp)
        previewSizeDp = null
        resizing = false
        exitResizeMode()
        constrainPlacement()
    }

    private fun acceptTap() {
        if (resizeMode) {
            exitResizeMode()
            return
        }
        val decision = tapSequence.onTap(
            nowMs = tapTimeOverrideMs ?: SystemClock.uptimeMillis(),
            state = DictationEvents.state,
            tripleTapAction = controls.tripleTapAction,
        )
        performTapDecision(decision)
        schedulePendingTapTimeout()
    }

    private fun schedulePendingTapTimeout() {
        main.removeCallbacks(tapTimeout)
        val deadline = tapSequence.pendingDeadlineMs() ?: return
        main.postDelayed(tapTimeout, (deadline - SystemClock.uptimeMillis()).coerceAtLeast(0L))
    }

    private fun performTapDecision(decision: BubbleGesturePolicy.Decision) {
        when (decision) {
            BubbleGesturePolicy.Decision.START -> commandStart()
            BubbleGesturePolicy.Decision.STOP -> commandStop()
            BubbleGesturePolicy.Decision.CANCEL -> commandCancel()
            BubbleGesturePolicy.Decision.DISCARD -> if (DictationEvents.state == DictState.RECORDING || DictationEvents.state == DictState.PREPARING) commandCancel()
            BubbleGesturePolicy.Decision.RESIZE -> enterResizeMode()
            BubbleGesturePolicy.Decision.PAUSE_RESUME -> if (DictationEvents.state == DictState.RECORDING) {
                if (paused) onResume() else onPause()
            }
            BubbleGesturePolicy.Decision.OPEN_FLOW -> openFlow()
            BubbleGesturePolicy.Decision.OPEN_SETTINGS -> openSettings()
            else -> Unit
        }
    }

    private fun openFlow() {
        launchUserRequestedScreen(Intent(appContext, MainActivity::class.java))
    }

    private fun openSettings() {
        launchUserRequestedScreen(Intent(appContext, SettingsActivity::class.java))
    }

    private fun launchUserRequestedScreen(intent: Intent) {
        try {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            appContext.startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(appContext, e.message ?: "Could not open Flow", Toast.LENGTH_LONG).show()
        }
    }

    private fun enterResizeMode() {
        if (!resizeMode) updateTouchTarget(resizeMode = true)
        resizeMode = true
        resizeHint?.apply {
            text = "Pinch to resize"
            visibility = View.VISIBLE
        }
        constrainPlacement()
        main.removeCallbacks(resizeModeTimeout)
        main.postDelayed(resizeModeTimeout, RESIZE_MODE_MS)
    }

    private fun exitResizeMode() {
        if (resizeMode) updateTouchTarget(resizeMode = false)
        resizeMode = false
        resizing = false
        resizeHint?.visibility = View.GONE
        main.removeCallbacks(resizeModeTimeout)
        constrainPlacement()
    }

    private fun updateTouchTarget(resizeMode: Boolean) {
        val target = touchTarget ?: return
        val layout = target.layoutParams ?: return
        val visible = previewSizeDp ?: controls.bubbleSizeDp
        val newTargetDp = if (resizeMode) BubbleSizePolicy.resizeCaptureTargetDp(visible)
            else BubbleSizePolicy.touchTargetDp(visible)
        val newTargetPx = dp(newTargetDp)
        val verticalOffsetPx = (layout.height - newTargetPx) / 2
        params?.let { it.y += verticalOffsetPx }
        layout.width = newTargetPx
        layout.height = newTargetPx
        target.layoutParams = layout
        collapsed?.requestLayout()
    }

    // -- Expand / collapse ---------------------------------------------------

    @SuppressLint("InflateParams")
    private fun expand(text: String) {
        val p = params ?: return
        if (resizeMode) exitResizeMode()
        removeView(collapsed)
        collapsed = null
        micButton = null
        touchTarget = null
        waveform = null
        statusLabel = null
        timer = null
        resizeHint = null
        if (expanded != null) {
            expanded?.findViewById<TextView>(R.id.bubble_text)?.text = text
            return
        }
        collapsedAnchor = p.x to p.y
        val metrics = appContext.resources.displayMetrics
        p.x = p.x.coerceIn(0, (metrics.widthPixels - dp(280)).coerceAtLeast(0))
        p.y = p.y.coerceIn(0, (metrics.heightPixels - dp(240)).coerceAtLeast(0))
        val view = inflater.inflate(R.layout.bubble_expanded, null)
        view.findViewById<TextView>(R.id.bubble_text).text = text
        view.findViewById<Button>(R.id.btn_bubble_insert).setOnClickListener {
            val reviewIntent = Intent(appContext, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                putExtra("review_text", text)
            }
            appContext.startActivity(reviewIntent)
            collapse()
        }
        view.findViewById<Button>(R.id.btn_bubble_copy).setOnClickListener {
            if (TextOutput.copy(appContext, text)) {
                Toast.makeText(appContext, R.string.copied, Toast.LENGTH_SHORT).show()
            }
            collapse()
        }
        view.findViewById<Button>(R.id.btn_bubble_close).setOnClickListener {
            collapse()
        }
        windowManager.addView(view, p)
        expanded = view
    }

    @SuppressLint("InflateParams")
    private fun collapse() {
        val p = params ?: return
        removeView(expanded)
        expanded = null
        if (collapsed != null) {
            syncVisual(DictationEvents.state)
            return
        }
        collapsedAnchor?.let { (x, y) -> p.x = x; p.y = y }
        collapsedAnchor = null
        val view = inflater.inflate(R.layout.bubble_collapsed, null)
        configureCollapsed(view)
        attachGestureHandlers(view)
        windowManager.addView(view, p)
        collapsed = view
        view.addOnLayoutChangeListener { _, _, _, _, _, oldLeft, oldTop, oldRight, oldBottom ->
            if ((oldRight - oldLeft) != view.width || (oldBottom - oldTop) != view.height) constrainPlacement()
        }
        constrainPlacement()
        syncVisual(DictationEvents.state)
    }

    private fun syncVisual(state: DictState) {
        val mic = micButton ?: return
        val recording = state == DictState.RECORDING
        val processing = state == DictState.PREPARING || state == DictState.TRANSCRIBING
        main.removeCallbacks(timerTick)
        timer?.visibility = if (recording) View.VISIBLE else View.GONE
        if (recording) main.post(timerTick) else timerSeconds = -1L
        waveform?.setRecording(recording && !paused)
        waveform?.setProcessing(processing)
        waveform?.setAudioStatus(DictationEvents.audioStatus)
        waveform?.visibility = if (recording || processing) View.VISIBLE else View.GONE
        waveform?.layoutParams = waveform?.layoutParams?.apply {
            width = dp(maxOf(BubbleSizePolicy.clamp(controls.bubbleSizeDp), MIN_METER_WIDTH_DP))
            height = dp(METER_HEIGHT_DP)
        }
        statusLabel?.text = when {
            state == DictState.PREPARING -> "Getting ready…"
            state == DictState.TRANSCRIBING -> "Transcribing…"
            recording && paused -> "Paused"
            recording -> DictationEvents.audioStatus.label
            else -> ""
        }
        statusLabel?.setTextColor(when {
            processing -> appContext.getColor(R.color.flow_text)
            DictationEvents.audioStatus == AudioSignalStatus.CLIPPING -> appContext.getColor(R.color.flow_error)
            DictationEvents.audioStatus == AudioSignalStatus.TOO_QUIET ||
                DictationEvents.audioStatus == AudioSignalStatus.NOISY -> appContext.getColor(R.color.flow_warning)
            else -> appContext.getColor(R.color.flow_text)
        })
        statusLabel?.visibility = if (recording || processing) View.VISIBLE else View.GONE
        mic.setImageResource(if (recording && paused) R.drawable.ic_mic_paused else R.drawable.ic_mic)
        mic.contentDescription = if (recording && paused) appContext.getString(R.string.bubble_paused) else appContext.getString(when (state) {
            DictState.IDLE -> R.string.bubble_start
            DictState.RECORDING -> R.string.bubble_finish
            DictState.PREPARING -> R.string.bubble_cancel_preparation
            DictState.TRANSCRIBING -> R.string.bubble_processing
            DictState.DISCARDING -> R.string.bubble_discarding
        })
        touchTarget?.contentDescription = mic.contentDescription
        mic.isEnabled = state != DictState.TRANSCRIBING && state != DictState.DISCARDING
        when (state) {
            DictState.RECORDING -> {
                mic.setBackgroundResource(R.drawable.bubble_bg_recording)
            }
            DictState.IDLE, DictState.PREPARING, DictState.TRANSCRIBING, DictState.DISCARDING -> {
                mic.setBackgroundResource(R.drawable.bubble_bg)
            }
        }
        constrainPlacement()
    }

    /** Apply the saved size and add separate waveform and resize controls. */
    private fun configureCollapsed(view: View) {
        micButton = view.findViewById(R.id.bubble_mic)
        touchTarget = view.findViewById(R.id.bubble_touch_target)
        val sizeDp = BubbleSizePolicy.clamp(controls.bubbleSizeDp)
        val sizePx = dp(sizeDp)
        val targetPx = dp(BubbleSizePolicy.touchTargetDp(sizeDp))
        micButton?.layoutParams = micButton?.layoutParams?.apply {
            width = sizePx
            height = sizePx
        }
        touchTarget?.layoutParams = touchTarget?.layoutParams?.apply {
            width = targetPx
            height = targetPx
        }

        val column = view as? LinearLayout ?: return
        val oldMeter = view.findViewById<View>(R.id.bubble_level)
        val meterIndex = column.indexOfChild(oldMeter)
        if (meterIndex >= 0) column.removeViewAt(meterIndex)

        val waveformView = BubbleWaveformView(appContext).apply {
            contentDescription = "Recording audio level"
            layoutParams = LinearLayout.LayoutParams(dp(maxOf(sizeDp, MIN_METER_WIDTH_DP)), dp(METER_HEIGHT_DP)).apply {
                topMargin = dp(2)
            }
        }
        waveform = waveformView
        column.addView(waveformView, meterIndex.coerceAtLeast(0))

        statusLabel = TextView(appContext).apply {
            textSize = 14f
            gravity = Gravity.CENTER
            setTextColor(appContext.getColor(R.color.flow_text))
            background = transientSurface()
            setPadding(dp(10), dp(4), dp(10), dp(4))
            minHeight = dp(32)
            maxWidth = (appContext.resources.displayMetrics.widthPixels - dp(48)).coerceAtLeast(dp(80))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            visibility = View.GONE
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        }.also { column.addView(it, meterIndex.coerceAtLeast(0) + 1) }

        timerSeconds = -1L
        timer = TextView(appContext).apply {
            textSize = 12f
            gravity = Gravity.CENTER
            setTextColor(appContext.getColor(R.color.flow_primary))
            background = transientSurface()
            setPadding(dp(8), dp(2), dp(8), dp(2))
            visibility = View.GONE
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(24))
        }.also { column.addView(it) }

        waveformView.setQuiet(quiet)
        resizeHint = TextView(appContext).apply {
            text = "Pinch to resize"
            textSize = 14f
            gravity = Gravity.CENTER
            setTextColor(appContext.getColor(R.color.flow_primary))
            background = transientSurface()
            setPadding(dp(10), dp(4), dp(10), dp(4))
            visibility = View.GONE
            minHeight = dp(32)
            maxWidth = (appContext.resources.displayMetrics.widthPixels - dp(48)).coerceAtLeast(dp(80))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        }.also { column.addView(it) }
    }

    private fun transientSurface() = GradientDrawable().apply {
        setColor(appContext.getColor(R.color.flow_surface))
        cornerRadius = dp(14).toFloat()
        setStroke(dp(1), appContext.getColor(R.color.flow_outline))
    }

    private fun setBubbleSize(sizeDp: Int, persist: Boolean = true) {
        val size = BubbleSizePolicy.clamp(sizeDp)
        if (persist) controls.bubbleSizeDp = size
        previewSizeDp = if (persist) null else size
        val px = dp(size)
        updateTouchTarget(resizeMode)
        micButton?.layoutParams = micButton?.layoutParams?.apply {
            width = px
            height = px
        }
        waveform?.layoutParams = waveform?.layoutParams?.apply {
            width = dp(maxOf(size, MIN_METER_WIDTH_DP))
            height = dp(METER_HEIGHT_DP)
        }
        touchTarget?.contentDescription = "Floating talk button, currently ${size} dp. Tap to start or stop."
        collapsed?.requestLayout()
        constrainPlacement()
    }

    private fun removeView(view: View?) {
        if (view == null) return
        try {
            windowManager.removeView(view)
        } catch (_: Exception) {
            // Already detached; ignore.
        }
    }

    private fun commandStart() {
        if (appContext.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            Toast.makeText(appContext,
                "Open Flow and tap Allow microphone, then try again.",
                Toast.LENGTH_LONG).show()
            return
        }
        val targetId = if (automatic) AutoInputBridge.captureTarget() else null
        try {
            if (automatic && targetId == null) {
                Toast.makeText(appContext, "Focus an editable field before recording.", Toast.LENGTH_LONG).show()
                return
            }
            appContext.startForegroundService(DictationService.startIntent(appContext, targetId))
        } catch (e: Exception) {
            targetId?.let { AutoInputBridge.clearTarget(it) }
            Toast.makeText(appContext, e.message ?: "Cannot start", Toast.LENGTH_LONG).show()
        }
    }

    private fun commandStop() {
        // Plain startService: the service is already foreground, and a
        // startForegroundService() stop to an exited service would crash
        // with ForegroundServiceDidNotStartInTimeException.
        try {
            appContext.startService(DictationService.stopIntent(appContext))
        } catch (e: Exception) {
            Toast.makeText(appContext, e.message ?: "Cannot stop", Toast.LENGTH_LONG).show()
        }
    }

    private fun commandCancel() {
        try {
            appContext.startService(DictationService.cancelIntent(appContext))
        } catch (e: Exception) {
            Toast.makeText(appContext, e.message ?: "Cannot cancel", Toast.LENGTH_LONG).show()
        }
    }

    companion object {
        private const val HOLD_MS = 400L
        private const val RESIZE_MODE_MS = 5_000L
        private const val MIN_METER_WIDTH_DP = 72
        private const val METER_HEIGHT_DP = 24
    }
}
