package com.realitymemory.glasses.capture

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import com.rokid.os.sprite.record.service.IRecorderService
import com.rokid.os.sprite.record.service.IRecordingCallback
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class RokidSystemRecordingClient(private val context: Context) {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val binding = AtomicBoolean(false)
    private val closed = AtomicBoolean(false)

    @Volatile private var recorder: IRecorderService? = null
    @Volatile private var bound = false
    private var pendingCapture: PendingCapture? = null
    private var pendingTimeout: Runnable? = null
    private var bindingWatchdog: Runnable? = null
    private var reconnectRunnable: Runnable? = null

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            bindingWatchdog?.let(mainHandler::removeCallbacks)
            bindingWatchdog = null
            reconnectRunnable?.let(mainHandler::removeCallbacks)
            reconnectRunnable = null
            recorder = IRecorderService.Stub.asInterface(service)
            bound = true
            binding.set(false)
            mainHandler.post(::startPendingCaptureIfConnected)
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            recorder = null
            bound = false
            binding.set(false)
            scheduleReconnect()
        }

        override fun onBindingDied(name: ComponentName?) {
            recorder = null
            bound = false
            binding.set(false)
            scheduleReconnect(resetBinding = true)
        }

        override fun onNullBinding(name: ComponentName?) {
            recorder = null
            bound = false
            binding.set(false)
            scheduleReconnect(resetBinding = true)
        }
    }

    fun connect(): Boolean {
        if (closed.get()) return false
        if (recorder != null || !binding.compareAndSet(false, true)) return recorder != null
        val intent = Intent(SERVICE_ACTION)
            .setComponent(ComponentName(SERVICE_PACKAGE, SERVICE_CLASS))
        return runCatching {
            context.bindService(intent, connection, Context.BIND_AUTO_CREATE).also { accepted ->
                if (accepted) {
                    scheduleBindingWatchdog()
                } else {
                    binding.set(false)
                    scheduleReconnect()
                }
            }
        }.getOrElse {
            binding.set(false)
            scheduleReconnect()
            false
        }
    }

    fun isConnected(): Boolean = recorder != null

    fun captureCameraVideo(
        outputFile: File,
        durationMs: Long,
        callback: Callback,
    ): Boolean {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            mainHandler.post { captureCameraVideo(outputFile, durationMs, callback) }
            return true
        }
        outputFile.parentFile?.mkdirs()
        outputFile.delete()
        val service = recorder
        if (service == null) {
            if (pendingCapture != null) {
                callback.onError(ERROR_REQUEST_BUSY, "已有录制请求正在等待乐奇系统服务")
                return false
            }
            pendingCapture = PendingCapture(
                outputFile = outputFile,
                durationMs = durationMs,
                callback = callback,
            )
            connect()
            pendingTimeout = Runnable {
                val pending = pendingCapture ?: return@Runnable
                pendingCapture = null
                pendingTimeout = null
                pending.callback.onError(
                    ERROR_SERVICE_UNAVAILABLE,
                    "等待乐奇系统录制服务连接超时（${WAIT_FOR_SERVICE_TIMEOUT_MS}毫秒）",
                )
                scheduleReconnect(resetBinding = true)
            }.also {
                mainHandler.postDelayed(it, WAIT_FOR_SERVICE_TIMEOUT_MS)
            }
            startPendingCaptureIfConnected()
            return true
        }
        return startRecording(service, outputFile, durationMs, callback)
    }

    private fun startPendingCaptureIfConnected() {
        val service = recorder ?: return
        val pending = pendingCapture ?: return
        pendingCapture = null
        pendingTimeout?.let(mainHandler::removeCallbacks)
        pendingTimeout = null
        startRecording(
            service = service,
            outputFile = pending.outputFile,
            durationMs = pending.durationMs,
            callback = pending.callback,
        )
    }

    private fun startRecording(
        service: IRecorderService,
        outputFile: File,
        durationMs: Long,
        callback: Callback,
    ): Boolean {
        val config = Bundle().apply {
            putInt("type", TYPE_CAMERA)
            // The RV101 service forwards height before width to MediaRecorder.setVideoSize.
            putInt("width", REQUEST_HEIGHT)
            putInt("height", REQUEST_WIDTH)
            putInt("durationMs", durationMs.coerceIn(1_000L, MAX_DURATION_MS).toInt())
            putInt("fps", REQUEST_FPS)
            putString("outputPath", outputFile.absolutePath)
        }
        val serviceCallback = object : IRecordingCallback.Stub() {
            override fun onStarted(type: Int, path: String?) {
                mainHandler.post { callback.onStarted(path ?: outputFile.absolutePath) }
            }

            override fun onCompleted(
                type: Int,
                path: String?,
                success: Boolean,
                message: String?,
            ) {
                mainHandler.post {
                    callback.onCompleted(
                        File(path?.takeIf(String::isNotBlank) ?: outputFile.absolutePath),
                        success,
                        message,
                    )
                }
            }

            override fun onError(type: Int, errorCode: Int, message: String?) {
                mainHandler.post {
                    callback.onError(errorCode, message ?: "乐奇系统录制服务返回未知错误")
                }
            }
        }
        return runCatching {
            service.startRecording(config, serviceCallback).also { accepted ->
                if (!accepted) {
                    callback.onError(ERROR_START_REJECTED, "乐奇系统录制服务拒绝了本次请求")
                }
            }
        }.getOrElse { error ->
            callback.onError(ERROR_BINDER_CALL, "${error.javaClass.simpleName}: ${error.message}")
            false
        }
    }

    fun stopCameraRecording() {
        runCatching { recorder?.stopRecording(TYPE_CAMERA) }
    }

    fun shutdown() {
        closed.set(true)
        pendingTimeout?.let(mainHandler::removeCallbacks)
        pendingTimeout = null
        bindingWatchdog?.let(mainHandler::removeCallbacks)
        bindingWatchdog = null
        reconnectRunnable?.let(mainHandler::removeCallbacks)
        reconnectRunnable = null
        pendingCapture?.callback?.onError(
            ERROR_SERVICE_UNAVAILABLE,
            "应用已停止，等待中的录制请求已取消",
        )
        pendingCapture = null
        if (bound || binding.get()) {
            runCatching { context.unbindService(connection) }
        }
        recorder = null
        bound = false
        binding.set(false)
    }

    private fun scheduleBindingWatchdog() {
        bindingWatchdog?.let(mainHandler::removeCallbacks)
        bindingWatchdog = Runnable {
            bindingWatchdog = null
            if (recorder == null && binding.get()) {
                scheduleReconnect(resetBinding = true)
            }
        }.also {
            mainHandler.postDelayed(it, BINDING_WATCHDOG_MS)
        }
    }

    private fun scheduleReconnect(resetBinding: Boolean = false) {
        if (closed.get()) return
        if (resetBinding) {
            runCatching { context.unbindService(connection) }
            recorder = null
            bound = false
            binding.set(false)
        }
        if (reconnectRunnable != null) return
        reconnectRunnable = Runnable {
            reconnectRunnable = null
            if (!closed.get() && recorder == null) {
                connect()
            }
        }.also {
            mainHandler.postDelayed(it, RECONNECT_DELAY_MS)
        }
    }

    interface Callback {
        fun onStarted(path: String)
        fun onCompleted(file: File, success: Boolean, message: String?)
        fun onError(errorCode: Int, message: String)
    }

    private data class PendingCapture(
        val outputFile: File,
        val durationMs: Long,
        val callback: Callback,
    )

    companion object {
        private const val SERVICE_ACTION =
            "com.rokid.os.sprite.record.action.RECORDING_SERVICE"
        private const val SERVICE_PACKAGE = "com.rokid.os.sprite.record"
        private const val SERVICE_CLASS =
            "com.rokid.os.sprite.record.service.RecordingService"
        private const val TYPE_CAMERA = 1
        private const val REQUEST_WIDTH = 1280
        private const val REQUEST_HEIGHT = 720
        private const val REQUEST_FPS = 30
        private const val MAX_DURATION_MS = 30_000L
        private const val WAIT_FOR_SERVICE_TIMEOUT_MS = 3_000L
        private const val BINDING_WATCHDOG_MS = 3_000L
        private const val RECONNECT_DELAY_MS = 1_000L
        private const val ERROR_SERVICE_UNAVAILABLE = 2001
        private const val ERROR_START_REJECTED = 2002
        private const val ERROR_BINDER_CALL = 2003
        private const val ERROR_REQUEST_BUSY = 2004
    }
}
