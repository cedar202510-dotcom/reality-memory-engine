package com.realitymemory.glasses.interaction

import android.content.Context
import android.graphics.PixelFormat
import android.provider.Settings
import android.view.Gravity
import android.view.WindowManager
import com.realitymemory.glasses.runtime.RuntimeStatus
import com.realitymemory.glasses.ui.GlassesUiView

/**
 * 在后台 Runtime 收到用户可见消息时短暂呈现透明 HUD。
 *
 * 普通后台服务不能可靠拉起 Activity；RV101 Debug 联调通过 SYSTEM_ALERT_WINDOW
 * 验证这条路径。正式分发仍需用户授权或 Rokid 系统白名单。
 */
class GlassesOverlayPresenter(context: Context) {
    private val appContext = context.applicationContext
    private val windowManager = appContext.getSystemService(WindowManager::class.java)
    private var activeView: GlassesUiView? = null

    fun show(
        status: RuntimeStatus,
        onVisible: () -> Unit,
    ): OverlayResult {
        if (!Settings.canDrawOverlays(appContext)) {
            return OverlayResult(
                shown = false,
                reason = "SYSTEM_ALERT_WINDOW_NOT_GRANTED",
            )
        }
        dismiss()
        val view = GlassesUiView(appContext, transparentBackground = true).apply {
            render(status)
        }
        val parameters = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.FILL
            title = "RealGitPresentation"
        }
        return runCatching {
            windowManager.addView(view, parameters)
            activeView = view
            view.post {
                if (activeView === view && view.isAttachedToWindow) {
                    onVisible()
                }
            }
            OverlayResult(shown = true, reason = null)
        }.getOrElse { error ->
            activeView = null
            OverlayResult(
                shown = false,
                reason = "${error.javaClass.simpleName}: ${error.message}",
            )
        }
    }

    fun dismiss() {
        val view = activeView ?: return
        activeView = null
        runCatching { windowManager.removeViewImmediate(view) }
    }

    data class OverlayResult(
        val shown: Boolean,
        val reason: String?,
    )
}
