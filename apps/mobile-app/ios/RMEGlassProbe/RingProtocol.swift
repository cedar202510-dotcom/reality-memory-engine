import Foundation

struct RingSensorConfiguration: Codable, Equatable {
    let sampleRateHz: Int
    let accelRangeG: Int
    let gyroRangeDPS: Int
}

struct RingSystemInfo: Equatable {
    let firmwareVersion: String
    let systemTime: UInt32
    let audioStorageTotal: UInt32
    let audioStorageAvailable: UInt32
    let batteryPercent: UInt16
    let batteryCharging: Bool
    let serialNumber: String
    let cpuID: String
    let model: String

    var displayName: String {
        let normalizedModel = model.trimmingCharacters(in: .whitespacesAndNewlines)
        return normalizedModel.isEmpty ? "Ring Sound 戒指" : normalizedModel
    }

    var serialNumberSuffix: String {
        let normalizedSerialNumber = serialNumber.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedSerialNumber.isEmpty else {
            return "未知"
        }
        return String(normalizedSerialNumber.suffix(4))
    }
}

struct RingIMUSample: Codable, Equatable {
    let timestampMilliseconds: UInt32
    let accelX: Int16
    let accelY: Int16
    let accelZ: Int16
    let gyroX: Int16
    let gyroY: Int16
    let gyroZ: Int16
}

struct RingIMUBatch: Codable, Equatable {
    let sequenceStart: UInt32
    let frameCount: Int
    let sampleSize: Int
    let samples: [RingIMUSample]
}

struct RingProtocolPacket: Equatable {
    let version: UInt16
    let command: UInt16
    let body: Data
}

enum RingProtocolCodecError: LocalizedError {
    case invalidMagic
    case unsupportedVersion(UInt16)
    case bodyTooLarge(Int)
    case invalidCRC
    case malformedBody(String)
    case deviceError(Int)

    var errorDescription: String? {
        switch self {
        case .invalidMagic:
            "戒指数据包起始标记无效"
        case .unsupportedVersion(let version):
            "戒指协议版本 \(version) 暂不支持"
        case .bodyTooLarge(let size):
            "戒指数据包体过大：\(size) 字节"
        case .invalidCRC:
            "戒指数据包 CRC 校验失败"
        case .malformedBody(let reason):
            "戒指数据包格式错误：\(reason)"
        case .deviceError(let code):
            code == 2 ? "戒指忙碌，请单击戒指切换到手势模式后重试" : "戒指返回错误码 \(code)"
        }
    }
}

enum RingProtocolCodec {
    static let serviceUUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
    static let notifyCharacteristicUUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
    static let writeCharacteristicUUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

    static let systemInfoCommand: UInt16 = 0x0101
    static let systemInfoResponse: UInt16 = 0x0102
    static let startSensorReportCommand: UInt16 = 0x0601
    static let startSensorReportResponse: UInt16 = 0x0602
    static let stopSensorReportCommand: UInt16 = 0x0603
    static let stopSensorReportResponse: UInt16 = 0x0604
    static let sensorDataCommand: UInt16 = 0x0605
    static let doubleTapCommand: UInt16 = 0x0701
    static let gestureCommand: UInt16 = 0x0702
    static let keyDoublePressCommand: UInt16 = 0x0703
    static let keySinglePressCommand: UInt16 = 0x0704

    private static let magic: UInt8 = 0x3F
    private static let protocolVersion: UInt16 = 4
    private static let headerSize = 11
    private static let maxBodySize = 5_120

    static func encode(command: UInt16, body: Data = Data()) -> Data {
        var data = Data()
        data.append(magic)
        data.appendUInt16BE(protocolVersion)
        data.appendUInt16BE(command)
        data.appendUInt32BE(UInt32(body.count))
        data.appendUInt16BE(body.isEmpty ? 0 : crc16(body))
        data.append(body)
        return data
    }

    static func decode(_ packetData: Data) throws -> RingProtocolPacket {
        guard packetData.count >= headerSize else {
            throw RingProtocolCodecError.malformedBody("包头不足 \(headerSize) 字节")
        }
        guard packetData.byte(at: 0) == magic else {
            throw RingProtocolCodecError.invalidMagic
        }

        let version = packetData.uint16BE(at: 1)
        guard version <= protocolVersion else {
            throw RingProtocolCodecError.unsupportedVersion(version)
        }
        let command = packetData.uint16BE(at: 3)
        let bodyLength = Int(packetData.uint32BE(at: 5))
        guard bodyLength <= maxBodySize else {
            throw RingProtocolCodecError.bodyTooLarge(bodyLength)
        }
        guard packetData.count >= headerSize + bodyLength else {
            throw RingProtocolCodecError.malformedBody("包体长度不足")
        }

        let expectedCRC = packetData.uint16BE(at: 9)
        let body = packetData.subdata(in: headerSize..<(headerSize + bodyLength))
        if !body.isEmpty, crc16(body) != expectedCRC {
            throw RingProtocolCodecError.invalidCRC
        }
        return RingProtocolPacket(version: version, command: command, body: body)
    }

    static func parseSensorStart(_ body: Data) throws -> RingSensorConfiguration {
        try ensureSuccess(body)
        guard body.count == 8 else {
            throw RingProtocolCodecError.malformedBody("开启传感器响应长度应为 8 字节")
        }
        return RingSensorConfiguration(
            sampleRateHz: Int(body.uint16BE(at: 2)),
            accelRangeG: Int(body.uint16BE(at: 4)),
            gyroRangeDPS: Int(body.uint16BE(at: 6))
        )
    }

    static func parseSystemInfo(_ body: Data) throws -> RingSystemInfo {
        try ensureSuccess(body)
        var reader = RingDataReader(data: body, offset: 2)
        return RingSystemInfo(
            firmwareVersion: try reader.readString(),
            systemTime: try reader.readUInt32(),
            audioStorageTotal: try reader.readUInt32(),
            audioStorageAvailable: try reader.readUInt32(),
            batteryPercent: try reader.readUInt16(),
            batteryCharging: try reader.readUInt8() != 0,
            serialNumber: try reader.readString(),
            cpuID: try reader.readString(),
            model: try reader.readString()
        )
    }

    static func parseSensorStop(_ body: Data) throws {
        try ensureSuccess(body)
        guard body.count == 2 else {
            throw RingProtocolCodecError.malformedBody("停止传感器响应长度应为 2 字节")
        }
    }

    static func parseSensorBatch(_ body: Data) throws -> RingIMUBatch {
        try ensureSuccess(body)
        guard body.count >= 10 else {
            throw RingProtocolCodecError.malformedBody("IMU 批次包体过短")
        }

        let sequenceStart = body.uint32BE(at: 2)
        let frameCount = Int(body.uint16BE(at: 6))
        let sampleSize = Int(body.uint16BE(at: 8))
        guard sampleSize == 16 else {
            throw RingProtocolCodecError.malformedBody("不支持 \(sampleSize) 字节 IMU 样本")
        }
        let expectedLength = 10 + frameCount * sampleSize
        guard body.count == expectedLength else {
            throw RingProtocolCodecError.malformedBody(
                "IMU 批次应为 \(expectedLength) 字节，实际 \(body.count) 字节"
            )
        }

        var samples: [RingIMUSample] = []
        samples.reserveCapacity(frameCount)
        for index in 0..<frameCount {
            let offset = 10 + index * sampleSize
            samples.append(
                RingIMUSample(
                    timestampMilliseconds: body.uint32BE(at: offset),
                    accelX: body.int16BE(at: offset + 4),
                    accelY: body.int16BE(at: offset + 6),
                    accelZ: body.int16BE(at: offset + 8),
                    gyroX: body.int16BE(at: offset + 10),
                    gyroY: body.int16BE(at: offset + 12),
                    gyroZ: body.int16BE(at: offset + 14)
                )
            )
        }

        return RingIMUBatch(
            sequenceStart: sequenceStart,
            frameCount: frameCount,
            sampleSize: sampleSize,
            samples: samples
        )
    }

    static func parseEventTimestamp(_ body: Data) throws -> UInt32 {
        guard body.count == 4 else {
            throw RingProtocolCodecError.malformedBody("动作事件时间戳长度应为 4 字节")
        }
        return body.uint32BE(at: 0)
    }

    static func parseGesture(_ body: Data) throws -> (timestamp: UInt32, gestureID: UInt8) {
        guard body.count == 5 else {
            throw RingProtocolCodecError.malformedBody("手势事件长度应为 5 字节")
        }
        return (body.uint32BE(at: 0), body.byte(at: 4))
    }

    static func gestureName(_ id: UInt8) -> String {
        switch id {
        case 1:
            "向后旋转"
        case 2:
            "向前旋转"
        case 3:
            "挥手"
        default:
            "未知手势 \(id)"
        }
    }

    private static func ensureSuccess(_ body: Data) throws {
        guard body.count >= 2 else {
            throw RingProtocolCodecError.malformedBody("缺少设备错误码")
        }
        let errorCode = Int(body.uint16BE(at: 0))
        guard errorCode == 0 else {
            throw RingProtocolCodecError.deviceError(errorCode)
        }
    }

    private static func crc16(_ data: Data, initial: UInt16 = 0xFFFF) -> UInt16 {
        var crc = initial
        for byte in data {
            crc = (crc >> 8) | (crc << 8)
            crc ^= UInt16(byte)
            crc ^= (crc & 0x00FF) >> 4
            crc ^= (crc << 8) << 4
            crc ^= ((crc & 0x00FF) << 4) << 1
        }
        return crc
    }
}

private struct RingDataReader {
    let data: Data
    var offset: Int

    mutating func readUInt8() throws -> UInt8 {
        try require(1)
        defer { offset += 1 }
        return data.byte(at: offset)
    }

    mutating func readUInt16() throws -> UInt16 {
        try require(2)
        defer { offset += 2 }
        return data.uint16BE(at: offset)
    }

    mutating func readUInt32() throws -> UInt32 {
        try require(4)
        defer { offset += 4 }
        return data.uint32BE(at: offset)
    }

    mutating func readString() throws -> String {
        let length = Int(try readUInt16())
        try require(length)
        let bytes = data.subdata(in: offset..<(offset + length))
        offset += length
        guard let value = String(data: bytes, encoding: .utf8) else {
            throw RingProtocolCodecError.malformedBody("系统信息包含无效 UTF-8 字符串")
        }
        return value
    }

    private func require(_ length: Int) throws {
        guard length >= 0, offset + length <= data.count else {
            throw RingProtocolCodecError.malformedBody("系统信息字段长度超出包体")
        }
    }
}

final class RingPacketStreamParser {
    private var buffer = Data()

    func reset() {
        buffer.removeAll(keepingCapacity: true)
    }

    func feed(_ chunk: Data) throws -> [RingProtocolPacket] {
        buffer.append(chunk)
        var packets: [RingProtocolPacket] = []

        while !buffer.isEmpty {
            guard let magicIndex = buffer.firstIndex(of: 0x3F) else {
                buffer.removeAll(keepingCapacity: true)
                return packets
            }
            if magicIndex > buffer.startIndex {
                buffer.removeSubrange(buffer.startIndex..<magicIndex)
            }
            guard buffer.count >= 11 else {
                return packets
            }

            let bodyLength = Int(buffer.uint32BE(at: 5))
            guard bodyLength <= 5_120 else {
                buffer.removeAll(keepingCapacity: true)
                throw RingProtocolCodecError.bodyTooLarge(bodyLength)
            }
            let packetLength = 11 + bodyLength
            guard buffer.count >= packetLength else {
                return packets
            }

            let packetData = buffer.prefix(packetLength)
            buffer.removeFirst(packetLength)
            packets.append(try RingProtocolCodec.decode(Data(packetData)))
        }
        return packets
    }
}

private extension Data {
    mutating func appendUInt16BE(_ value: UInt16) {
        append(UInt8((value >> 8) & 0xFF))
        append(UInt8(value & 0xFF))
    }

    mutating func appendUInt32BE(_ value: UInt32) {
        append(UInt8((value >> 24) & 0xFF))
        append(UInt8((value >> 16) & 0xFF))
        append(UInt8((value >> 8) & 0xFF))
        append(UInt8(value & 0xFF))
    }

    func byte(at offset: Int) -> UInt8 {
        self[index(startIndex, offsetBy: offset)]
    }

    func uint16BE(at offset: Int) -> UInt16 {
        (UInt16(byte(at: offset)) << 8) | UInt16(byte(at: offset + 1))
    }

    func int16BE(at offset: Int) -> Int16 {
        Int16(bitPattern: uint16BE(at: offset))
    }

    func uint32BE(at offset: Int) -> UInt32 {
        (UInt32(byte(at: offset)) << 24)
            | (UInt32(byte(at: offset + 1)) << 16)
            | (UInt32(byte(at: offset + 2)) << 8)
            | UInt32(byte(at: offset + 3))
    }
}
