package com.realitymemory.glasses.wearable

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import androidx.core.content.ContextCompat
import java.time.Instant
import java.util.Locale
import java.util.UUID

data class HeartRateBroadcastSample(
    val bpm: Int,
    val peripheralName: String?,
    val peripheralAddress: String,
    val rssi: Int?,
    val capturedAt: Instant,
    val monotonicNs: Long,
    val rawHex: String,
)

class HeartRateBroadcastCollector(
    private val context: Context,
    private val onSample: (HeartRateBroadcastSample) -> Unit,
    private val onStatus: (String) -> Unit,
) {
    private val handler = Handler(Looper.getMainLooper())
    private val bluetoothManager = context.getSystemService(BluetoothManager::class.java)

    private var scanner: BluetoothLeScanner? = null
    private var gatt: BluetoothGatt? = null
    private var active = false
    private var currentRssi: Int? = null

    private val scanCallback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            if (!active || !hasBlePermissions()) return
            stopScan()
            currentRssi = result.rssi
            val name = result.scanRecord?.deviceName ?: result.device.name
            onStatus("已发现心率广播设备：${name ?: result.device.address}")
            gatt?.close()
            gatt = result.device.connectGatt(
                context,
                false,
                gattCallback,
                android.bluetooth.BluetoothDevice.TRANSPORT_LE,
            )
        }

        override fun onScanFailed(errorCode: Int) {
            onStatus("心率广播扫描失败：$errorCode")
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            if (!active || !hasBlePermissions()) return
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    onStatus("已连接心率广播设备，正在发现服务")
                    gatt.discoverServices()
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    onStatus("心率广播连接断开，准备重新扫描")
                    closeGatt()
                    scheduleRescan()
                }
            }
        }

        @SuppressLint("MissingPermission")
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (!active || !hasBlePermissions()) return
            val service = gatt.getService(HEART_RATE_SERVICE_UUID)
            val characteristic = service?.getCharacteristic(HEART_RATE_MEASUREMENT_UUID)
            if (characteristic == null) {
                onStatus("设备没有标准 BLE 心率测量特征")
                closeGatt()
                scheduleRescan()
                return
            }
            val subscribed = gatt.setCharacteristicNotification(characteristic, true)
            val descriptor = characteristic.getDescriptor(CLIENT_CHARACTERISTIC_CONFIG_UUID)
            if (!subscribed || descriptor == null) {
                onStatus("心率通知订阅失败")
                closeGatt()
                scheduleRescan()
                return
            }
            val descriptorWriteStarted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                gatt.writeDescriptor(
                    descriptor,
                    BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE,
                ) == BluetoothGatt.GATT_SUCCESS
            } else {
                @Suppress("DEPRECATION")
                descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                @Suppress("DEPRECATION")
                gatt.writeDescriptor(descriptor)
            }
            onStatus(
                if (descriptorWriteStarted) {
                    "已订阅实时心率通知，等待 BPM"
                } else {
                    "心率通知描述符写入失败"
                },
            )
        }

        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            if (characteristic.uuid == HEART_RATE_MEASUREMENT_UUID) {
                @Suppress("DEPRECATION")
                handleMeasurement(gatt, characteristic.value)
            }
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            if (characteristic.uuid == HEART_RATE_MEASUREMENT_UUID) {
                handleMeasurement(gatt, value)
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun start() {
        if (active) {
            onStatus("心率广播 POC 已在运行")
            return
        }
        if (!hasBlePermissions()) {
            onStatus("缺少蓝牙扫描/连接权限")
            return
        }
        if (!context.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)) {
            onStatus("当前设备未声明支持 BLE")
            return
        }
        val adapter = bluetoothManager?.adapter
        if (adapter == null || !adapter.isEnabled) {
            onStatus("蓝牙未开启")
            return
        }
        scanner = adapter.bluetoothLeScanner
        if (scanner == null) {
            onStatus("无法获取 BLE scanner")
            return
        }
        active = true
        startScan()
    }

    @SuppressLint("MissingPermission")
    fun stop() {
        active = false
        handler.removeCallbacksAndMessages(null)
        stopScan()
        closeGatt()
        onStatus("心率广播 POC 已停止")
    }

    private fun handleMeasurement(gatt: BluetoothGatt, value: ByteArray) {
        val bpm = parseHeartRateMeasurement(value) ?: return
        val device = gatt.device
        @SuppressLint("MissingPermission")
        val name = if (hasBlePermissions()) device.name else null
        onSample(
            HeartRateBroadcastSample(
                bpm = bpm,
                peripheralName = name,
                peripheralAddress = device.address,
                rssi = currentRssi,
                capturedAt = Instant.now(),
                monotonicNs = android.os.SystemClock.elapsedRealtimeNanos(),
                rawHex = value.toHex(),
            ),
        )
    }

    @SuppressLint("MissingPermission")
    private fun startScan() {
        if (!active || !hasBlePermissions()) return
        onStatus("正在扫描标准 BLE 心率广播")
        val filter = ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(HEART_RATE_SERVICE_UUID))
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        scanner?.startScan(listOf(filter), settings, scanCallback)
    }

    @SuppressLint("MissingPermission")
    private fun stopScan() {
        if (!hasBlePermissions()) return
        runCatching { scanner?.stopScan(scanCallback) }
    }

    private fun scheduleRescan() {
        if (active) handler.postDelayed({ startScan() }, RESCAN_DELAY_MS)
    }

    @SuppressLint("MissingPermission")
    private fun closeGatt() {
        runCatching { gatt?.disconnect() }
        runCatching { gatt?.close() }
        gatt = null
    }

    private fun hasBlePermissions(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            (
                ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_SCAN) ==
                    PackageManager.PERMISSION_GRANTED &&
                    ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) ==
                    PackageManager.PERMISSION_GRANTED
                )

    private fun parseHeartRateMeasurement(value: ByteArray): Int? {
        if (value.size < 2) return null
        val flags = value[0].toInt()
        return if (flags and HEART_RATE_VALUE_UINT16_FLAG == 0) {
            value[1].toInt() and 0xff
        } else {
            if (value.size < 3) return null
            (value[1].toInt() and 0xff) or ((value[2].toInt() and 0xff) shl 8)
        }
    }

    private fun ByteArray.toHex(): String =
        joinToString("") { String.format(Locale.US, "%02x", it.toInt() and 0xff) }

    companion object {
        private val HEART_RATE_SERVICE_UUID =
            UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")
        private val HEART_RATE_MEASUREMENT_UUID =
            UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb")
        private val CLIENT_CHARACTERISTIC_CONFIG_UUID =
            UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

        private const val HEART_RATE_VALUE_UINT16_FLAG = 0x01
        private const val RESCAN_DELAY_MS = 2_000L
    }
}
