package com.realitymemory.glasses.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Typeface
import android.os.SystemClock
import android.view.View
import com.realitymemory.glasses.downlink.DownlinkPresentation
import com.realitymemory.glasses.downlink.PresentationIntent
import com.realitymemory.glasses.downlink.PresentationInteraction
import com.realitymemory.glasses.runtime.RuntimeDisplayKind
import com.realitymemory.glasses.runtime.RuntimeStatus
import kotlin.math.min

class GlassesUiView(
    context: Context,
    transparentBackground: Boolean = false,
) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = GLASS_GREEN
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        typeface = Typeface.create("sans-serif", Typeface.NORMAL)
    }

    private var status = RuntimeStatusStoreDefaults.empty

    init {
        setBackgroundColor(if (transparentBackground) Color.TRANSPARENT else Color.BLACK)
        isFocusable = true
        isClickable = true
        defaultFocusHighlightEnabled = false
    }

    fun render(newStatus: RuntimeStatus) {
        status = newStatus
        contentDescription = when (newStatus.displayKind) {
            RuntimeDisplayKind.DISCLOSURE ->
                "RealGit 已开启现实感知。正在为您整理现实记忆。"
            RuntimeDisplayKind.REMINDER -> newStatus.message
            RuntimeDisplayKind.PRESENTATION -> newStatus.presentation?.let {
                listOfNotNull(it.title, it.body).joinToString("。")
            }.orEmpty()
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
            RuntimeDisplayKind.PRESENTATION ->
                status.presentation?.let { drawPresentation(canvas, it) }
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
        val phase = (SystemClock.uptimeMillis() % SENSING_PERIOD_MS).toFloat() /
            SENSING_PERIOD_MS
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f
        paint.alpha = (180f * (1f - phase)).toInt().coerceIn(0, 180)
        canvas.drawCircle(CENTER_X, 235f, 22f + phase * 18f, paint)
        paint.alpha = 230
        canvas.drawCircle(CENTER_X, 235f, 22f, paint)

        paint.style = Paint.Style.FILL
        val coreRadius = 2.7f + 0.8f * (1f - phase)
        paint.alpha = (150 + 105 * (1f - phase)).toInt()
        canvas.drawCircle(CENTER_X, 235f, coreRadius, paint)
        paint.alpha = 255

        drawCenteredText(canvas, "RealGit 已开启现实感知", 292f, 17f, Typeface.BOLD)
        drawCenteredText(canvas, "正在为您整理现实记忆", 325f, 12f, Typeface.NORMAL)
        drawActionHint(canvas, "×", "取消")
    }

    private fun drawReminder(canvas: Canvas, message: String) {
        drawMessageFrame(canvas)
        drawAlertIcon(canvas)

        val lines = wrapText(message, 17f, MESSAGE_TEXT_WIDTH, Typeface.BOLD)
        lines.take(3).forEachIndexed { index, line ->
            drawText(canvas, line, MESSAGE_X, 285f + index * 27f, 17f, Typeface.BOLD)
        }
    }

    private fun drawPresentation(
        canvas: Canvas,
        presentation: DownlinkPresentation,
    ) {
        drawMessageFrame(canvas)
        drawSemanticIcon(canvas, presentation.intent)

        val titleLines = wrapText(
            presentation.title,
            17f,
            MESSAGE_TEXT_WIDTH,
            Typeface.BOLD,
        ).take(2)
        titleLines.forEachIndexed { index, line ->
            drawText(canvas, line, MESSAGE_X, 285f + index * 27f, 17f, Typeface.BOLD)
        }

        presentation.body?.let { body ->
            val bodyBaseline = 285f + titleLines.size * 27f + 7f
            wrapText(body, 12f, MESSAGE_TEXT_WIDTH, Typeface.NORMAL)
                .take(2)
                .forEachIndexed { index, line ->
                    drawText(
                        canvas,
                        line,
                        MESSAGE_X,
                        bodyBaseline + index * 19f,
                        12f,
                        Typeface.NORMAL,
                    )
                }
        }

        when (presentation.interaction) {
            PresentationInteraction.ACKNOWLEDGE ->
                drawPresentationActionButton(canvas, "✓", "知道了")
            PresentationInteraction.COMPLETE_TASK ->
                drawPresentationActionButton(canvas, "✓", "完成")
            PresentationInteraction.ADD_TO_SHOPPING_LIST ->
                drawPresentationActionButton(canvas, "+", "加入采购清单")
            PresentationInteraction.DISMISS ->
                drawPresentationActionButton(canvas, "×", "关闭")
            PresentationInteraction.NONE -> Unit
        }
    }

    private fun drawMessageFrame(canvas: Canvas) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2f
        paint.alpha = 255
        canvas.drawLine(40f, 230f, 40f, 350f, paint)
    }

    private fun drawAlertIcon(canvas: Canvas) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f
        canvas.drawCircle(ICON_X, ICON_Y, 12f, paint)
        paint.style = Paint.Style.FILL
        drawCenteredGlyph(canvas, "!", ICON_X, ICON_Y + 5f, 14f)
    }

    private fun drawSemanticIcon(
        canvas: Canvas,
        intent: PresentationIntent,
    ) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f
        paint.alpha = 255
        when (intent) {
            PresentationIntent.ANSWER -> {
                val star = Path().apply {
                    moveTo(ICON_X, ICON_Y - 13f)
                    lineTo(ICON_X + 3f, ICON_Y - 3f)
                    lineTo(ICON_X + 13f, ICON_Y)
                    lineTo(ICON_X + 3f, ICON_Y + 3f)
                    lineTo(ICON_X, ICON_Y + 13f)
                    lineTo(ICON_X - 3f, ICON_Y + 3f)
                    lineTo(ICON_X - 13f, ICON_Y)
                    lineTo(ICON_X - 3f, ICON_Y - 3f)
                    close()
                }
                canvas.drawPath(star, paint)
                canvas.drawCircle(ICON_X + 14f, ICON_Y + 13f, 2.2f, paint)
            }
            PresentationIntent.REMINDER,
            PresentationIntent.SYSTEM,
            -> drawAlertIcon(canvas)
            PresentationIntent.TASK -> {
                canvas.drawRoundRect(
                    ICON_X - 11f,
                    ICON_Y - 14f,
                    ICON_X + 11f,
                    ICON_Y + 14f,
                    2f,
                    2f,
                    paint,
                )
                val check = Path().apply {
                    moveTo(ICON_X - 6f, ICON_Y)
                    lineTo(ICON_X - 1f, ICON_Y + 5f)
                    lineTo(ICON_X + 7f, ICON_Y - 6f)
                }
                canvas.drawPath(check, paint)
            }
            PresentationIntent.CONSUMABLE -> {
                canvas.drawRoundRect(
                    ICON_X - 12f,
                    ICON_Y - 7f,
                    ICON_X + 12f,
                    ICON_Y + 14f,
                    2f,
                    2f,
                    paint,
                )
                canvas.drawArc(
                    ICON_X - 7f,
                    ICON_Y - 15f,
                    ICON_X + 7f,
                    ICON_Y - 1f,
                    190f,
                    160f,
                    false,
                    paint,
                )
                canvas.drawLine(ICON_X - 4f, ICON_Y + 4f, ICON_X + 4f, ICON_Y + 4f, paint)
                canvas.drawLine(ICON_X, ICON_Y, ICON_X, ICON_Y + 8f, paint)
            }
            PresentationIntent.PRIVACY -> {
                val shield = Path().apply {
                    moveTo(ICON_X, ICON_Y - 14f)
                    lineTo(ICON_X + 11f, ICON_Y - 9f)
                    lineTo(ICON_X + 10f, ICON_Y + 3f)
                    cubicTo(
                        ICON_X + 8f,
                        ICON_Y + 10f,
                        ICON_X + 3f,
                        ICON_Y + 13f,
                        ICON_X,
                        ICON_Y + 15f,
                    )
                    cubicTo(
                        ICON_X - 3f,
                        ICON_Y + 13f,
                        ICON_X - 8f,
                        ICON_Y + 10f,
                        ICON_X - 10f,
                        ICON_Y + 3f,
                    )
                    lineTo(ICON_X - 11f, ICON_Y - 9f)
                    close()
                }
                canvas.drawPath(shield, paint)
                canvas.drawLine(
                    ICON_X - 8f,
                    ICON_Y + 9f,
                    ICON_X + 8f,
                    ICON_Y - 9f,
                    paint,
                )
            }
        }
    }

    private fun drawActionHint(
        canvas: Canvas,
        glyph: String,
        label: String,
    ) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f
        paint.alpha = 205
        canvas.drawCircle(ACTION_X, ACTION_Y, 10f, paint)
        paint.style = Paint.Style.FILL
        drawCenteredGlyph(canvas, glyph, ACTION_X, ACTION_Y + 4f, 11f)
        paint.alpha = 175
        drawCenteredTextAt(canvas, label, ACTION_X, ACTION_Y + 29f, 9f, Typeface.NORMAL)
        paint.alpha = 255
    }

    private fun drawPresentationActionButton(
        canvas: Canvas,
        glyph: String,
        label: String,
    ) {
        prepareText(10f, Typeface.BOLD, 230)
        val width = (paint.measureText(label) + 46f).coerceIn(68f, 126f)
        val left = ACTION_BUTTON_RIGHT - width
        val top = ACTION_BUTTON_CENTER_Y - 15f
        val bottom = ACTION_BUTTON_CENTER_Y + 15f

        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f
        paint.alpha = 215
        canvas.drawRoundRect(
            left,
            top,
            ACTION_BUTTON_RIGHT,
            bottom,
            4f,
            4f,
            paint,
        )

        paint.style = Paint.Style.FILL
        drawCenteredGlyph(
            canvas,
            glyph,
            left + 17f,
            ACTION_BUTTON_CENTER_Y + 4f,
            11f,
        )
        drawText(
            canvas,
            label,
            left + 31f,
            ACTION_BUTTON_CENTER_Y + 4f,
            10f,
            Typeface.BOLD,
        )
        paint.alpha = 255
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
        wrapText(detail, 12f, 360f, Typeface.NORMAL).take(2).forEachIndexed { index, line ->
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

    private fun drawCenteredTextAt(
        canvas: Canvas,
        value: String,
        centerX: Float,
        baselineY: Float,
        size: Float,
        style: Int,
    ) {
        val previousAlpha = paint.alpha
        prepareText(size, style, previousAlpha)
        canvas.drawText(value, centerX - paint.measureText(value) / 2f, baselineY, paint)
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

    private fun prepareText(
        size: Float,
        style: Int,
        alpha: Int = 255,
    ) {
        paint.style = Paint.Style.FILL
        paint.color = GLASS_GREEN
        paint.alpha = alpha
        paint.textSize = size
        paint.typeface = Typeface.create("sans-serif", style)
        paint.letterSpacing = 0f
    }

    private fun wrapText(
        value: String,
        size: Float,
        maxWidth: Float,
        style: Int,
    ): List<String> {
        prepareText(size, style)
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
        private const val ICON_X = 76f
        private const val ICON_Y = 235f
        private const val MESSAGE_X = 64f
        private const val MESSAGE_TEXT_WIDTH = 300f
        private const val ACTION_X = 420f
        private const val ACTION_Y = 350f
        private const val ACTION_BUTTON_RIGHT = 450f
        private const val ACTION_BUTTON_CENTER_Y = 395f
        private const val SENSING_PERIOD_MS = 2_400L
        private const val BLINK_REFRESH_MS = 100L
        private val GLASS_GREEN = Color.rgb(0, 255, 0)
    }
}
