import 'dart:typed_data';

import 'package:flutter/services.dart';

class GsUsbDevice {
  const GsUsbDevice({required this.path, required this.label});

  final String path;
  final String label;

  factory GsUsbDevice.fromMap(Map<Object?, Object?> map) => GsUsbDevice(
        path: map['path']! as String,
        label: (map['label'] as String?) ?? 'candleLight / gs_usb',
      );
}

class AtlasGsUsb {
  static const MethodChannel _channel = MethodChannel('obd_atlas/gs_usb');

  static Future<List<GsUsbDevice>> scan() async {
    final raw = await _channel.invokeListMethod<Object?>('scan') ?? const [];
    return raw
        .whereType<Map<Object?, Object?>>()
        .map(GsUsbDevice.fromMap)
        .toList(growable: false);
  }

  static Future<void> connect(String path, {int bitrate = 500000}) async {
    await _channel.invokeMethod<void>('connect', <String, Object?>{
      'path': path,
      'bitrate': bitrate,
    });
  }

  static Future<Uint8List?> readFrame() async {
    return _channel.invokeMethod<Uint8List>('readFrame');
  }

  static Future<void> disconnect() async {
    await _channel.invokeMethod<void>('disconnect');
  }
}
