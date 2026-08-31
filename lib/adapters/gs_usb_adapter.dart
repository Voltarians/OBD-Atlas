import 'dart:async';
import 'dart:typed_data';

import 'package:atlas_gs_usb/atlas_gs_usb.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

class GsUsbAdapter implements AtlasAdapter {
  GsUsbAdapter(this.device, {this.bitrate = 500000, this.channel = 1});

  final GsUsbDevice device;
  final int bitrate;
  final int channel;

  final _frames = StreamController<CanFrame>.broadcast();
  final _states = StreamController<AtlasAdapterState>.broadcast();
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  bool _polling = false;

  static Future<List<GsUsbDevice>> availableDevices() => AtlasGsUsb.scan();

  @override
  String get id => device.path;

  @override
  String get displayName => device.label;

  @override
  String get transport => 'candleLight / gs_usb';

  @override
  AtlasAdapterState get state => _state;

  @override
  Stream<CanFrame> get frames => _frames.stream;

  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  void _setState(AtlasAdapterState value) {
    _state = value;
    _states.add(value);
  }

  @override
  Future<void> connect() async {
    if (_state == AtlasAdapterState.connected) return;
    _setState(AtlasAdapterState.connecting);
    try {
      await AtlasGsUsb.connect(device.path, bitrate: bitrate);
      _setState(AtlasAdapterState.connected);
      _polling = true;
      unawaited(_readLoop());
    } catch (_) {
      _setState(AtlasAdapterState.error);
      rethrow;
    }
  }

  Future<void> _readLoop() async {
    while (_polling && _state == AtlasAdapterState.connected) {
      try {
        final packet = await AtlasGsUsb.readFrame();
        if (!_polling) break;
        if (packet == null || packet.length < 20) {
          await Future<void>.delayed(const Duration(milliseconds: 1));
          continue;
        }
        for (var offset = 0; offset + 20 <= packet.length; offset += 20) {
          final frame = _decode(packet, offset);
          if (frame != null) _frames.add(frame);
        }
      } catch (error, stackTrace) {
        if (!_polling) break;
        _frames.addError(error, stackTrace);
        _setState(AtlasAdapterState.error);
        _polling = false;
      }
    }
  }

  CanFrame? _decode(Uint8List packet, int offset) {
    final bytes = ByteData.sublistView(packet, offset, offset + 20);
    final echoId = bytes.getUint32(0, Endian.little);
    if (echoId != 0xFFFFFFFF) return null; // TX echo, not a received bus frame.

    final rawId = bytes.getUint32(4, Endian.little);
    const effFlag = 0x80000000;
    const rtrFlag = 0x40000000;
    const errFlag = 0x20000000;
    if ((rawId & errFlag) != 0) return null;

    final extended = (rawId & effFlag) != 0;
    final remote = (rawId & rtrFlag) != 0;
    final id = rawId & (extended ? 0x1FFFFFFF : 0x7FF);
    final dlc = bytes.getUint8(8).clamp(0, 8);
    final data = remote
        ? <int>[]
        : List<int>.generate(dlc, (index) => bytes.getUint8(12 + index), growable: false);

    return CanFrame(
      timestamp: DateTime.now(),
      id: id,
      data: data,
      extended: extended,
      remote: remote,
      channel: channel,
    );
  }

  @override
  Future<void> disconnect() async {
    _polling = false;
    try {
      await AtlasGsUsb.disconnect();
    } finally {
      _setState(AtlasAdapterState.disconnected);
    }
  }
}
