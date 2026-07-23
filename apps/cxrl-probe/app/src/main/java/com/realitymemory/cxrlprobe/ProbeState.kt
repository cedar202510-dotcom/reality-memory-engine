package com.realitymemory.cxrlprobe

data class ProbeState(
    val companionInstalled: Boolean = false,
    val authenticated: Boolean = false,
    val cxrConnected: Boolean = false,
    val glassBluetoothConnected: Boolean = false,
    val customViewOpened: Boolean = false,
    val wearing: Boolean? = null,
    val takingPhoto: Boolean = false,
    val scheduledCaptureEnabled: Boolean = false,
    val captureIntervalSeconds: Int = 30,
    val captureCount: Int = 0,
    val lastImageBytes: ByteArray? = null,
    val lastCaptureSummary: String = "No capture yet",
    val status: String = "Check the Rokid companion app first",
    val recentEvents: List<String> = emptyList()
) {
    val linkReady: Boolean
        get() = cxrConnected && glassBluetoothConnected

    val captureReady: Boolean
        get() = authenticated && linkReady && customViewOpened && !takingPhoto
}
