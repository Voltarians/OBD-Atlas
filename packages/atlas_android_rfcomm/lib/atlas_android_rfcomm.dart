import 'package:flutter/services.dart';

class AndroidRfcommDevice {
  const AndroidRfcommDevice({
    required this.name,
    required this.address,
  });

  final String name;
  final String address;

  String get label => '${name.isEmpty ? 'Bluetooth SPP' : name} • $address';

  factory AndroidRfcommDevice.fromMap(Map<Object?, Object?> map) =>
      AndroidRfcommDevice(
        name: (map['name'] as String?) ?? '',
        address: map['address']! as String,
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

  static Future<List<AndroidRfcommDevice>> pairedDevices() async {
    final raw =
        await _channel.invokeListMethod<Object?>('pairedDevices') ?? const [];
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
