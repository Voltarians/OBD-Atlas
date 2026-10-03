import CoreBluetooth
import Flutter
import UIKit

public final class AtlasAndroidRfcommPlugin: NSObject, FlutterPlugin, CBCentralManagerDelegate, CBPeripheralDelegate, FlutterStreamHandler {
    private var central: CBCentralManager?
    private var probeResult: FlutterResult?
    private var discovered: [UUID: CBPeripheral] = [:]
    private var reports: [UUID: [String: Any]] = [:]
    private var timeoutWorkItem: DispatchWorkItem?
    private var activePeripheral: CBPeripheral?
    private var rxCharacteristic: CBCharacteristic?
    private var txCharacteristic: CBCharacteristic?
    private var connectResult: FlutterResult?
    private var bytesSink: FlutterEventSink?

    public static func register(with registrar: FlutterPluginRegistrar) {
        let channel = FlutterMethodChannel(name: "obd_atlas/android_rfcomm", binaryMessenger: registrar.messenger())
        let instance = AtlasAndroidRfcommPlugin()
        registrar.addMethodCallDelegate(instance, channel: channel)
        let bytes = FlutterEventChannel(name: "obd_atlas/android_rfcomm_bytes", binaryMessenger: registrar.messenger())
        bytes.setStreamHandler(instance)
    }

    public func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        switch call.method {
        case "requestConnectPermission":
            ensureCentral(); result(true)
        case "bluetoothState":
            ensureCentral(); result(stateName(central?.state ?? .unknown))
        case "pairedDevices":
            result(reports.values.map { $0 })
        case "probeClassicDevices":
            startProbe(call, result: result)
        case "connect":
            connectBle(call, result: result)
        case "write":
            writeBle(call, result: result)
        case "close":
            closeBle(); finishProbe(); result(nil)
        default:
            result(FlutterMethodNotImplemented)
        }
    }

    private func ensureCentral() {
        if central == nil { central = CBCentralManager(delegate: self, queue: .main) }
    }

    private func startProbe(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        guard probeResult == nil else {
            result(FlutterError(code: "PROBE_BUSY", message: "Bluetooth characterization is already running.", details: nil)); return
        }
        ensureCentral()
        discovered.removeAll(); reports.removeAll()
        let args = call.arguments as? [String: Any]
        let seconds = max(2.0, min((args?["timeoutSeconds"] as? Double) ?? 12.0, 30.0))
        probeResult = result
        if central?.state == .poweredOn {
            central?.scanForPeripherals(withServices: [CBUUID(string: "18F0")], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        }
        if #available(iOS 13.0, *) { central?.registerForConnectionEvents(options: nil) }
        let work = DispatchWorkItem { [weak self] in self?.completeProbe() }
        timeoutWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    }

    private func observe(_ peripheral: CBPeripheral, event: String) {
        discovered[peripheral.identifier] = peripheral
        peripheral.delegate = self
        var report = reports[peripheral.identifier] ?? [:]
        report["name"] = peripheral.name ?? ""
        report["address"] = peripheral.identifier.uuidString
        report["transport"] = "corebluetooth-br-edr-gatt"
        report["state"] = peripheralState(peripheral.state)
        report["lastEvent"] = event
        report["timestamp"] = ISO8601DateFormatter().string(from: Date())
        if report["services"] == nil { report["services"] = [[String: Any]]() }
        reports[peripheral.identifier] = report

        if peripheral.state == .connected {
            peripheral.discoverServices(nil)
        } else if peripheral.state == .disconnected {
            central?.connect(peripheral, options: nil)
        }
    }

    private func completeProbe() {
        guard let result = probeResult else { return }
        timeoutWorkItem?.cancel(); timeoutWorkItem = nil; probeResult = nil
        central?.stopScan()
        result(reports.values.sorted {
            (($0["name"] as? String) ?? "").localizedCaseInsensitiveCompare(($1["name"] as? String) ?? "") == .orderedAscending
        })
    }

    private func finishProbe() {
        timeoutWorkItem?.cancel(); timeoutWorkItem = nil
        if #available(iOS 13.0, *) { central?.registerForConnectionEvents(options: [:]) }
        probeResult = nil
    }

    public func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state == .poweredOn && probeResult != nil {
            central.scanForPeripherals(withServices: [CBUUID(string: "18F0")], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        }
        guard probeResult != nil else { return }
        if central.state == .unauthorized || central.state == .unsupported || central.state == .poweredOff {
            completeProbe()
        }
    }

    public func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String: Any], rssi RSSI: NSNumber) {
        observe(peripheral, event: "bleAdvertisement")
    }

    @available(iOS 13.0, *)
    public func centralManager(_ central: CBCentralManager, connectionEventDidOccur event: CBConnectionEvent, for peripheral: CBPeripheral) {
        observe(peripheral, event: event == .peerConnected ? "peerConnected" : "peerDisconnected")
    }

    public func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        activePeripheral = peripheral
        peripheral.delegate = self
        observe(peripheral, event: "didConnect")
        peripheral.discoverServices([CBUUID(string: "18F0")])
    }

    public func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        observe(peripheral, event: "connectFailed")
        var r = reports[peripheral.identifier] ?? [:]
        r["error"] = error?.localizedDescription ?? "unknown"
        reports[peripheral.identifier] = r
    }

    public func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error = error {
            var r = reports[peripheral.identifier] ?? [:]; r["error"] = error.localizedDescription; reports[peripheral.identifier] = r; return
        }
        peripheral.services?.forEach { service in
            if service.uuid == CBUUID(string: "18F0") {
                peripheral.discoverCharacteristics([CBUUID(string: "2AF0"), CBUUID(string: "2AF1")], for: service)
            } else {
                peripheral.discoverCharacteristics(nil, for: service)
            }
        }
    }

    public func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        var serviceMap: [String: Any] = ["uuid": service.uuid.uuidString, "characteristics": [[String: Any]]()]
        var chars = [[String: Any]]()
        for c in service.characteristics ?? [] {
            var props = [String]()
            if c.properties.contains(.read) { props.append("read") }
            if c.properties.contains(.write) { props.append("write") }
            if c.properties.contains(.writeWithoutResponse) { props.append("writeWithoutResponse") }
            if c.properties.contains(.notify) { props.append("notify") }
            if c.properties.contains(.indicate) { props.append("indicate") }
            chars.append(["uuid": c.uuid.uuidString, "properties": props])
        }
        serviceMap["characteristics"] = chars
        var r = reports[peripheral.identifier] ?? [:]
        var services = r["services"] as? [[String: Any]] ?? []
        services.removeAll { ($0["uuid"] as? String) == service.uuid.uuidString }
        services.append(serviceMap)
        r["services"] = services
        if let error = error { r["error"] = error.localizedDescription }
        reports[peripheral.identifier] = r

        if service.uuid == CBUUID(string: "18F0") {
            for characteristic in service.characteristics ?? [] {
                if characteristic.uuid == CBUUID(string: "2AF0") {
                    rxCharacteristic = characteristic
                    peripheral.setNotifyValue(true, for: characteristic)
                } else if characteristic.uuid == CBUUID(string: "2AF1") {
                    txCharacteristic = characteristic
                }
            }
            if rxCharacteristic != nil && txCharacteristic != nil, let pending = connectResult {
                connectResult = nil
                pending(nil)
            }
        }
    }

    public func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error = error {
            bytesSink?(FlutterError(code: "IOS_BLE_READ", message: error.localizedDescription, details: nil))
            return
        }
        if characteristic.uuid == CBUUID(string: "2AF0"), let value = characteristic.value {
            bytesSink?(FlutterStandardTypedData(bytes: value))
        }
    }

    private func connectBle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        ensureCentral()
        guard central?.state == .poweredOn else {
            result(FlutterError(code: "IOS_BLE_OFF", message: "Bluetooth is not powered on.", details: nil)); return
        }
        guard let args = call.arguments as? [String: Any],
              let address = args["address"] as? String,
              let uuid = UUID(uuidString: address) else {
            result(FlutterError(code: "IOS_BLE_ADDRESS", message: "A Core Bluetooth peripheral UUID is required.", details: nil)); return
        }
        let peripheral = discovered[uuid] ?? central?.retrievePeripherals(withIdentifiers: [uuid]).first
        guard let peripheral else {
            result(FlutterError(code: "IOS_BLE_NOT_FOUND", message: "vLinker MS BLE peripheral is no longer available. Scan again.", details: nil)); return
        }
        activePeripheral = peripheral
        peripheral.delegate = self
        connectResult = result
        central?.connect(peripheral, options: nil)
    }

    private func writeBle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        guard let peripheral = activePeripheral, let characteristic = txCharacteristic else {
            result(FlutterError(code: "IOS_BLE_NOT_CONNECTED", message: "vLinker MS BLE transport is not connected.", details: nil)); return
        }
        let data: Data
        if let typed = call.arguments as? FlutterStandardTypedData { data = typed.data }
        else if let bytes = call.arguments as? [UInt8] { data = Data(bytes) }
        else {
            result(FlutterError(code: "IOS_BLE_WRITE", message: "Expected byte data.", details: nil)); return
        }
        let type: CBCharacteristicWriteType = characteristic.properties.contains(.writeWithoutResponse) ? .withoutResponse : .withResponse
        peripheral.writeValue(data, for: characteristic, type: type)
        result(nil)
    }

    private func closeBle() {
        if let peripheral = activePeripheral { central?.cancelPeripheralConnection(peripheral) }
        activePeripheral = nil; rxCharacteristic = nil; txCharacteristic = nil
        if let pending = connectResult {
            connectResult = nil
            pending(FlutterError(code: "IOS_BLE_CLOSED", message: "BLE connection closed.", details: nil))
        }
    }

    public func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink) -> FlutterError? {
        bytesSink = events; return nil
    }

    public func onCancel(withArguments arguments: Any?) -> FlutterError? {
        bytesSink = nil; return nil
    }

    private func stateName(_ s: CBManagerState) -> String {
        switch s { case .poweredOn: return "poweredOn"; case .poweredOff: return "poweredOff"; case .unauthorized: return "unauthorized"; case .unsupported: return "unsupported"; case .resetting: return "resetting"; default: return "unknown" }
    }
    private func peripheralState(_ s: CBPeripheralState) -> String {
        switch s { case .connected: return "connected"; case .connecting: return "connecting"; case .disconnecting: return "disconnecting"; default: return "disconnected" }
    }
}
