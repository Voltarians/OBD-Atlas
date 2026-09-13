import 'dart:async';
import 'dart:typed_data';

import 'package:atlas_canalystii/atlas_canalystii.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

class CanalystiiAdapter implements AtlasAdapter {
  CanalystiiAdapter(this.device, {required this.bitrate, this.baseChannel = 2});

  final CanalystiiDevice device;
  final int bitrate;
  final int baseChannel;

  final _frames = StreamController<CanFrame>.broadcast();
  final _states = StreamController<AtlasAdapterState>.broadcast();
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  bool _running = false;
  Future<void>? _pollTask;

  static Future<List<CanalystiiDevice>> availableDevices() => AtlasCanalystii.scan();

  @override
  String get id => device.path;

  @override
  String get displayName => device.label;

  @override
  String get transport => 'CANalyst-II WinUSB';

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
    _setState(AtlasAdapterState.connecting);
    try {
      await AtlasCanalystii.connect(device.path, bitrate);
      _running = true;
      _setState(AtlasAdapterState.connected);
      _pollTask = _poll();
    } catch (_) {
      _setState(AtlasAdapterState.error);
      rethrow;
    }
  }

  Future<void> _poll() async {
    try {
      while (_running) {
        for (var physical = 0; physical < 2 && _running; physical++) {
          final data = await AtlasCanalystii.readFrames(physical);
          if (data != null && data.isNotEmpty) {
            _parseBuffers(data, baseChannel + physical);
          }
        }
        await Future<void>.delayed(const Duration(milliseconds: 1));
      }
    } catch (error, stack) {
      if (_running) {
        _setState(AtlasAdapterState.error);
        _frames.addError(error, stack);
      }
    }
  }

  void _parseBuffers(Uint8List data, int logicalChannel) {
    final bd = ByteData.sublistView(data);
    for (var base = 0; base + 64 <= data.length; base += 64) {
      final count = data[base];
      if (count > 3) continue;
      for (var i = 0; i < count; i++) {
        final off = base + 1 + i * 21;
        if (off + 21 > data.length) break;
        final canId = bd.getUint32(off, Endian.little);
        final remote = data[off + 10] != 0;
        final extended = data[off + 11] != 0;
        final len = data[off + 12].clamp(0, 8);
        final payload = Uint8List.fromList(data.sublist(off + 13, off + 13 + len));
        _frames.add(CanFrame(
          timestamp: DateTime.now(),
          channel: logicalChannel,
          id: canId,
          extended: extended,
          remote: remote,
          data: payload,
        ));
      }
    }
  }

  @override
  Future<void> disconnect() async {
    _running = false;
    await _pollTask;
    _pollTask = null;
    try {
      await AtlasCanalystii.disconnect();
    } finally {
      _setState(AtlasAdapterState.disconnected);
    }
  }
}
