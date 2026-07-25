package com.realitymemory.glasses

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.realitymemory.glasses.runtime.RealityRuntimeService
import com.realitymemory.glasses.runtime.RuntimeDisplayKind
import com.realitymemory.glasses.runtime.RuntimeStatus
import com.realitymemory.glasses.runtime.RuntimeStatusStore
import com.realitymemory.glasses.runtime.SessionState
import com.realitymemory.glasses.ui.GlassesUiView

class MainActivity : ComponentActivity() {
    private lateinit var glassesUi: GlassesUiView
    private var currentStatus = RuntimeStatus(
        state = SessionState.ARMED,
        message = "",
        lastEvidence = null,
        displayKind = RuntimeDisplayKind.NONE,
    )
    private var transientDisplayShown = false
    private var visualShellClosing = false
    private var lastReportedPresentationId: String? = null

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) {
        if (hasPermissions()) {
            startRuntimeAndOptionalPreview()
        } else {
            glassesUi.render(
                RuntimeStatus(
                    state = SessionState.BLOCKED,
                    message = "需要相机和麦克风权限",
                    lastEvidence = null,
                    displayKind = RuntimeDisplayKind.BLOCKED,
                ),
            )
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
                ACTION_SPRITE_BUTTON_CLICK -> handleSingleClick()
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
            startRuntimeAndOptionalPreview()
        } else {
            permissionLauncher.launch(requiredPermissions())
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        refresh()
        maybeShowDebugReminder()
        maybeHandleDebugCommand()
        maybeReportWearDisclosureVisible()
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
                handleSingleClick()
                true
            }
            KeyEvent.KEYCODE_PROG_BLUE -> {
                rememberNow()
                true
            }
            KeyEvent.KEYCODE_BACK -> {
                cancelCurrentSession()
                true
            }
            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun buildUi() {
        glassesUi = GlassesUiView(this).apply {
            setOnClickListener { handleSingleClick() }
        }
        setContentView(glassesUi)
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

    private fun startRuntimeAndOptionalPreview() {
        if (!isAuxiliaryLaunch()) {
            sendRuntimeAction(
                RealityRuntimeService.ACTION_START_EXPLICIT,
                startReason = intent?.getStringExtra(EXTRA_START_REASON),
            )
        }
        maybeShowDebugReminder()
        maybeHandleDebugCommand()
        maybeReportWearDisclosureVisible()
    }

    private fun isAuxiliaryLaunch(): Boolean =
        intent?.getBooleanExtra(EXTRA_OPENED_FROM_WEAR, false) == true ||
            intent?.getBooleanExtra(EXTRA_OPENED_FROM_PRESENTATION, false) == true ||
            hasPendingDebugCommand()

    private fun maybeReportWearDisclosureVisible() {
        if (intent?.getBooleanExtra(EXTRA_OPENED_FROM_WEAR, false) != true) return
        intent?.removeExtra(EXTRA_OPENED_FROM_WEAR)
        sendRuntimeAction(RealityRuntimeService.ACTION_REPORT_WEAR_DISCLOSURE_VISIBLE)
    }

    private fun maybeShowDebugReminder() {
        if (!BuildConfig.DEBUG) return
        val reminder = intent?.getStringExtra(EXTRA_DEBUG_REMINDER_TEXT) ?: return
        intent?.removeExtra(EXTRA_DEBUG_REMINDER_TEXT)
        glassesUi.postDelayed(
            {
                sendRuntimeAction(RealityRuntimeService.ACTION_TEST_REMINDER, reminder)
            },
            DEBUG_REMINDER_DELAY_MS,
        )
    }

    private fun maybeHandleDebugCommand() {
        if (!BuildConfig.DEBUG) return
        when (intent?.getStringExtra(EXTRA_DEBUG_COMMAND)) {
            DEBUG_COMMAND_REMEMBER_NOW -> rememberNow()
            DEBUG_COMMAND_SYSTEM_VIDEO ->
                sendRuntimeAction(RealityRuntimeService.ACTION_TEST_SYSTEM_VIDEO)
            DEBUG_COMMAND_HEART_RATE_START ->
                sendRuntimeAction(RealityRuntimeService.ACTION_START_HEART_RATE_BROADCAST_POC)
            DEBUG_COMMAND_HEART_RATE_STOP ->
                sendRuntimeAction(RealityRuntimeService.ACTION_STOP_HEART_RATE_BROADCAST_POC)
            DEBUG_COMMAND_END_SESSION -> cancelCurrentSession()
        }
        intent?.removeExtra(EXTRA_DEBUG_COMMAND)
    }

    private fun hasPendingDebugCommand(): Boolean =
        intent?.hasExtra(EXTRA_DEBUG_REMINDER_TEXT) == true ||
            intent?.hasExtra(EXTRA_DEBUG_COMMAND) == true

    private fun refresh() {
        currentStatus = RuntimeStatusStore.read(this)
        if (currentStatus.displayKind != RuntimeDisplayKind.NONE) {
            transientDisplayShown = true
        }
        if (currentStatus.displayKind != RuntimeDisplayKind.PRESENTATION) {
            lastReportedPresentationId = null
        }
        glassesUi.render(currentStatus)
        currentStatus.presentation?.messageId
            ?.takeIf {
                currentStatus.displayKind == RuntimeDisplayKind.PRESENTATION &&
                    it != lastReportedPresentationId
            }
            ?.let { messageId ->
                lastReportedPresentationId = messageId
                sendRuntimeAction(
                    RealityRuntimeService.ACTION_REPORT_PRESENTATION_VISIBLE,
                    messageId = messageId,
                )
            }
        if (
            transientDisplayShown &&
            currentStatus.displayKind == RuntimeDisplayKind.NONE
        ) {
            closeVisualShell()
        }
    }

    private fun closeVisualShell() {
        if (visualShellClosing || isFinishing || isDestroyed) return
        visualShellClosing = true
        glassesUi.post {
            if (!isFinishing && !isDestroyed) {
                finishAndRemoveTask()
            }
        }
    }

    private fun handleSingleClick() {
        when (currentStatus.displayKind) {
            RuntimeDisplayKind.REMINDER ->
                sendRuntimeAction(RealityRuntimeService.ACTION_DISMISS_REMINDER)
            RuntimeDisplayKind.PRESENTATION ->
                sendRuntimeAction(
                    RealityRuntimeService.ACTION_DISMISS_PRESENTATION,
                    messageId = currentStatus.presentation?.messageId,
                )
            else -> cancelCurrentSession()
        }
    }

    private fun rememberNow() {
        sendRuntimeAction(RealityRuntimeService.ACTION_REMEMBER_NOW)
    }

    private fun cancelCurrentSession() {
        sendRuntimeAction(RealityRuntimeService.ACTION_END_SESSION)
        glassesUi.postDelayed(
            { finishAndRemoveTask() },
            CANCELLED_DISPLAY_MS,
        )
    }

    private fun sendRuntimeAction(
        action: String,
        reminderText: String? = null,
        startReason: String? = null,
        messageId: String? = null,
    ) {
        val serviceIntent = Intent(this, RealityRuntimeService::class.java).setAction(action)
        if (reminderText != null) {
            serviceIntent.putExtra(RealityRuntimeService.EXTRA_REMINDER_TEXT, reminderText)
        }
        if (startReason != null) {
            serviceIntent.putExtra(RealityRuntimeService.EXTRA_START_REASON, startReason)
        }
        if (messageId != null) {
            serviceIntent.putExtra(RealityRuntimeService.EXTRA_MESSAGE_ID, messageId)
        }
        ContextCompat.startForegroundService(this, serviceIntent)
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

    companion object {
        const val EXTRA_OPENED_FROM_WEAR = "opened_from_wear"
        const val EXTRA_OPENED_FROM_PRESENTATION = "opened_from_presentation"
        const val EXTRA_DEBUG_REMINDER_TEXT = "debug_reminder_text"
        const val EXTRA_DEBUG_COMMAND = "rme_debug_command"
        const val EXTRA_START_REASON = "rme_start_reason"

        private const val ACTION_SPRITE_BUTTON_CLICK =
            "com.android.action.ACTION_SPRITE_BUTTON_CLICK"
        private const val ACTION_AI_START = "com.android.action.ACTION_AI_START"
        private const val DEBUG_COMMAND_REMEMBER_NOW = "remember_now"
        private const val DEBUG_COMMAND_SYSTEM_VIDEO = "system_video"
        private const val DEBUG_COMMAND_HEART_RATE_START = "heart_rate_start"
        private const val DEBUG_COMMAND_HEART_RATE_STOP = "heart_rate_stop"
        private const val DEBUG_COMMAND_END_SESSION = "end_session"
        private const val DEBUG_REMINDER_DELAY_MS = 400L
        private const val CANCELLED_DISPLAY_MS = 3_000L
    }
}
