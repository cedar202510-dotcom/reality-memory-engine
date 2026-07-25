package com.realitymemory.glasses.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.os.SystemClock
import android.view.View
import com.realitymemory.glasses.runtime.RuntimeDisplayKind
import com.realitymemory.glasses.runtime.RuntimeStatus
import kotlin.math.min

class GlassesUiView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = GLASS_GREEN
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        typeface = Typeface.create("sans-serif", Typeface.NORMAL)
    }

    private var status = RuntimeStatusStoreDefaults.empty

    init {
        setBackgroundColor(Color.BLACK)
        isFocusable = true
        isClickable = true
        defaultFocusHighlightEnabled = false
    }

    fun render(newStatus: RuntimeStatus) {
        status = newStatus
        contentDescription = when (newStatus.displayKind) {
            RuntimeDisplayKind.DISCLOSURE ->
                "RealGit 已开启现实感知。正在为您整理现实记忆。单击取消本次。"
            RuntimeDisplayKind.REMINDER -> newStatus.message
            RuntimeDisplayKind.CANCELLED -> "本次现实感知已取消。再次佩戴时重新开启。"
            RuntimeDisplayKind.BLOCKED -> newStatus.message
            RuntimeDisplayKind.NONE -> ""
        }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        // Keep the verified pure-black window background as the only
        // full-screen fill; this View only draws the green HUD elements.
        val scale = min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT)
        val originX = (width - DESIGN_WIDTH * scale) / 2f
        val originY = (height - DESIGN_HEIGHT * scale) / 2f

        canvas.save()
        canvas.translate(originX, originY)
        canvas.scale(scale, scale)
        when (status.displayKind) {
            RuntimeDisplayKind.DISCLOSURE -> drawDisclosure(canvas)
            RuntimeDisplayKind.REMINDER -> drawReminder(canvas, status.message)
            RuntimeDisplayKind.CANCELLED -> drawCancelled(canvas)
            RuntimeDisplayKind.BLOCKED -> drawBlocked(canvas, status.message)
            RuntimeDisplayKind.NONE -> Unit
        }
        canvas.restore()

        if (status.displayKind == RuntimeDisplayKind.DISCLOSURE) {
            postInvalidateDelayed(BLINK_REFRESH_MS)
        }
    }

    private fun drawDisclosure(canvas: Canvas) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f
        paint.alpha = 255
        canvas.drawCircle(CENTER_X, 247f, 12f, paint)

        paint.style = Paint.Style.FILL
        paint.alpha = if (SystemClock.uptimeMillis() % BLINK_PERIOD_MS < BLINK_ON_MS) 255 else 72
        canvas.drawCircle(CENTER_X, 247f, 3f, paint)
        paint.alpha = 255

        drawCenteredText(canvas, "RealGit 已开启现实感知", 286f, 17f, Typeface.BOLD)
        drawCenteredText(canvas, "正在为您整理现实记忆", 319f, 12f, Typeface.NORMAL)
        drawCenteredText(canvas, "单击取消本次", 358f, 11f, Typeface.NORMAL)
    }

    private fun drawReminder(canvas: Canvas, message: String) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2f
        paint.alpha = 255
        canvas.drawLine(40f, 215f, 40f, 355f, paint)
        canvas.drawCircle(76f, 235f, 12f, paint)

        paint.style = Paint.Style.FILL
        paint.strokeWidth = 1f
        drawCenteredGlyph(canvas, "!", 76f, 240f, 14f)

        val lines = wrapText(message, 17f, 344f)
        lines.take(3).forEachIndexed { index, line ->
            drawText(canvas, line, 64f, 285f + index * 27f, 17f, Typeface.BOLD)
        }
        drawText(canvas, "单击知道了", 64f, 372f, 11f, Typeface.NORMAL)
    }

    private fun drawCancelled(canvas: Canvas) {
        drawCircleGlyph(canvas, "×", 247f)
        drawCenteredText(canvas, "本次现实感知已取消", 290f, 17f, Typeface.BOLD)
        drawCenteredText(canvas, "再次佩戴时重新开启", 323f, 12f, Typeface.NORMAL)
    }

    private fun drawBlocked(canvas: Canvas, message: String) {
        drawCircleGlyph(canvas, "!", 247f)
        drawCenteredText(canvas, "现实感知暂未开启", 290f, 17f, Typeface.BOLD)
        val detail = message.ifBlank { "请检查相机和麦克风权限" }
        wrapText(detail, 12f, 360f).take(2).forEachIndexed { index, line ->
            drawCenteredText(canvas, line, 323f + index * 20f, 12f, Typeface.NORMAL)
        }
    }

    private fun drawCircleGlyph(canvas: Canvas, glyph: String, centerY: Float) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f
        paint.alpha = 255
        canvas.drawCircle(CENTER_X, centerY, 12f, paint)
        paint.style = Paint.Style.FILL
        drawCenteredGlyph(canvas, glyph, CENTER_X, centerY + 5f, 14f)
    }

    private fun drawCenteredGlyph(
        canvas: Canvas,
        value: String,
        centerX: Float,
        baselineY: Float,
        size: Float,
    ) {
        prepareText(size, Typeface.NORMAL)
        canvas.drawText(value, centerX - paint.measureText(value) / 2f, baselineY, paint)
    }

    private fun drawCenteredText(
        canvas: Canvas,
        value: String,
        baselineY: Float,
        size: Float,
        style: Int,
    ) {
        prepareText(size, style)
        canvas.drawText(value, CENTER_X - paint.measureText(value) / 2f, baselineY, paint)
    }

    private fun drawText(
        canvas: Canvas,
        value: String,
        x: Float,
        baselineY: Float,
        size: Float,
        style: Int,
    ) {
        prepareText(size, style)
        canvas.drawText(value, x, baselineY, paint)
    }

    private fun prepareText(size: Float, style: Int) {
        paint.style = Paint.Style.FILL
        paint.color = GLASS_GREEN
        paint.alpha = 255
        paint.textSize = size
        paint.typeface = Typeface.create("sans-serif", style)
        paint.letterSpacing = 0f
    }

    private fun wrapText(value: String, size: Float, maxWidth: Float): List<String> {
        prepareText(size, Typeface.BOLD)
        if (paint.measureText(value) <= maxWidth) return listOf(value)

        val lines = mutableListOf<String>()
        var start = 0
        while (start < value.length) {
            val count = paint.breakText(value, start, value.length, true, maxWidth, null)
                .coerceAtLeast(1)
            lines += value.substring(start, start + count)
            start += count
        }
        return lines
    }

    private object RuntimeStatusStoreDefaults {
        val empty = RuntimeStatus(
            state = com.realitymemory.glasses.runtime.SessionState.ARMED,
            message = "",
            lastEvidence = null,
            displayKind = RuntimeDisplayKind.NONE,
        )
    }

    companion object {
        private const val DESIGN_WIDTH = 480f
        private const val DESIGN_HEIGHT = 640f
        private const val CENTER_X = DESIGN_WIDTH / 2f
        private const val BLINK_PERIOD_MS = 1_600L
        private const val BLINK_ON_MS = 928L
        private const val BLINK_REFRESH_MS = 100L
        private val GLASS_GREEN = Color.rgb(0, 255, 0)
    }
}
