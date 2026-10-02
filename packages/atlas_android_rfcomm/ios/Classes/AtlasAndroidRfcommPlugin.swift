import CoreBluetooth
import Flutter
import UIKit

public final class AtlasAndroidRfcommPlugin: NSObject, FlutterPlugin, CBCentralManagerDelegate, CBPeripheralDelegate {
    private var central: CBCentralManager?
    private var probeResult: FlutterResult?
    private var discovered: [UUID: CBPeripheral] = [:]
    private var reports: [UUID: [String: Any]] = [:]
    private var timeoutWorkItem: DispatchWorkItem?

    public static func register(with registrar: FlutterPluginRegistrar) {
        let channel = FlutterMethodChannel(name: "obd_atlas/android_rfcomm", binaryMessenger: registrar.messenger())
        let instance = AtlasAndroidRfcommPlugin()
        registrar.addMethodCallDelegate(instance, channel: channel)
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
        case "connect", "write":
            result(FlutterError(code: "IOS_SPP_UNAVAILABLE",
                message: "Core Bluetooth Classic is GATT over BR/EDR; it does not expose an arbitrary RFCOMM/SPP serial stream.",
                details: nil))
        case "close":
            finishProbe(); result(nil)
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
        guard probeResult != nil else { return }
        if central.state == .unauthorized || central.state == .unsupported || central.state == .poweredOff {
            completeProbe()
        }
    }

    @available(iOS 13.0, *)
    public func centralManager(_ central: CBCentralManager, connectionEventDidOccur event: CBConnectionEvent, for peripheral: CBPeripheral) {
        observe(peripheral, event: event == .peerConnected ? "peerConnected" : "peerDisconnected")
    }

    public func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        observe(peripheral, event: "didConnect")
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
        peripheral.services?.forEach { peripheral.discoverCharacteristics(nil, for: $0) }
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
    }

    private func stateName(_ s: CBManagerState) -> String {
        switch s { case .poweredOn: return "poweredOn"; case .poweredOff: return "poweredOff"; case .unauthorized: return "unauthorized"; case .unsupported: return "unsupported"; case .resetting: return "resetting"; default: return "unknown" }
    }
    private func peripheralState(_ s: CBPeripheralState) -> String {
        switch s { case .connected: return "connected"; case .connecting: return "connecting"; case .disconnecting: return "disconnecting"; default: return "disconnected" }
    }
}
