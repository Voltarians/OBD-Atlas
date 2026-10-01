import CoreBluetooth
import Flutter
import UIKit

public final class AtlasAndroidRfcommPlugin: NSObject, FlutterPlugin, CBCentralManagerDelegate {
    private var central: CBCentralManager?
    private var probeResult: FlutterResult?
    private var discovered: [UUID: CBPeripheral] = [:]
    private var timeoutWorkItem: DispatchWorkItem?

    public static func register(with registrar: FlutterPluginRegistrar) {
        let channel = FlutterMethodChannel(
            name: "obd_atlas/android_rfcomm",
            binaryMessenger: registrar.messenger()
        )
        let instance = AtlasAndroidRfcommPlugin()
        registrar.addMethodCallDelegate(instance, channel: channel)
    }

    public func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        switch call.method {
        case "requestConnectPermission":
            ensureCentral()
            // Instantiating CBCentralManager triggers the iOS Bluetooth privacy prompt
            // when required. The actual powered-on state arrives asynchronously.
            result(true)

        case "pairedDevices":
            // iOS doesn't expose a Windows/Android style paired RFCOMM device list.
            // Return probe observations instead of pretending a COM/SPP endpoint exists.
            result(discovered.values.map(deviceMap))

        case "probeClassicDevices":
            startClassicGattProbe(call, result: result)

        case "connect":
            result(FlutterError(
                code: "IOS_SPP_UNAVAILABLE",
                message: "Core Bluetooth Classic exposes GATT over BR/EDR, not arbitrary RFCOMM/SPP. The vLinker MS SPP serial channel is not available through this probe.",
                details: nil
            ))

        case "write":
            result(FlutterError(
                code: "IOS_SPP_UNAVAILABLE",
                message: "No iOS RFCOMM/SPP stream is open. Core Bluetooth Classic is GATT-based.",
                details: nil
            ))

        case "close":
            finishProbe()
            result(nil)

        default:
            result(FlutterMethodNotImplemented)
        }
    }

    private func ensureCentral() {
        if central == nil {
            central = CBCentralManager(delegate: self, queue: DispatchQueue.main)
        }
    }

    private func startClassicGattProbe(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        if probeResult != nil {
            result(FlutterError(
                code: "PROBE_BUSY",
                message: "A Core Bluetooth Classic probe is already running.",
                details: nil
            ))
            return
        }

        ensureCentral()
        discovered.removeAll()

        let args = call.arguments as? [String: Any]
        let timeoutSeconds = max(1.0, min((args?["timeoutSeconds"] as? Double) ?? 8.0, 30.0))

        probeResult = result

        // A nil filter asks Core Bluetooth to report matching connection events broadly.
        // For BR/EDR, Core Bluetooth only surfaces peers that participate in GATT.
        if #available(iOS 13.0, *) {
            central?.registerForConnectionEvents(options: nil)
        }

        let work = DispatchWorkItem { [weak self] in
            self?.completeProbe()
        }
        timeoutWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + timeoutSeconds, execute: work)
    }

    private func finishProbe() {
        timeoutWorkItem?.cancel()
        timeoutWorkItem = nil
        if #available(iOS 13.0, *) {
            central?.registerForConnectionEvents(options: [:])
        }
        probeResult = nil
    }

    private func completeProbe() {
        guard let result = probeResult else { return }
        timeoutWorkItem?.cancel()
        timeoutWorkItem = nil
        probeResult = nil

        let devices = discovered.values
            .sorted { ($0.name ?? "").localizedCaseInsensitiveCompare($1.name ?? "") == .orderedAscending }
            .map(deviceMap)
        result(devices)
    }

    private func deviceMap(_ peripheral: CBPeripheral) -> [String: Any] {
        return [
            "name": peripheral.name ?? "",
            "address": peripheral.identifier.uuidString,
            "transport": "corebluetooth-br-edr-gatt"
        ]
    }

    public func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard let result = probeResult else { return }
        switch central.state {
        case .poweredOn:
            break
        case .unauthorized:
            timeoutWorkItem?.cancel()
            timeoutWorkItem = nil
            probeResult = nil
            result(FlutterError(
                code: "BLUETOOTH_PERMISSION",
                message: "Bluetooth access is not authorized for OBD Atlas.",
                details: nil
            ))
        case .unsupported:
            timeoutWorkItem?.cancel()
            timeoutWorkItem = nil
            probeResult = nil
            result(FlutterError(
                code: "BLUETOOTH_UNSUPPORTED",
                message: "Core Bluetooth is not supported on this device.",
                details: nil
            ))
        case .poweredOff:
            timeoutWorkItem?.cancel()
            timeoutWorkItem = nil
            probeResult = nil
            result(FlutterError(
                code: "BLUETOOTH_OFF",
                message: "Bluetooth is turned off.",
                details: nil
            ))
        default:
            break
        }
    }

    @available(iOS 13.0, *)
    public func centralManager(
        _ central: CBCentralManager,
        connectionEventDidOccur event: CBConnectionEvent,
        for peripheral: CBPeripheral
    ) {
        if event == .peerConnected {
            discovered[peripheral.identifier] = peripheral
        }
    }
}
