import CoreBluetooth
import Foundation

struct RingDiscoveredDevice: Identifiable, Equatable {
    let id: UUID
    let name: String
    let rssi: Int
}

enum RingAdapterState: Equatable {
    case bluetoothUnavailable(String)
    case idle
    case scanning
    case connecting
    case discoveringServices
    case connected
    case preparingSensor
    case sensorReporting
    case disconnecting
    case failed(String)

    var displayName: String {
        switch self {
        case .bluetoothUnavailable(let reason):
            "蓝牙不可用：\(reason)"
        case .idle:
            "未连接"
        case .scanning:
            "扫描中"
        case .connecting:
            "连接中"
        case .discoveringServices:
            "读取服务中"
        case .connected:
            "已连接"
        case .preparingSensor:
            "正在开启传感器"
        case .sensorReporting:
            "传感器采集中"
        case .disconnecting:
            "断开中"
        case .failed(let reason):
            "失败：\(reason)"
        }
    }

    var isConnected: Bool {
        switch self {
        case .connected, .preparingSensor, .sensorReporting:
            true
        default:
            false
        }
    }

    var isSensorReporting: Bool {
        self == .sensorReporting
    }
}

struct RingHardwareEvent {
    let occurredAt: Date
    let deviceTimestampMilliseconds: UInt32
    let type: String
    let detail: String?
}

final class RingDeviceAdapter: NSObject {
    var onStateChanged: ((RingAdapterState) -> Void)?
    var onDevicesChanged: (([RingDiscoveredDevice]) -> Void)?
    var onSensorConfiguration: ((RingSensorConfiguration) -> Void)?
    var onIMUBatch: ((RingIMUBatch, Date) -> Void)?
    var onHardwareEvent: ((RingHardwareEvent) -> Void)?
    var onLog: ((String) -> Void)?

    private let serviceUUID = CBUUID(string: RingProtocolCodec.serviceUUID)
    private let notifyUUID = CBUUID(string: RingProtocolCodec.notifyCharacteristicUUID)
    private let writeUUID = CBUUID(string: RingProtocolCodec.writeCharacteristicUUID)
    private let streamParser = RingPacketStreamParser()

    private lazy var central = CBCentralManager(delegate: self, queue: .main)
    private var peripherals: [UUID: CBPeripheral] = [:]
    private var discovered: [UUID: RingDiscoveredDevice] = [:]
    private var connectedPeripheral: CBPeripheral?
    private var notifyCharacteristic: CBCharacteristic?
    private var writeCharacteristic: CBCharacteristic?
    private var scanStopTask: Task<Void, Never>?
    private var responseTimeoutTask: Task<Void, Never>?
    private(set) var state: RingAdapterState = .idle {
        didSet {
            onStateChanged?(state)
        }
    }

    override init() {
        super.init()
        _ = central
    }

    func scan() {
        guard central.state == .poweredOn else {
            updateBluetoothState()
            return
        }
        discovered.removeAll()
        peripherals.removeAll()
        onDevicesChanged?([])
        central.stopScan()
        central.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
        state = .scanning
        onLog?("开始扫描附近蓝牙设备；iOS 使用设备 UUID，不提供 MAC 地址")

        scanStopTask?.cancel()
        scanStopTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            guard !Task.isCancelled else {
                return
            }
            self?.stopScan()
        }
    }

    func stopScan() {
        central.stopScan()
        scanStopTask?.cancel()
        scanStopTask = nil
        if state == .scanning {
            state = .idle
        }
    }

    func connect(deviceID: UUID) {
        guard let peripheral = peripherals[deviceID] else {
            state = .failed("找不到所选戒指，请重新扫描")
            return
        }
        stopScan()
        disconnectCurrentIfNeeded()
        connectedPeripheral = peripheral
        peripheral.delegate = self
        streamParser.reset()
        state = .connecting
        central.connect(peripheral, options: nil)
    }

    func disconnect() {
        guard let connectedPeripheral else {
            state = .idle
            return
        }
        state = .disconnecting
        central.cancelPeripheralConnection(connectedPeripheral)
    }

    func startSensorReport() {
        guard state == .connected, writeCharacteristic != nil else {
            onLog?("无法开启戒指传感器：戒指连接或 NUS 写入通道未就绪")
            return
        }
        state = .preparingSensor
        write(command: RingProtocolCodec.startSensorReportCommand)
        startResponseTimeout(action: "开启戒指传感器", fallbackState: .connected)
    }

    func stopSensorReport() {
        guard state.isConnected, writeCharacteristic != nil else {
            return
        }
        write(command: RingProtocolCodec.stopSensorReportCommand)
        startResponseTimeout(action: "停止戒指传感器", fallbackState: .sensorReporting)
    }

    private func write(command: UInt16) {
        guard let connectedPeripheral, let writeCharacteristic else {
            state = .failed("戒指写入通道未就绪")
            return
        }
        let packet = RingProtocolCodec.encode(command: command)
        let writeType: CBCharacteristicWriteType =
            writeCharacteristic.properties.contains(.write) ? .withResponse : .withoutResponse
        connectedPeripheral.writeValue(packet, for: writeCharacteristic, type: writeType)
    }

    private func startResponseTimeout(action: String, fallbackState: RingAdapterState) {
        responseTimeoutTask?.cancel()
        responseTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            guard !Task.isCancelled, let self else {
                return
            }
            self.onLog?("\(action)等待响应超时，可重新尝试")
            self.state = fallbackState
        }
    }

    private func handle(_ packet: RingProtocolPacket, receivedAt: Date) {
        do {
            switch packet.command {
            case RingProtocolCodec.startSensorReportResponse:
                responseTimeoutTask?.cancel()
                let configuration = try RingProtocolCodec.parseSensorStart(packet.body)
                state = .sensorReporting
                onSensorConfiguration?(configuration)
                onLog?(
                    "戒指传感器已开启：\(configuration.sampleRateHz)Hz，"
                        + "加速度 ±\(configuration.accelRangeG)g，"
                        + "陀螺仪 ±\(configuration.gyroRangeDPS)dps"
                )
            case RingProtocolCodec.stopSensorReportResponse:
                responseTimeoutTask?.cancel()
                try RingProtocolCodec.parseSensorStop(packet.body)
                state = .connected
                onLog?("戒指实时传感器上报已停止")
            case RingProtocolCodec.sensorDataCommand:
                onIMUBatch?(try RingProtocolCodec.parseSensorBatch(packet.body), receivedAt)
            case RingProtocolCodec.doubleTapCommand:
                let timestamp = try RingProtocolCodec.parseEventTimestamp(packet.body)
                emitEvent(type: "RING_DOUBLE_TAP", timestamp: timestamp, detail: "普通双击")
            case RingProtocolCodec.gestureCommand:
                let gesture = try RingProtocolCodec.parseGesture(packet.body)
                emitEvent(
                    type: "RING_HMM_GESTURE",
                    timestamp: gesture.timestamp,
                    detail: RingProtocolCodec.gestureName(gesture.gestureID)
                )
            case RingProtocolCodec.keyDoublePressCommand:
                let timestamp = try RingProtocolCodec.parseEventTimestamp(packet.body)
                emitEvent(type: "RING_KEY_DOUBLE_PRESS", timestamp: timestamp, detail: "按键双击")
            case RingProtocolCodec.keySinglePressCommand:
                let timestamp = try RingProtocolCodec.parseEventTimestamp(packet.body)
                emitEvent(type: "RING_KEY_SINGLE_PRESS", timestamp: timestamp, detail: "按键单击")
            default:
                break
            }
        } catch {
            if packet.command == RingProtocolCodec.startSensorReportResponse {
                responseTimeoutTask?.cancel()
                state = .connected
            }
            onLog?(error.localizedDescription)
        }
    }

    private func emitEvent(type: String, timestamp: UInt32, detail: String) {
        onHardwareEvent?(
            RingHardwareEvent(
                occurredAt: Date(),
                deviceTimestampMilliseconds: timestamp,
                type: type,
                detail: detail
            )
        )
    }

    private func disconnectCurrentIfNeeded() {
        if let connectedPeripheral {
            central.cancelPeripheralConnection(connectedPeripheral)
        }
        self.connectedPeripheral = nil
        notifyCharacteristic = nil
        writeCharacteristic = nil
        responseTimeoutTask?.cancel()
    }

    private func updateBluetoothState() {
        switch central.state {
        case .poweredOn:
            if !state.isConnected, state != .scanning {
                state = .idle
            }
        case .poweredOff:
            state = .bluetoothUnavailable("手机蓝牙已关闭")
        case .unauthorized:
            state = .bluetoothUnavailable("Reality Memory 未获得蓝牙权限")
        case .unsupported:
            state = .bluetoothUnavailable("当前设备不支持蓝牙低功耗")
        case .resetting:
            state = .bluetoothUnavailable("蓝牙正在重置")
        case .unknown:
            state = .bluetoothUnavailable("蓝牙状态未知")
        @unknown default:
            state = .bluetoothUnavailable("未知蓝牙状态")
        }
    }
}

extension RingDeviceAdapter: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        updateBluetoothState()
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let name = advertisedName ?? peripheral.name ?? "未命名蓝牙设备"
        let device = RingDiscoveredDevice(
            id: peripheral.identifier,
            name: name,
            rssi: RSSI.intValue
        )
        peripherals[device.id] = peripheral
        discovered[device.id] = device
        onDevicesChanged?(
            discovered.values.sorted {
                if $0.rssi == $1.rssi {
                    return $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
                }
                return $0.rssi > $1.rssi
            }
        )
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        state = .discoveringServices
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        connectedPeripheral = nil
        state = .failed(error?.localizedDescription ?? "连接戒指失败")
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        connectedPeripheral = nil
        notifyCharacteristic = nil
        writeCharacteristic = nil
        responseTimeoutTask?.cancel()
        streamParser.reset()
        state = error == nil ? .idle : .failed("戒指蓝牙断开：\(error!.localizedDescription)")
    }
}

extension RingDeviceAdapter: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            state = .failed("读取戒指服务失败：\(error.localizedDescription)")
            return
        }
        guard let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            state = .failed("所选设备不是支持 NUS v4 协议的戒指")
            central.cancelPeripheralConnection(peripheral)
            return
        }
        peripheral.discoverCharacteristics([notifyUUID, writeUUID], for: service)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        if let error {
            state = .failed("读取戒指通信通道失败：\(error.localizedDescription)")
            return
        }
        notifyCharacteristic = service.characteristics?.first(where: { $0.uuid == notifyUUID })
        writeCharacteristic = service.characteristics?.first(where: { $0.uuid == writeUUID })
        guard let notifyCharacteristic, writeCharacteristic != nil else {
            state = .failed("戒指 NUS 通道不完整")
            return
        }
        peripheral.setNotifyValue(true, for: notifyCharacteristic)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            state = .failed("订阅戒指数据失败：\(error.localizedDescription)")
            return
        }
        guard characteristic.uuid == notifyUUID, characteristic.isNotifying else {
            return
        }
        state = .connected
        onLog?("戒指已连接，NUS v4 数据通道已就绪")
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            onLog?("接收戒指数据失败：\(error.localizedDescription)")
            return
        }
        guard characteristic.uuid == notifyUUID, let data = characteristic.value else {
            return
        }
        do {
            let receivedAt = Date()
            for packet in try streamParser.feed(data) {
                handle(packet, receivedAt: receivedAt)
            }
        } catch {
            onLog?(error.localizedDescription)
        }
    }
}
