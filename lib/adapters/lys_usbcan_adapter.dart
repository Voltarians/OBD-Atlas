import 'dart:async';
import 'dart:typed_data';

import 'package:atlas_lys_usbcan/atlas_lys_usbcan.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

class LysUsbcanAdapter implements AtlasAdapter {
  LysUsbcanAdapter({required this.bitrate, this.baseChannel = 4, this.deviceIndex = 0});

  final int bitrate;
  final int baseChannel;
  final int deviceIndex;

  final _frames = StreamController<CanFrame>.broadcast();
  final _states = StreamController<AtlasAdapterState>.broadcast();
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  bool _running = false;
  Future<void>? _pollTask;

  static Future<bool> probe() => AtlasLysUsbcan.probe();

  @override
  String get id => 'lys-usbcan-$deviceIndex';

  @override
  String get displayName => 'LYS USBCAN-II • 0471:1200';

  @override
  String get transport => 'ControlCAN VCI native';

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
      await AtlasLysUsbcan.connect(
        bitrate: bitrate,
        deviceIndex: deviceIndex,
      );
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
        var gotAny = false;
        for (var physical = 0; physical < 2 && _running; physical++) {
          final data = await AtlasLysUsbcan.readFrames(physical);
          if (data != null && data.isNotEmpty) {
            gotAny = true;
            _parseFrames(data, baseChannel + physical);
          }
        }
        await Future<void>.delayed(
          gotAny ? Duration.zero : const Duration(milliseconds: 1),
        );
      }
    } catch (error, stack) {
      if (_running) {
        _setState(AtlasAdapterState.error);
        _frames.addError(error, stack);
      }
    }
  }

  void _parseFrames(Uint8List data, int logicalChannel) {
    const recordSize = 24;
    final bd = ByteData.sublistView(data);
    for (var offset = 0; offset + recordSize <= data.length; offset += recordSize) {
      final canId = bd.getUint32(offset, Endian.little);
      final remote = data[offset + 10] != 0;
      final extended = data[offset + 11] != 0;
      final dlc = data[offset + 12].clamp(0, 8);
      final payload = Uint8List.fromList(
        data.sublist(offset + 13, offset + 13 + dlc),
      );
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

  @override
  Future<void> disconnect() async {
    _running = false;
    await _pollTask;
    _pollTask = null;
    try {
      await AtlasLysUsbcan.disconnect();
    } finally {
      _setState(AtlasAdapterState.disconnected);
    }
  }
}
