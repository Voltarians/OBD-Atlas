import CoreBluetooth
import Flutter
import UIKit

public final class AtlasAndroidRfcommPlugin: NSObject, FlutterPlugin, FlutterStreamHandler, CBCentralManagerDelegate, CBPeripheralDelegate {
    private var central: CBCentralManager?
    private var eventSink: FlutterEventSink?

    private var scanResult: FlutterResult?
    private var scanTimeout: DispatchWorkItem?
    private var discovered: [UUID: CBPeripheral] = [:]
    private var reports: [UUID: [String: Any]] = [:]

    private var connectResult: FlutterResult?
    private var connectTimeout: DispatchWorkItem?
    private var activePeripheral: CBPeripheral?
    private var notifyCharacteristic: CBCharacteristic?
    private var writeCharacteristic: CBCharacteristic?

    private let profiles: [(service: String, notify: String, write: String, tag: String)] = [
        ("18F0", "2AF0", "2AF1", "vLinker 18F0"),
        ("FFF0", "FFF1", "FFF2", "BLE UART FFF0"),
        ("FFE0", "FFE1", "FFE1", "BLE UART FFE0"),
        ("6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
         "6E400003-B5A3-F393-E0A9-E50E24DCCA9E",
         "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
         "Nordic UART")
    ]

    public static func register(with registrar: FlutterPluginRegistrar) {
        let methodChannel = FlutterMethodChannel(
            name: "obd_atlas/android_rfcomm",
            binaryMessenger: registrar.messenger())
        let eventChannel = FlutterEventChannel(
            name: "obd_atlas/android_rfcomm_bytes",
            binaryMessenger: registrar.messenger())
        let instance = AtlasAndroidRfcommPlugin()
        registrar.addMethodCallDelegate(instance, channel: methodChannel)
        eventChannel.setStreamHandler(instance)
    }

    public func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink) -> FlutterError? {
        eventSink = events
        return nil
    }

    public func onCancel(withArguments arguments: Any?) -> FlutterError? {
        eventSink = nil
        return nil
    }

    public func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        switch call.method {
        case "requestConnectPermission":
            ensureCentral()
            result(true)
        case "bluetoothState":
            ensureCentral()
            result(stateName(central?.state ?? .unknown))
        case "pairedDevices":
            result(reports.values.map { $0 })
        case "scanBleDevices", "probeClassicDevices":
            startBleScan(call, result: result)
        case "connect":
            connectBle(call, result: result)
        case "write":
            writeBle(call, result: result)
        case "close":
            closeBle()
            result(nil)
        default:
            result(FlutterMethodNotImplemented)
        }
    }

    private func ensureCentral() {
        if central == nil {
            central = CBCentralManager(delegate: self, queue: .main)
        }
    }

    private func startBleScan(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        guard scanResult == nil else {
            result(FlutterError(
                code: "SCAN_BUSY",
                message: "A BLE scan is already running.",
                details: nil))
            return
        }

        ensureCentral()
        discovered.removeAll()
        reports.removeAll()

        let args = call.arguments as? [String: Any]
        let seconds = max(2.0, min((args?["timeoutSeconds"] as? Double) ?? 8.0, 30.0))
        scanResult = result

        let work = DispatchWorkItem { [weak self] in
            self?.completeBleScan()
        }
        scanTimeout = work
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)

        if central?.state == .poweredOn {
            beginBleScan()
        }
    }

    private func beginBleScan() {
        central?.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
    }

    private func completeBleScan() {
        guard let result = scanResult else { return }
        central?.stopScan()
        scanTimeout?.cancel()
        scanTimeout = nil
        scanResult = nil

        let values = reports.values.sorted {
            (($0["name"] as? String) ?? "")
                .localizedCaseInsensitiveCompare(($1["name"] as? String) ?? "") == .orderedAscending
        }
        result(values)
    }

    private func connectBle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        guard connectResult == nil else {
            result(FlutterError(
                code: "CONNECT_BUSY",
                message: "A BLE connection attempt is already running.",
                details: nil))
            return
        }
        guard let args = call.arguments as? [String: Any],
              let address = args["address"] as? String,
              let identifier = UUID(uuidString: address) else {
            result(FlutterError(
                code: "ARGUMENT",
                message: "Missing or invalid iOS BLE peripheral identifier.",
                details: nil))
            return
        }

        ensureCentral()
        guard central?.state == .poweredOn else {
            result(FlutterError(
                code: "BLUETOOTH",
                message: "Bluetooth is not powered on.",
                details: nil))
            return
        }

        let peripheral = discovered[identifier]
            ?? central?.retrievePeripherals(withIdentifiers: [identifier]).first

        guard let target = peripheral else {
            result(FlutterError(
                code: "NOT_FOUND",
                message: "The selected BLE adapter is no longer available. Scan again.",
                details: nil))
            return
        }

        closeActivePeripheral()
        connectResult = result
        activePeripheral = target
        target.delegate = self

        let timeout = DispatchWorkItem { [weak self] in
            self?.failConnect(
                code: "CONNECT_TIMEOUT",
                message: "Timed out discovering a writable/notify BLE GATT transport.")
        }
        connectTimeout = timeout
        DispatchQueue.main.asyncAfter(deadline: .now() + 12.0, execute: timeout)
        central?.connect(target, options: nil)
    }

    private func writeBle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        guard let peripheral = activePeripheral,
              peripheral.state == .connected,
              let characteristic = writeCharacteristic else {
            result(FlutterError(
                code: "WRITE",
                message: "BLE GATT transport is not connected.",
                details: nil))
            return
        }

        guard let typed = call.arguments as? FlutterStandardTypedData else {
            result(FlutterError(
                code: "ARGUMENT",
                message: "Missing bytes.",
                details: nil))
            return
        }

        let type: CBCharacteristicWriteType =
            characteristic.properties.contains(.writeWithoutResponse)
                ? .withoutResponse
                : .withResponse
        peripheral.writeValue(typed.data, for: characteristic, type: type)
        result(nil)
    }

    private func closeBle() {
        central?.stopScan()
        scanTimeout?.cancel()
        scanTimeout = nil
        if let pending = scanResult {
            scanResult = nil
            pending(reports.values.map { $0 })
        }

        if connectResult != nil {
            failConnect(code: "CANCELLED", message: "BLE connection cancelled.")
        }
        closeActivePeripheral()
    }

    private func closeActivePeripheral() {
        if let peripheral = activePeripheral {
            if let notify = notifyCharacteristic, notify.isNotifying {
                peripheral.setNotifyValue(false, for: notify)
            }
            central?.cancelPeripheralConnection(peripheral)
        }
        activePeripheral = nil
        notifyCharacteristic = nil
        writeCharacteristic = nil
    }

    private func failConnect(code: String, message: String) {
        connectTimeout?.cancel()
        connectTimeout = nil
        let pending = connectResult
        connectResult = nil
        closeActivePeripheral()
        pending?(FlutterError(code: code, message: message, details: nil))
    }

    private func completeConnect(profile: String) {
        guard let pending = connectResult else { return }
        connectTimeout?.cancel()
        connectTimeout = nil
        connectResult = nil

        if let peripheral = activePeripheral {
            var report = reports[peripheral.identifier] ?? [:]
            report["state"] = "connected"
            report["profile"] = profile
            report["transport"] = "ble-gatt"
            reports[peripheral.identifier] = report
        }
        pending(nil)
    }

    public func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if scanResult != nil {
            if central.state == .poweredOn {
                beginBleScan()
            } else if central.state == .unauthorized ||
                        central.state == .unsupported ||
                        central.state == .poweredOff {
                completeBleScan()
            }
        }

        if connectResult != nil && central.state != .poweredOn {
            failConnect(
                code: "BLUETOOTH",
                message: "Bluetooth became unavailable while connecting.")
        }
    }

    public func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        discovered[peripheral.identifier] = peripheral
        peripheral.delegate = self

        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        var report = reports[peripheral.identifier] ?? [:]
        report["name"] = advertisedName ?? peripheral.name ?? ""
        report["address"] = peripheral.identifier.uuidString
        report["transport"] = "ble-gatt"
        report["state"] = peripheralState(peripheral.state)
        report["rssi"] = RSSI.intValue
        report["timestamp"] = ISO8601DateFormatter().string(from: Date())

        if let serviceUUIDs = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] {
            report["advertisedServices"] = serviceUUIDs.map { $0.uuidString }
        }
        reports[peripheral.identifier] = report
    }

    public func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        activePeripheral = peripheral
        peripheral.delegate = self
        peripheral.discoverServices(nil)
    }

    public func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        failConnect(
            code: "CONNECT",
            message: error?.localizedDescription ?? "BLE connection failed.")
    }

    public func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        if activePeripheral?.identifier == peripheral.identifier {
            activePeripheral = nil
            notifyCharacteristic = nil
            writeCharacteristic = nil
            if let error = error {
                eventSink?(FlutterError(
                    code: "DISCONNECTED",
                    message: error.localizedDescription,
                    details: nil))
            }
        }
    }

    public func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error = error {
            failConnect(code: "DISCOVERY", message: error.localizedDescription)
            return
        }
        for service in peripheral.services ?? [] {
            peripheral.discoverCharacteristics(nil, for: service)
        }
    }

    private func tryGenericSerialProfile(
        peripheral: CBPeripheral,
        service: CBService,
        characteristics: [CBCharacteristic]
    ) -> String? {
        let candidates = characteristics.filter {
            $0.properties.contains(.write) ||
            $0.properties.contains(.writeWithoutResponse) ||
            $0.properties.contains(.notify) ||
            $0.properties.contains(.indicate)
        }

        let notify = candidates.first {
            $0.properties.contains(.notify) || $0.properties.contains(.indicate)
        }
        let write = candidates.first {
            $0.properties.contains(.writeWithoutResponse) || $0.properties.contains(.write)
        }

        guard let notifyCharacteristic = notify,
              let writeCharacteristic = write else {
            return nil
        }

        self.notifyCharacteristic = notifyCharacteristic
        self.writeCharacteristic = writeCharacteristic
        return "Auto GATT serial \(service.uuid.uuidString)"
    }

    public func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        if let error = error {
            failConnect(code: "DISCOVERY", message: error.localizedDescription)
            return
        }

        var report = reports[peripheral.identifier] ?? [:]
        var services = report["services"] as? [[String: Any]] ?? []
        let serviceUUID = service.uuid.uuidString.uppercased()
        var chars = [[String: Any]]()

        for characteristic in service.characteristics ?? [] {
            var properties = [String]()
            if characteristic.properties.contains(.read) { properties.append("read") }
            if characteristic.properties.contains(.write) { properties.append("write") }
            if characteristic.properties.contains(.writeWithoutResponse) { properties.append("writeWithoutResponse") }
            if characteristic.properties.contains(.notify) { properties.append("notify") }
            if characteristic.properties.contains(.indicate) { properties.append("indicate") }
            chars.append([
                "uuid": characteristic.uuid.uuidString,
                "properties": properties
            ])
        }

        services.removeAll {
            (($0["uuid"] as? String) ?? "").uppercased() == serviceUUID
        }
        services.append(["uuid": service.uuid.uuidString, "characteristics": chars])
        report["services"] = services
        reports[peripheral.identifier] = report

        if let profile = profiles.first(where: {
            $0.service.uppercased() == serviceUUID
        }) {
            for characteristic in service.characteristics ?? [] {
                let uuid = characteristic.uuid.uuidString.uppercased()
                if uuid == profile.notify.uppercased() &&
                    (characteristic.properties.contains(.notify) ||
                     characteristic.properties.contains(.indicate)) {
                    notifyCharacteristic = characteristic
                }
                if uuid == profile.write.uppercased() &&
                    (characteristic.properties.contains(.write) ||
                     characteristic.properties.contains(.writeWithoutResponse)) {
                    writeCharacteristic = characteristic
                }
            }

            if let notify = notifyCharacteristic, writeCharacteristic != nil {
                report["profile"] = profile.tag
                reports[peripheral.identifier] = report
                peripheral.setNotifyValue(true, for: notify)
                return
            }
        }

        let deviceName = ((reports[peripheral.identifier]?["name"] as? String) ?? "").lowercased()
        if deviceName.contains("kiwi"),
           let genericProfile = tryGenericSerialProfile(
                peripheral: peripheral,
                service: service,
                characteristics: service.characteristics ?? []) {
            report["profile"] = genericProfile
            reports[peripheral.identifier] = report
            if let notify = notifyCharacteristic {
                peripheral.setNotifyValue(true, for: notify)
            }
        }
    }

    public func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error = error {
            failConnect(code: "NOTIFY", message: error.localizedDescription)
            return
        }
        guard characteristic === notifyCharacteristic,
              characteristic.isNotifying,
              let profile = reports[peripheral.identifier]?["profile"] as? String else {
            return
        }
        completeConnect(profile: profile)
    }

    public func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error = error {
            eventSink?(FlutterError(
                code: "READ",
                message: error.localizedDescription,
                details: nil))
            return
        }
        guard characteristic === notifyCharacteristic,
              let data = characteristic.value else {
            return
        }
        eventSink?(FlutterStandardTypedData(bytes: data))
    }

    private func stateName(_ state: CBManagerState) -> String {
        switch state {
        case .poweredOn: return "poweredOn"
        case .poweredOff: return "poweredOff"
        case .unauthorized: return "unauthorized"
        case .unsupported: return "unsupported"
        case .resetting: return "resetting"
        default: return "unknown"
        }
    }

    private func peripheralState(_ state: CBPeripheralState) -> String {
        switch state {
        case .connected: return "connected"
        case .connecting: return "connecting"
        case .disconnecting: return "disconnecting"
        default: return "disconnected"
        }
    }
}
