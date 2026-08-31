import 'package:flutter/services.dart';

class AtlasLysUsbcan {
  static const MethodChannel _channel = MethodChannel('obd_atlas/lys_usbcan');

  static Future<bool> probe() async =>
      await _channel.invokeMethod<bool>('probe') ?? false;

  static Future<void> connect({
    int bitrate = 500000,
    int deviceIndex = 0,
  }) =>
      _channel.invokeMethod<void>('connect', {
        'bitrate': bitrate,
        'deviceIndex': deviceIndex,
      });

  static Future<void> disconnect() =>
      _channel.invokeMethod<void>('disconnect');

  static Future<Uint8List?> readFrames(int channel) =>
      _channel.invokeMethod<Uint8List>('readFrames', {'channel': channel});
}
