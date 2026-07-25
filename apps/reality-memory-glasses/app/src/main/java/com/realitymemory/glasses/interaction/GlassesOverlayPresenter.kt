package com.realitymemory.glasses.interaction

import android.content.Context
import android.graphics.PixelFormat
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import android.view.Gravity
import android.view.KeyEvent
import android.view.WindowManager
import com.realitymemory.glasses.downlink.PresentationInteraction
import com.realitymemory.glasses.runtime.RuntimeStatus
import com.realitymemory.glasses.ui.GlassesUiView

/**
 * 在后台 Runtime 收到用户可见消息时短暂呈现独占消息层。
 *
 * 普通后台服务不能可靠拉起 Activity；RV101 Debug 联调通过 SYSTEM_ALERT_WINDOW
 * 验证这条路径。消息层使用不发光的纯黑画布遮住桌面 UI，只绘制绿色 HUD 内容；
 * 正式分发仍需用户授权或 Rokid 系统白名单。
 */
class GlassesOverlayPresenter(context: Context) {
    private val appContext = context.applicationContext
    private val windowManager = appContext.getSystemService(WindowManager::class.java)
    private val powerManager = appContext.getSystemService(PowerManager::class.java)
    private var activeView: GlassesUiView? = null
    private var presentationWakeLock: PowerManager.WakeLock? = null

    fun show(
        status: RuntimeStatus,
        visibleDurationMs: Long,
        onVisible: () -> Unit,
        onPrimaryAction: () -> Unit,
    ): OverlayResult {
        if (!Settings.canDrawOverlays(appContext)) {
            return OverlayResult(
                shown = false,
                reason = "SYSTEM_ALERT_WINDOW_NOT_GRANTED",
            )
        }
        dismiss()
        val initiallyInteractive = powerManager.isInteractive
        val wakeRequested = !initiallyInteractive
        if (wakeRequested) {
            acquirePresentationWakeLock(visibleDurationMs + WAKE_LOCK_MARGIN_MS)
        }
        val view = GlassesUiView(appContext, transparentBackground = false).apply {
            render(status)
            keepScreenOn = true
        }
        val acceptsPrimaryAction =
            status.presentation?.interaction != null &&
                status.presentation.interaction != PresentationInteraction.NONE
        if (acceptsPrimaryAction) {
            view.isFocusableInTouchMode = true
            view.setOnClickListener { onPrimaryAction() }
            view.setOnKeyListener { _, keyCode, event ->
                if (
                    event.action == KeyEvent.ACTION_UP &&
                    keyCode in PRIMARY_ACTION_KEY_CODES
                ) {
                    onPrimaryAction()
                    true
                } else {
                    keyCode in PRIMARY_ACTION_KEY_CODES
                }
            }
        }
        val focusFlag = if (acceptsPrimaryAction) {
            0
        } else {
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        }
        val parameters = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                focusFlag or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED,
            PixelFormat.OPAQUE,
        ).apply {
            gravity = Gravity.FILL
            title = "RealGitPresentation"
        }
        return runCatching {
            windowManager.addView(view, parameters)
            activeView = view
            if (acceptsPrimaryAction) view.requestFocus()
            confirmVisible(view, onVisible)
            OverlayResult(
                shown = true,
                reason = null,
                initiallyInteractive = initiallyInteractive,
                wakeRequested = wakeRequested,
            )
        }.getOrElse { error ->
            activeView = null
            releasePresentationWakeLock()
            OverlayResult(
                shown = false,
                reason = "${error.javaClass.simpleName}: ${error.message}",
                initiallyInteractive = initiallyInteractive,
                wakeRequested = wakeRequested,
            )
        }
    }

    fun dismiss() {
        val view = activeView ?: return
        activeView = null
        runCatching { windowManager.removeViewImmediate(view) }
        releasePresentationWakeLock()
    }

    private fun confirmVisible(
        view: GlassesUiView,
        onVisible: () -> Unit,
    ) {
        val deadline = SystemClock.uptimeMillis() + DISPLAY_WAKE_CONFIRM_TIMEOUT_MS
        val confirmation = object : Runnable {
            override fun run() {
                if (activeView !== view || !view.isAttachedToWindow) return
                if (powerManager.isInteractive) {
                    view.postOnAnimation(onVisible)
                    return
                }
                if (SystemClock.uptimeMillis() < deadline) {
                    view.postDelayed(this, DISPLAY_WAKE_CONFIRM_INTERVAL_MS)
                }
            }
        }
        view.post(confirmation)
    }

    @Suppress("DEPRECATION")
    private fun acquirePresentationWakeLock(timeoutMs: Long) {
        releasePresentationWakeLock()
        presentationWakeLock = powerManager.newWakeLock(
            PowerManager.SCREEN_BRIGHT_WAKE_LOCK or
                PowerManager.ACQUIRE_CAUSES_WAKEUP,
            WAKE_LOCK_TAG,
        ).apply {
            setReferenceCounted(false)
            acquire(timeoutMs)
        }
    }

    private fun releasePresentationWakeLock() {
        presentationWakeLock?.let { wakeLock ->
            if (wakeLock.isHeld) runCatching { wakeLock.release() }
        }
        presentationWakeLock = null
    }

    data class OverlayResult(
        val shown: Boolean,
        val reason: String?,
        val initiallyInteractive: Boolean = false,
        val wakeRequested: Boolean = false,
    )

    companion object {
        private const val DISPLAY_WAKE_CONFIRM_TIMEOUT_MS = 2_500L
        private const val DISPLAY_WAKE_CONFIRM_INTERVAL_MS = 100L
        private const val WAKE_LOCK_MARGIN_MS = 2_000L
        private const val WAKE_LOCK_TAG = "RealGit:Presentation"
        private val PRIMARY_ACTION_KEY_CODES = setOf(
            KeyEvent.KEYCODE_ENTER,
            KeyEvent.KEYCODE_DPAD_CENTER,
            KeyEvent.KEYCODE_SPACE,
        )
    }
}
