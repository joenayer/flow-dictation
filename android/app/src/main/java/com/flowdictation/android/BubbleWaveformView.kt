package com.flowdictation.android

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.animation.ValueAnimator
import android.util.AttributeSet
import android.view.View
import android.os.Handler
import android.os.Looper
import kotlin.math.max

/** A compact, scrolling RMS history. It schedules frames only while recording. */
internal class BubbleWaveformView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    private val main = Handler(Looper.getMainLooper())
    private val history = FloatArray(BAR_COUNT)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = context.getColor(R.color.flow_primary)
        strokeWidth = context.resources.displayMetrics.density * 2f
        strokeCap = Paint.Cap.ROUND
    }
    private var targetLevel = 0f
    private var smoothedLevel = 0f
    private var recording = false
    private var processing = false
    private var phase = 0
    private var quiet = false
    private var audioStatus = AudioSignalStatus.LISTENING

    fun setQuiet(quiet: Boolean) {
        this.quiet = quiet
        invalidate()
    }

    fun setAudioStatus(status: AudioSignalStatus) {
        audioStatus = status
        invalidate()
    }

    private val frame = object : Runnable {
        override fun run() {
            if (!recording && !processing) return
            if (recording) advanceLevel() else phase = (phase + 1) % (BAR_COUNT * 3)
            invalidate()
            main.postDelayed(this, FRAME_MS)
        }
    }

    fun setLevel(level01: Float) {
        if (recording) {
            targetLevel = level01.coerceIn(0f, 1f)
            if (!ValueAnimator.areAnimatorsEnabled()) {
                advanceLevel()
                invalidate()
            }
        }
    }

    fun setRecording(active: Boolean) {
        if (recording == active) return
        recording = active
        if (active) {
            processing = false
        } else {
            targetLevel = 0f
            smoothedLevel = 0f
            history.fill(0f)
        }
        updateFrames()
    }

    /** Deliberately indeterminate: never invent an audio waveform or percent while decoding. */
    fun setProcessing(active: Boolean) {
        if (processing == active) return
        processing = active
        if (active) recording = false
        phase = 0
        updateFrames()
    }

    private fun advanceLevel() {
        val factor = if (targetLevel > smoothedLevel) 0.65f else 0.2f
        smoothedLevel += (targetLevel - smoothedLevel) * factor
        System.arraycopy(history, 1, history, 0, history.lastIndex)
        history[history.lastIndex] = smoothedLevel
    }

    private fun updateFrames() {
        main.removeCallbacks(frame)
        if ((recording || processing) && ValueAnimator.areAnimatorsEnabled()) main.post(frame)
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val spacing = width.toFloat() / BAR_COUNT
        val mid = height / 2f
        val maxHalfHeight = max(0f, mid - paint.strokeWidth)
        paint.color = when {
            processing -> context.getColor(R.color.flow_primary)
            audioStatus == AudioSignalStatus.CLIPPING -> context.getColor(R.color.flow_error)
            quiet || audioStatus == AudioSignalStatus.NOISY || audioStatus == AudioSignalStatus.TOO_QUIET -> context.getColor(R.color.flow_warning)
            else -> context.getColor(R.color.flow_primary)
        }
        if (processing) {
            // Three moving dots read as work in progress, not measured audio.
            for (index in 0..2) {
                paint.alpha = if ((phase / 7) % 3 == index) 255 else 90
                canvas.drawCircle(width * (0.3f + index * 0.2f), mid, paint.strokeWidth * 1.2f, paint)
            }
            paint.alpha = 255
            return
        }
        for (index in history.indices) {
            val half = max(paint.strokeWidth, history[index] * maxHalfHeight)
            val x = spacing * (index + 0.5f)
            canvas.drawLine(x, mid - half, x, mid + half, paint)
        }
    }

    override fun onDetachedFromWindow() {
        processing = false
        setRecording(false)
        main.removeCallbacks(frame)
        super.onDetachedFromWindow()
    }

    private companion object {
        const val BAR_COUNT = 25
        const val FRAME_MS = 33L
    }
}
