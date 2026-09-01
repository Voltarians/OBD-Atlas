import 'dart:io';

import 'package:flutter/services.dart';

class AtlasLysUsbcan {
  static const MethodChannel _channel = MethodChannel('obd_atlas/lys_usbcan');

  // On Windows the direct WinUSB connect path already performs the definitive
  // device/interface open. Avoid a probe open+close cycle immediately before
  // connect, because some 0471:1200 adapters do not respond on EP0x81 after a
  // rapid WinUSB reopen. The native connect call remains the real detection
  // and will return a useful error if the adapter is absent or incompatible.
  static Future<bool> probe() async {
    if (Platform.isWindows) return true;
    return await _channel.invokeMethod<bool>('probe') ?? false;
  }

  static Future<void> connect({
    int bitrate = 500000,
    int deviceIndex = -1,
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
