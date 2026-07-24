package com.realitymemory.glasses

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.realitymemory.glasses.runtime.RealityRuntimeService
import com.realitymemory.glasses.runtime.RuntimeStatusStore
import com.realitymemory.glasses.runtime.SessionState

class MainActivity : ComponentActivity() {
    private lateinit var stateView: TextView
    private lateinit var messageView: TextView
    private lateinit var primaryButton: Button

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) {
        if (hasPermissions()) {
            sendRuntimeAction(RealityRuntimeService.ACTION_START_EXPLICIT)
        } else {
            render(SessionState.BLOCKED, "需要相机和麦克风权限", null)
        }
    }

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            refresh()
        }
    }

    private val glassesInputReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                ACTION_SPRITE_BUTTON_CLICK -> togglePause()
                ACTION_AI_START -> rememberNow()
            }
            if (isOrderedBroadcast) abortBroadcast()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        buildUi()
        registerReceivers()
        refresh()
        if (hasPermissions()) {
            sendRuntimeAction(RealityRuntimeService.ACTION_START_EXPLICIT)
        } else {
            permissionLauncher.launch(requiredPermissions())
        }
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(statusReceiver) }
        runCatching { unregisterReceiver(glassesInputReceiver) }
        super.onDestroy()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_ENTER,
            KeyEvent.KEYCODE_BACK,
            KeyEvent.KEYCODE_PROG_BLUE,
            -> true
            else -> super.onKeyDown(keyCode, event)
        }
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (event?.repeatCount != 0) return super.onKeyUp(keyCode, event)
        return when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> {
                togglePause()
                true
            }
            KeyEvent.KEYCODE_PROG_BLUE -> {
                rememberNow()
                true
            }
            KeyEvent.KEYCODE_BACK -> {
                endSession()
                true
            }
            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun buildUi() {
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(28), dp(22), dp(28), dp(18))
        }
        root.addView(
            content,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(480),
            ).apply {
                gravity = Gravity.TOP
                topMargin = dp(80)
            },
        )

        content.addView(
            text("REALITY MEMORY", 13f, COLOR_MUTED).apply {
                typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            },
            linearMatchWrap(),
        )
        stateView = text("准备中", 34f, Color.WHITE).apply {
            gravity = Gravity.CENTER
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            setPadding(0, dp(28), 0, dp(12))
        }
        content.addView(stateView, linearMatchWrap())

        messageView = text("", 17f, COLOR_MUTED).apply {
            gravity = Gravity.CENTER
            setLineSpacing(dp(4).toFloat(), 1f)
            maxLines = 3
        }
        content.addView(
            messageView,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f,
            ),
        )

        primaryButton = actionButton("暂停").apply { setOnClickListener { togglePause() } }
        content.addView(primaryButton, linearMatchWrap(dp(8)))

        val actions = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        actions.addView(
            actionButton("记一下", secondary = true).apply { setOnClickListener { rememberNow() } },
            LinearLayout.LayoutParams(0, dp(48), 1f).apply { marginEnd = dp(6) },
        )
        actions.addView(
            actionButton("本次关闭", secondary = true).apply { setOnClickListener { endSession() } },
            LinearLayout.LayoutParams(0, dp(48), 1f).apply { marginStart = dp(6) },
        )
        content.addView(actions, linearMatchWrap(dp(8)))

        val testReminder = actionButton("测试提醒", secondary = true).apply {
            visibility = if (BuildConfig.DEBUG) View.VISIBLE else View.GONE
            setOnClickListener {
                sendRuntimeAction(
                    RealityRuntimeService.ACTION_TEST_REMINDER,
                    "提醒：出门前别忘了带上刚才放在桌边的钥匙。",
                )
            }
        }
        content.addView(testReminder, linearMatchWrap(dp(8)))
        setContentView(root)
    }

    private fun registerReceivers() {
        ContextCompat.registerReceiver(
            this,
            statusReceiver,
            IntentFilter(RuntimeStatusStore.ACTION_STATUS_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        val keyFilter = IntentFilter().apply {
            priority = IntentFilter.SYSTEM_HIGH_PRIORITY
            addAction(ACTION_SPRITE_BUTTON_CLICK)
            addAction(ACTION_AI_START)
        }
        ContextCompat.registerReceiver(
            this,
            glassesInputReceiver,
            keyFilter,
            ContextCompat.RECEIVER_EXPORTED,
        )
    }

    private fun refresh() {
        val (state, message, lastEvidence) = RuntimeStatusStore.read(this)
        render(state, message, lastEvidence)
    }

    private fun render(state: SessionState, message: String, lastEvidence: String?) {
        stateView.text = when (state) {
            SessionState.ARMED -> "等待佩戴"
            SessionState.DISCLOSURE -> "准备开始"
            SessionState.ACTIVE -> "正在留意"
            SessionState.PAUSED -> "已暂停"
            SessionState.BLOCKED -> "暂未开始"
            SessionState.ENDED -> "本次结束"
        }
        stateView.setTextColor(
            when (state) {
                SessionState.ACTIVE -> COLOR_ACCENT
                SessionState.DISCLOSURE -> COLOR_NOTICE
                SessionState.PAUSED, SessionState.BLOCKED -> COLOR_WARNING
                else -> Color.WHITE
            },
        )
        messageView.text = buildString {
            append(message)
            if (BuildConfig.DEBUG && lastEvidence != null) {
                append("\n调试窗口：")
                append(lastEvidence.takeLast(12))
            }
        }
        primaryButton.text = when (state) {
            SessionState.PAUSED -> "继续"
            SessionState.ENDED, SessionState.ARMED, SessionState.BLOCKED -> "开始本次"
            SessionState.DISCLOSURE -> "本次关闭"
            else -> "暂停"
        }
    }

    private fun togglePause() {
        sendRuntimeAction(RealityRuntimeService.ACTION_TOGGLE_PAUSE)
    }

    private fun rememberNow() {
        sendRuntimeAction(RealityRuntimeService.ACTION_REMEMBER_NOW)
    }

    private fun endSession() {
        sendRuntimeAction(RealityRuntimeService.ACTION_END_SESSION)
    }

    private fun sendRuntimeAction(action: String, reminderText: String? = null) {
        val intent = Intent(this, RealityRuntimeService::class.java).setAction(action)
        if (reminderText != null) {
            intent.putExtra(RealityRuntimeService.EXTRA_REMINDER_TEXT, reminderText)
        }
        ContextCompat.startForegroundService(this, intent)
    }

    private fun hasPermissions(): Boolean =
        requiredPermissions().all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }

    private fun requiredPermissions(): Array<String> = buildList {
        add(Manifest.permission.CAMERA)
        add(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            add(Manifest.permission.POST_NOTIFICATIONS)
        }
    }.toTypedArray()

    private fun actionButton(label: String, secondary: Boolean = false): Button =
        Button(this).apply {
            text = label
            textSize = 16f
            isAllCaps = false
            setTextColor(if (secondary) Color.WHITE else Color.BLACK)
            background = GradientDrawable().apply {
                cornerRadius = dp(6).toFloat()
                setColor(if (secondary) COLOR_SURFACE else COLOR_ACCENT)
                if (secondary) setStroke(dp(1), COLOR_BORDER)
            }
        }

    private fun text(value: String, size: Float, color: Int) = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
        letterSpacing = 0f
    }

    private fun linearMatchWrap(topMargin: Int = 0) = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { this.topMargin = topMargin }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        const val EXTRA_OPENED_FROM_WEAR = "opened_from_wear"
        private const val ACTION_SPRITE_BUTTON_CLICK =
            "com.android.action.ACTION_SPRITE_BUTTON_CLICK"
        private const val ACTION_AI_START = "com.android.action.ACTION_AI_START"

        private val COLOR_ACCENT = Color.rgb(108, 245, 178)
        private val COLOR_NOTICE = Color.rgb(255, 210, 95)
        private val COLOR_WARNING = Color.rgb(255, 128, 112)
        private val COLOR_MUTED = Color.rgb(190, 198, 196)
        private val COLOR_SURFACE = Color.rgb(27, 31, 31)
        private val COLOR_BORDER = Color.rgb(75, 84, 82)
    }
}
