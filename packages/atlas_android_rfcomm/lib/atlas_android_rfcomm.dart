import 'package:flutter/services.dart';

class AndroidRfcommDevice {
  const AndroidRfcommDevice({
    required this.name,
    required this.address,
    this.transport,
  });

  final String name;
  final String address;
  final String? transport;

  String get label => '${name.isEmpty ? 'Bluetooth device' : name} • $address';

  factory AndroidRfcommDevice.fromMap(Map<Object?, Object?> map) =>
      AndroidRfcommDevice(
        name: (map['name'] as String?) ?? '',
        address: map['address']! as String,
        transport: map['transport'] as String?,
      );
}

class AtlasAndroidRfcomm {
  static const MethodChannel _channel =
      MethodChannel('obd_atlas/android_rfcomm');
  static const EventChannel _bytes =
      EventChannel('obd_atlas/android_rfcomm_bytes');

  static Stream<Uint8List> get bytes => _bytes.receiveBroadcastStream().map(
        (event) => event is Uint8List
            ? event
            : Uint8List.fromList((event as List).cast<int>()),
      );

  static Future<bool> requestConnectPermission() async {
    return await _channel.invokeMethod<bool>('requestConnectPermission') ?? false;
  }

  static Future<List<AndroidRfcommDevice>> pairedDevices() async {
    final raw =
        await _channel.invokeListMethod<Object?>('pairedDevices') ?? const [];
    return raw
        .whereType<Map<Object?, Object?>>()
        .map(AndroidRfcommDevice.fromMap)
        .toList(growable: false);
  }

  static Future<List<AndroidRfcommDevice>> probeClassicDevices({
    double timeoutSeconds = 8,
  }) async {
    final raw = await _channel.invokeListMethod<Object?>(
          'probeClassicDevices',
          <String, Object?>{'timeoutSeconds': timeoutSeconds},
        ) ??
        const [];
    return raw
        .whereType<Map<Object?, Object?>>()
        .map(AndroidRfcommDevice.fromMap)
        .toList(growable: false);
  }

  static Future<void> connect(String address) =>
      _channel.invokeMethod<void>('connect', <String, Object?>{
        'address': address,
      });

  static Future<void> write(Uint8List bytes) =>
      _channel.invokeMethod<void>('write', bytes);

  static Future<void> close() => _channel.invokeMethod<void>('close');
}
