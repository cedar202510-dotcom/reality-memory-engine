import CoreBluetooth
import Foundation

struct RingDiscoveredDevice: Identifiable, Equatable {
    let id: UUID
    let name: String
    let rssi: Int
    let advertisesRingService: Bool
    let isKnownRing: Bool

    var shortIdentifier: String {
        String(id.uuidString.suffix(4))
    }

    var displayName: String {
        if isKnownRing {
            return "我的戒指"
        }
        if advertisesRingService {
            return name == "未命名蓝牙设备" ? "疑似戒指" : "\(name)（疑似戒指）"
        }
        return name
    }
}

enum RingAdapterState: Equatable {
    case bluetoothUnavailable(String)
    case idle
    case scanning
    case connecting
    case discoveringServices
    case verifyingIdentity
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
        case .verifyingIdentity:
            "正在验证戒指身份"
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
        case .verifyingIdentity, .connected, .preparingSensor, .sensorReporting:
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
    var onSystemInfo: ((RingSystemInfo) -> Void)?
    var onSensorConfiguration: ((RingSensorConfiguration) -> Void)?
    var onIMUBatch: ((RingIMUBatch, Date) -> Void)?
    var onHardwareEvent: ((RingHardwareEvent) -> Void)?
    var onLog: ((String) -> Void)?

    private let serviceUUID = CBUUID(string: RingProtocolCodec.serviceUUID)
    private let notifyUUID = CBUUID(string: RingProtocolCodec.notifyCharacteristicUUID)
    private let writeUUID = CBUUID(string: RingProtocolCodec.writeCharacteristicUUID)
    private let streamParser = RingPacketStreamParser()
    private let knownRingIdentifierKey = "rme.ring.known-peripheral-identifier"

    private lazy var central = CBCentralManager(delegate: self, queue: .main)
    private var peripherals: [UUID: CBPeripheral] = [:]
    private var discovered: [UUID: RingDiscoveredDevice] = [:]
    private var connectedPeripheral: CBPeripheral?
    private var notifyCharacteristic: CBCharacteristic?
    private var writeCharacteristic: CBCharacteristic?
    private var scanStopTask: Task<Void, Never>?
    private var connectionTimeoutTask: Task<Void, Never>?
    private var responseTimeoutTask: Task<Void, Never>?
    private var identityTimeoutTask: Task<Void, Never>?
    private var reconnectTask: Task<Void, Never>?
    private var hasAttemptedAutomaticReconnect = false
    private var shouldMaintainConnection = false
    private var reconnectAttempt = 0
    private var knownRingIdentifier: UUID? {
        guard
            let value = UserDefaults.standard.string(forKey: knownRingIdentifierKey),
            let identifier = UUID(uuidString: value)
        else {
            return nil
        }
        return identifier
    }
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
            withServices: [serviceUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
        state = .scanning
        onLog?("开始扫描广播戒指 NUS 服务的设备；不会展示其他未知蓝牙设备")

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
        shouldMaintainConnection = true
        reconnectAttempt = 0
        beginConnection(to: peripheral)
    }

    private func beginConnection(to peripheral: CBPeripheral) {
        reconnectTask?.cancel()
        reconnectTask = nil
        stopScan()
        disconnectCurrentIfNeeded()
        connectedPeripheral = peripheral
        peripheral.delegate = self
        streamParser.reset()
        state = .connecting
        central.connect(peripheral, options: nil)
        connectionTimeoutTask?.cancel()
        connectionTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 10_000_000_000)
            guard !Task.isCancelled, let self, self.state == .connecting else {
                return
            }
            self.state = .failed("连接戒指超时，请确认戒指有电且靠近手机")
            self.central.cancelPeripheralConnection(peripheral)
        }
    }

    func disconnect() {
        shouldMaintainConnection = false
        reconnectTask?.cancel()
        reconnectTask = nil
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
        let writeType: CBCharacteristicWriteType
        if writeCharacteristic.properties.contains(.writeWithoutResponse) {
            writeType = .withoutResponse
        } else if writeCharacteristic.properties.contains(.write) {
            writeType = .withResponse
        } else {
            state = .failed("戒指 NUS 写入通道不支持写入")
            return
        }
        onLog?(
            String(
                format: "正在发送戒指命令 0x%04X（%@）",
                command,
                writeType == .withoutResponse ? "无响应写入" : "有响应写入"
            )
        )
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
            case RingProtocolCodec.systemInfoResponse:
                identityTimeoutTask?.cancel()
                let systemInfo = try RingProtocolCodec.parseSystemInfo(packet.body)
                rememberConnectedRing()
                state = .connected
                onSystemInfo?(systemInfo)
                onLog?(
                    "戒指身份验证成功：\(systemInfo.displayName)，"
                        + "序列号尾号 \(systemInfo.serialNumberSuffix)，"
                        + "电量 \(systemInfo.batteryPercent)%"
                )
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
            if packet.command == RingProtocolCodec.systemInfoResponse {
                identityTimeoutTask?.cancel()
                state = .failed("设备未通过戒指协议验证")
                if let connectedPeripheral {
                    central.cancelPeripheralConnection(connectedPeripheral)
                }
            }
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

    private func rememberConnectedRing() {
        guard let connectedPeripheral else {
            return
        }
        let identifier = connectedPeripheral.identifier
        guard knownRingIdentifier != identifier else {
            return
        }
        UserDefaults.standard.set(identifier.uuidString, forKey: knownRingIdentifierKey)
        if let current = discovered[identifier] {
            discovered[identifier] = RingDiscoveredDevice(
                id: current.id,
                name: current.name,
                rssi: current.rssi,
                advertisesRingService: current.advertisesRingService,
                isKnownRing: true
            )
            publishDiscoveredDevices()
        }
        onLog?("已通过戒指专用数据包确认设备，今后显示为“我的戒指”")
    }

    private func publishDiscoveredDevices() {
        onDevicesChanged?(
            discovered.values.sorted {
                if $0.isKnownRing != $1.isKnownRing {
                    return $0.isKnownRing
                }
                if $0.advertisesRingService != $1.advertisesRingService {
                    return $0.advertisesRingService
                }
                if $0.rssi != $1.rssi {
                    return $0.rssi > $1.rssi
                }
                return $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
            }
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
        identityTimeoutTask?.cancel()
        connectionTimeoutTask?.cancel()
    }

    private func verifyConnectedDeviceIdentity() {
        state = .verifyingIdentity
        onLog?("NUS 通道已就绪，正在读取戒指型号、序列号和电量")
        write(command: RingProtocolCodec.systemInfoCommand)
        identityTimeoutTask?.cancel()
        identityTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            guard !Task.isCancelled, let self else {
                return
            }
            self.state = .failed("设备未返回戒指系统信息")
            self.onLog?("身份验证超时：该设备虽然提供 NUS 服务，但未通过戒指协议验证")
            if let peripheral = self.connectedPeripheral {
                self.central.cancelPeripheralConnection(peripheral)
            }
        }
    }

    private func reconnectKnownRingIfPossible() {
        guard !hasAttemptedAutomaticReconnect, let knownRingIdentifier else {
            return
        }
        hasAttemptedAutomaticReconnect = true
        guard let peripheral = central.retrievePeripherals(
            withIdentifiers: [knownRingIdentifier]
        ).first else {
            onLog?("未能从 iOS 蓝牙缓存恢复已绑定戒指，请执行一次定向扫描")
            return
        }
        let device = RingDiscoveredDevice(
            id: peripheral.identifier,
            name: peripheral.name ?? "已绑定戒指",
            rssi: 0,
            advertisesRingService: true,
            isKnownRing: true
        )
        peripherals[device.id] = peripheral
        discovered[device.id] = device
        publishDiscoveredDevices()
        onLog?("正在自动连接已验证的戒指")
        shouldMaintainConnection = true
        connect(deviceID: device.id)
    }

    private func scheduleReconnect(to peripheral: CBPeripheral) {
        guard shouldMaintainConnection, reconnectTask == nil else {
            return
        }
        reconnectAttempt += 1
        let delaySeconds = min(15, max(2, reconnectAttempt * 2))
        onLog?("\(delaySeconds) 秒后自动重连已验证戒指（第 \(reconnectAttempt) 次）")
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delaySeconds) * 1_000_000_000)
            guard !Task.isCancelled, let self else {
                return
            }
            self.reconnectTask = nil
            guard
                self.shouldMaintainConnection,
                self.central.state == .poweredOn,
                self.connectedPeripheral == nil
            else {
                return
            }
            self.onLog?("正在自动重连已验证戒指")
            self.beginConnection(to: peripheral)
        }
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
        if central.state == .poweredOn {
            reconnectKnownRingIfPossible()
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let name = advertisedName ?? peripheral.name ?? "未命名蓝牙设备"
        let advertisedServices =
            (advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? [])
            + (advertisementData[CBAdvertisementDataOverflowServiceUUIDsKey] as? [CBUUID] ?? [])
        let device = RingDiscoveredDevice(
            id: peripheral.identifier,
            name: name,
            rssi: RSSI.intValue,
            advertisesRingService: advertisedServices.contains(serviceUUID),
            isKnownRing: peripheral.identifier == knownRingIdentifier
        )
        peripherals[device.id] = peripheral
        discovered[device.id] = device
        publishDiscoveredDevices()
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        connectionTimeoutTask?.cancel()
        reconnectAttempt = 0
        state = .discoveringServices
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        connectionTimeoutTask?.cancel()
        connectedPeripheral = nil
        state = .failed(error?.localizedDescription ?? "连接戒指失败")
        scheduleReconnect(to: peripheral)
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        let shouldReconnect = shouldMaintainConnection && state != .disconnecting
        connectedPeripheral = nil
        notifyCharacteristic = nil
        writeCharacteristic = nil
        responseTimeoutTask?.cancel()
        identityTimeoutTask?.cancel()
        connectionTimeoutTask?.cancel()
        streamParser.reset()
        if !shouldReconnect {
            state = .idle
            return
        }
        state = error == nil ? .idle : .failed("戒指蓝牙断开：\(error!.localizedDescription)")
        scheduleReconnect(to: peripheral)
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
        verifyConnectedDeviceIdentity()
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

    func peripheral(
        _ peripheral: CBPeripheral,
        didWriteValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        guard characteristic.uuid == writeUUID else {
            return
        }
        if let error {
            onLog?("戒指命令写入失败：\(error.localizedDescription)")
        } else {
            onLog?("戒指命令已由蓝牙通道确认写入")
        }
    }
}
