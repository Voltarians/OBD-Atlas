import 'package:flutter/services.dart';

class CanalystiiDevice {
  const CanalystiiDevice({required this.path, required this.label});
  final String path;
  final String label;
}

class AtlasCanalystii {
  static const MethodChannel _channel = MethodChannel('obd_atlas/canalystii');

  static Future<List<CanalystiiDevice>> scan() async {
    final raw = await _channel.invokeMethod<List<dynamic>>('scan') ?? const [];
    return raw.map((item) {
      final map = Map<dynamic, dynamic>.from(item as Map);
      return CanalystiiDevice(path: map['path'] as String, label: map['label'] as String);
    }).toList();
  }

  static Future<void> connect(String path, int bitrate) =>
      _channel.invokeMethod<void>('connect', {'path': path, 'bitrate': bitrate});

  static Future<void> disconnect() => _channel.invokeMethod<void>('disconnect');

  static Future<Uint8List?> readFrames(int channel) async {
    final data = await _channel.invokeMethod<Uint8List>('readFrames', {'channel': channel});
    return data;
  }
}
