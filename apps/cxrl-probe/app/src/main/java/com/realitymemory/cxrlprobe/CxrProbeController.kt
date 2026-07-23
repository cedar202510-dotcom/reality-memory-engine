package com.realitymemory.cxrlprobe

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.util.Log
import com.rokid.cxr.link.CXRLink
import com.rokid.cxr.link.callbacks.ICXRLinkCbk
import com.rokid.cxr.link.callbacks.ICustomViewCbk
import com.rokid.cxr.link.callbacks.IImageStreamCbk
import com.rokid.cxr.link.utils.CxrDefs
import com.rokid.cxr.link.utils.GlassInfo
import com.rokid.sprite.aiapp.externalapp.auth.AuthResult
import com.rokid.sprite.aiapp.externalapp.auth.AuthorizationHelper
import com.rokid.sprite.aiapp.externalapp.auth.GlassPermission
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

class CxrProbeController(context: Context) {
    companion object {
        const val REQUEST_CODE_AUTH = 7001
        private const val TAG = "RealityCxrLProbe"

        private val CUSTOM_VIEW_JSON = """
            {
              "type": "LinearLayout",
              "props": {
                "id": "root",
                "layout_width": "match_parent",
                "layout_height": "match_parent",
                "orientation": "vertical",
                "gravity": "center",
                "backgroundColor": "#000000"
              },
              "children": [
                {
                  "type": "TextView",
                  "props": {
                    "id": "status_text",
                    "layout_width": "wrap_content",
                    "layout_height": "wrap_content",
                    "text": "Reality Memory capture is active",
                    "textColor": "#00FF00",
                    "textSize": "16sp",
                    "gravity": "center"
                  }
                }
              ]
            }
        """.trimIndent()
    }

    private val appContext = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val logFile = File(appContext.filesDir, "probe-events.jsonl")
    private val _state = MutableStateFlow(ProbeState())
    val state: StateFlow<ProbeState> = _state.asStateFlow()

    private var authorizationToken = ""
    private var link: CXRLink? = null
    private var customViewOpening = false
    private var captureJob: Job? = null
    private var pendingCaptureTrigger = "manual"

    private val linkCallback = object : ICXRLinkCbk {
        override fun onCXRLConnected(connected: Boolean) {
            update("CXR link: $connected") {
                it.copy(cxrConnected = connected, status = linkStatus(connected, it.glassBluetoothConnected))
            }
            maybeOpenCustomView()
        }

        override fun onGlassBtConnected(connected: Boolean) {
            update("Glasses Bluetooth: $connected") {
                it.copy(
                    glassBluetoothConnected = connected,
                    status = linkStatus(it.cxrConnected, connected)
                )
            }
            maybeOpenCustomView()
        }

        override fun onGlassAiAssistStart() {
            event("Rokid AI assistant started")
        }

        override fun onGlassAiAssistStop() {
            event("Rokid AI assistant stopped")
        }

        override fun onGlassAiInterrupt(interruptWake: Boolean) {
            event("Rokid AI interrupt: $interruptWake")
        }

        override fun onGlassDeviceInfo(deviceInfo: GlassInfo) {
            event("Device info received: brightness=${deviceInfo.brightness}, volume=${deviceInfo.sound}")
        }

        override fun onGlassWearingStatus(wearing: Boolean) {
            update("Wearing status: $wearing") {
                it.copy(wearing = wearing)
            }
        }
    }

    private val customViewCallback = object : ICustomViewCbk {
        override fun onCustomViewOpened() {
            customViewOpening = false
            update("CustomView opened; capture APIs are ready") {
                it.copy(customViewOpened = true, status = "Ready to capture")
            }
        }

        override fun onCustomViewUpdated() {
            event("CustomView updated")
        }

        override fun onCustomViewClosed() {
            customViewOpening = false
            update("CustomView closed") {
                it.copy(customViewOpened = false, status = "CustomView is closed")
            }
        }

        override fun onCustomViewIconsSent() {
            event("CustomView icons sent")
        }

        override fun onCustomViewError(code: Int, msg: String?) {
            customViewOpening = false
            update("CustomView error: $code ${msg.orEmpty()}") {
                it.copy(customViewOpened = false, status = "CustomView failed: $code")
            }
        }
    }

    private val imageCallback = object : IImageStreamCbk {
        override fun onImageReceived(data: ByteArray?) {
            if (data == null || data.isEmpty()) {
                onImageError(-1, "Empty image")
                return
            }

            val trigger = pendingCaptureTrigger
            val capturedAt = Instant.now().toString()
            update("Image received: ${data.size} bytes") {
                it.copy(
                    takingPhoto = false,
                    captureCount = it.captureCount + 1,
                    lastImageBytes = data,
                    lastCaptureSummary = "$capturedAt | ${data.size} bytes | $trigger",
                    status = "Capture received"
                )
            }
            scope.launch(Dispatchers.IO) {
                appendObservation(capturedAt, trigger, data)
            }
        }

        override fun onImageError(code: Int, msg: String?) {
            update("Image error: $code ${msg.orEmpty()}") {
                it.copy(takingPhoto = false, status = "Capture failed: $code")
            }
        }
    }

    fun inspectCompanionApp(activity: Activity) {
        val installed = AuthorizationHelper.isRequiredRokidAppInstalled(activity) ||
            AuthorizationHelper.isRequiredHiRokidInstalled(activity)
        update(if (installed) "Rokid companion app found" else "Rokid companion app missing") {
            it.copy(
                companionInstalled = installed,
                status = if (installed) "Companion app found; request authorization" else
                    "Install Rokid AI App 1.9.0 or newer"
            )
        }
    }

    fun requestAuthorization(activity: Activity) {
        if (!_state.value.companionInstalled) {
            inspectCompanionApp(activity)
        }
        val historicalResult = AuthorizationHelper.requestAuthorization(
            activity,
            arrayOf(GlassPermission.CAMERA, GlassPermission.MICROPHONE, GlassPermission.MEDIA),
            REQUEST_CODE_AUTH
        )
        if (historicalResult != null) {
            parseAuthorizationResult(historicalResult.first, historicalResult.second)
        } else {
            update("Waiting for Rokid authorization UI") {
                it.copy(status = "Complete authorization in Rokid AI App")
            }
        }
    }

    fun parseAuthorizationResult(resultCode: Int, data: Intent?) {
        when (val result = AuthorizationHelper.parseAuthorizationResult(resultCode, data)) {
            is AuthResult.AuthSuccess -> {
                authorizationToken = result.token
                val authenticated = authorizationToken.isNotBlank()
                update(if (authenticated) "Authorization succeeded" else "Authorization returned an empty token") {
                    it.copy(
                        authenticated = authenticated,
                        status = if (authenticated) "Authorized; connect to glasses" else
                            "Authorization failed"
                    )
                }
            }

            is AuthResult.AuthFail -> {
                authorizationToken = ""
                update("Authorization failed") {
                    it.copy(authenticated = false, status = "Authorization failed")
                }
            }

            is AuthResult.AuthCancel -> {
                authorizationToken = ""
                update("Authorization cancelled") {
                    it.copy(authenticated = false, status = "Authorization cancelled")
                }
            }
        }
    }

    fun connect() {
        if (authorizationToken.isBlank()) {
            update("Connect blocked: no runtime token") {
                it.copy(status = "Request authorization first")
            }
            return
        }
        if (link != null) {
            event("Connection already created; reusing the singleton CXRLink")
            maybeOpenCustomView()
            return
        }

        val newLink = CXRLink(appContext).apply {
            configCXRSession(CxrDefs.CXRSession(CxrDefs.CXRSessionType.CUSTOMVIEW))
            setCXRLinkCbk(linkCallback)
            setCXRCustomViewCbk(customViewCallback)
            setCXRImageCbk(imageCallback)
        }
        link = newLink
        update("Connecting with the runtime authorization token") {
            it.copy(status = "Waiting for CXR and Bluetooth links")
        }
        if (!newLink.connect(authorizationToken)) {
            update("CXRLink.connect returned false") {
                it.copy(status = "Connection request was rejected")
            }
        }
    }

    fun takePhoto(trigger: String = "manual") {
        val current = _state.value
        if (!current.captureReady) {
            update("Capture blocked: session not ready") {
                it.copy(status = "Wait for both links and CustomView")
            }
            return
        }
        if (!AuthorizationHelper.hasGlassPermission(GlassPermission.CAMERA)) {
            update("Capture blocked: camera permission missing") {
                it.copy(status = "Re-authorize camera permission")
            }
            return
        }

        pendingCaptureTrigger = trigger
        update("Capture requested: $trigger") {
            it.copy(takingPhoto = true, status = "Taking photo")
        }
        val accepted = link?.takePhoto(1024, 768, 80) == true
        if (!accepted) {
            update("takePhoto returned false") {
                it.copy(takingPhoto = false, status = "Capture request was rejected")
            }
        }
    }

    fun startScheduledCapture() {
        if (captureJob?.isActive == true) return
        update("30-second capture loop started") {
            it.copy(scheduledCaptureEnabled = true)
        }
        captureJob = scope.launch {
            while (isActive) {
                val current = _state.value
                when {
                    current.wearing == false -> event("Scheduled capture skipped: glasses not worn")
                    current.captureReady -> takePhoto("timer")
                    else -> event("Scheduled capture waiting for a ready session")
                }
                delay(current.captureIntervalSeconds * 1_000L)
            }
        }
    }

    fun stopScheduledCapture() {
        captureJob?.cancel()
        captureJob = null
        update("Scheduled capture stopped") {
            it.copy(scheduledCaptureEnabled = false)
        }
    }

    fun disconnect() {
        stopScheduledCapture()
        val currentLink = link
        if (_state.value.customViewOpened) {
            runCatching { currentLink?.customViewClose() }
        }
        runCatching { currentLink?.disconnect() }
        link = null
        customViewOpening = false
        update("Disconnected") {
            it.copy(
                cxrConnected = false,
                glassBluetoothConnected = false,
                customViewOpened = false,
                wearing = null,
                takingPhoto = false,
                status = "Disconnected"
            )
        }
    }

    private fun maybeOpenCustomView() {
        val current = _state.value
        if (!current.linkReady || current.customViewOpened || customViewOpening) return
        customViewOpening = true
        update("Both links ready; opening CustomView") {
            it.copy(status = "Opening CustomView on glasses")
        }
        val accepted = runCatching { link?.customViewOpen(CUSTOM_VIEW_JSON) == true }
            .getOrElse {
                Log.e(TAG, "customViewOpen failed", it)
                false
            }
        if (!accepted) {
            customViewOpening = false
            update("customViewOpen returned false") {
                it.copy(status = "CustomView open request failed")
            }
        }
    }

    private fun appendObservation(capturedAt: String, trigger: String, image: ByteArray) {
        val digest = MessageDigest.getInstance("SHA-256").digest(image)
            .joinToString("") { "%02x".format(it) }
        val event = JSONObject()
            .put("schema_version", "0.1")
            .put("observation_id", UUID.randomUUID().toString())
            .put("captured_at", capturedAt)
            .put("source", "rokid_cxrl_photo")
            .put("trigger", trigger)
            .put("image_bytes", image.size)
            .put("image_sha256", digest)
            .put("image_persisted", false)
            .put("wearing", _state.value.wearing ?: JSONObject.NULL)
        logFile.appendText(event.toString() + "\n")
    }

    private fun linkStatus(cxr: Boolean, bluetooth: Boolean): String = when {
        cxr && bluetooth -> "Both links ready; opening CustomView"
        cxr -> "CXR ready; waiting for glasses Bluetooth"
        bluetooth -> "Bluetooth ready; waiting for CXR"
        else -> "Waiting for CXR and Bluetooth links"
    }

    private fun event(message: String) {
        update(message) { it }
    }

    private inline fun update(message: String, transform: (ProbeState) -> ProbeState) {
        Log.i(TAG, message)
        _state.value = transform(_state.value).let {
            it.copy(recentEvents = (listOf("${Instant.now()}  $message") + it.recentEvents).take(12))
        }
    }
}
