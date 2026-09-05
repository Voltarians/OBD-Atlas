import 'dart:async';
import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';
import 'linux_uc2_adapter.dart';

final class _VciInitConfig extends Struct {
  @Uint32()
  external int accCode;

  @Uint32()
  external int accMask;

  @Uint32()
  external int reserved;

  @Uint8()
  external int filter;

  @Uint8()
  external int timing0;

  @Uint8()
  external int timing1;

  @Uint8()
  external int mode;
}

final class _VciCanObj extends Struct {
  @Uint32()
  external int id;

  @Uint32()
  external int timeStamp;

  @Uint8()
  external int timeFlag;

  @Uint8()
  external int sendType;

  @Uint8()
  external int remoteFlag;

  @Uint8()
  external int externFlag;

  @Uint8()
  external int dataLen;

  @Array(8)
  external Array<Uint8> data;

  @Array(3)
  external Array<Uint8> reserved;
}

typedef _OpenNative = Uint32 Function(Uint32, Uint32, Uint32);
typedef _OpenDart = int Function(int, int, int);
typedef _CloseNative = Uint32 Function(Uint32, Uint32);
typedef _CloseDart = int Function(int, int);
typedef _InitNative = Uint32 Function(Uint32, Uint32, Uint32, Pointer<_VciInitConfig>);
typedef _InitDart = int Function(int, int, int, Pointer<_VciInitConfig>);
typedef _StartNative = Uint32 Function(Uint32, Uint32, Uint32);
typedef _StartDart = int Function(int, int, int);
typedef _ResetNative = Uint32 Function(Uint32, Uint32, Uint32);
typedef _ResetDart = int Function(int, int, int);
typedef _ReceiveNumNative = Uint32 Function(Uint32, Uint32, Uint32);
typedef _ReceiveNumDart = int Function(int, int, int);
typedef _ReceiveNative = Uint32 Function(
  Uint32,
  Uint32,
  Uint32,
  Pointer<_VciCanObj>,
  Uint32,
  Int32,
);
typedef _ReceiveDart = int Function(
  int,
  int,
  int,
  Pointer<_VciCanObj>,
  int,
  int,
);

/// Coordinated Linux session for two USBCAN2 adapters.
///
/// Each physical USBCAN2 exposes CAN0 and CAN1, giving PCG-1 four classic
/// CAN channels from two USB adapters. The vendor library behaves best when
/// the whole set is opened/configured before receive polling begins.
class LinuxUc2PairAdapter implements AtlasAdapter {
  LinuxUc2PairAdapter({
    required this.bitrate,
    this.baseChannel = 1,
    this.firstDeviceIndex = 0,
    this.secondDeviceIndex = 1,
  });

  static const int deviceType = 4;
  static const int _maxReceiveBatch = 256;

  final int bitrate;
  final int baseChannel;
  final int firstDeviceIndex;
  final int secondDeviceIndex;

  final _frames = StreamController<CanFrame>.broadcast();
  final _states = StreamController<AtlasAdapterState>.broadcast();
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  bool _running = false;
  Future<void>? _pollTask;
  DynamicLibrary? _library;
  final List<int> _openedDevices = <int>[];

  late _OpenDart _openDevice;
  late _CloseDart _closeDevice;
  late _InitDart _initCan;
  late _StartDart _startCan;
  late _ResetDart _resetCan;
  late _ReceiveNumDart _getReceiveNum;
  late _ReceiveDart _receive;

  @override
  String get id => 'linux-uc2-pair-$firstDeviceIndex-$secondDeviceIndex';

  @override
  String get displayName => 'Dual UC2 / LYS USBCAN • 4 CAN';

  @override
  String get transport => 'Native Linux ARM64 libusbcan • coordinated 4-channel session';

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

  ({int timing0, int timing1}) _timingForBitrate() {
    switch (bitrate) {
      case 125000:
        return (timing0: 0x03, timing1: 0x1c);
      case 250000:
        return (timing0: 0x01, timing1: 0x1c);
      case 500000:
        return (timing0: 0x00, timing1: 0x1c);
      case 800000:
        return (timing0: 0x00, timing1: 0x16);
      case 1000000:
        return (timing0: 0x00, timing1: 0x14);
      default:
        throw ArgumentError.value(bitrate, 'bitrate', 'Unsupported UC2 bitrate.');
    }
  }

  void _bind(DynamicLibrary library) {
    _openDevice = library.lookupFunction<_OpenNative, _OpenDart>('VCI_OpenDevice');
    _closeDevice = library.lookupFunction<_CloseNative, _CloseDart>('VCI_CloseDevice');
    _initCan = library.lookupFunction<_InitNative, _InitDart>('VCI_InitCAN');
    _startCan = library.lookupFunction<_StartNative, _StartDart>('VCI_StartCAN');
    _resetCan = library.lookupFunction<_ResetNative, _ResetDart>('VCI_ResetCAN');
    _getReceiveNum = library.lookupFunction<_ReceiveNumNative, _ReceiveNumDart>('VCI_GetReceiveNum');
    _receive = library.lookupFunction<_ReceiveNative, _ReceiveDart>('VCI_Receive');
  }

  @override
  Future<void> connect() async {
    if (_state == AtlasAdapterState.connected) return;
    if (!Platform.isLinux) throw UnsupportedError('Dual UC2 session is Linux-only.');

    _setState(AtlasAdapterState.connecting);
    try {
      final libraryPath = LinuxUc2Adapter.findLibraryPath();
      if (libraryPath == null) {
        throw StateError('ARM64 libusbcan.so was not found.');
      }
      final library = DynamicLibrary.open(libraryPath);
      _library = library;
      _bind(library);

      final devices = <int>[firstDeviceIndex, secondDeviceIndex];
      final timing = _timingForBitrate();

      // Open both USB devices first, matching the PCG-1 bench sequence.
      for (final device in devices) {
        final openResult = _openDevice(deviceType, device, 0);
        if (openResult != 1) {
          throw StateError('VCI_OpenDevice failed for UC2 device $device.');
        }
        _openedDevices.add(device);
      }

      // Initialize CAN0 and CAN1 on both USBCAN2 devices before starting any
      // receive polling.
      for (final device in devices) {
        for (final physicalChannel in const <int>[0, 1]) {
          final config = calloc<_VciInitConfig>();
          try {
            config.ref
              ..accCode = 0
              ..accMask = 0xffffffff
              ..reserved = 0
              ..filter = 1
              ..timing0 = timing.timing0
              ..timing1 = timing.timing1
              ..mode = 0;
            final initResult = _initCan(deviceType, device, physicalChannel, config);
            if (initResult != 1) {
              throw StateError('VCI_InitCAN failed for UC2 device $device CAN$physicalChannel.');
            }
          } finally {
            calloc.free(config);
          }
        }
      }

      for (final device in devices) {
        for (final physicalChannel in const <int>[0, 1]) {
          final startResult = _startCan(deviceType, device, physicalChannel);
          if (startResult != 1) {
            throw StateError('VCI_StartCAN failed for UC2 device $device CAN$physicalChannel.');
          }
        }
      }

      // Begin polling only after all four controllers are running.
      _running = true;
      _setState(AtlasAdapterState.connected);
      _pollTask = _pollAllFour();
    } catch (_) {
      _setState(AtlasAdapterState.error);
      await _closeOpened();
      rethrow;
    }
  }

  Future<void> _pollAllFour() async {
    final firstCan0 = calloc<_VciCanObj>(_maxReceiveBatch);
    final firstCan1 = calloc<_VciCanObj>(_maxReceiveBatch);
    final secondCan0 = calloc<_VciCanObj>(_maxReceiveBatch);
    final secondCan1 = calloc<_VciCanObj>(_maxReceiveBatch);
    try {
      while (_running) {
        var gotAny = false;
        gotAny |= _pollOne(firstDeviceIndex, 0, baseChannel, firstCan0);
        gotAny |= _pollOne(firstDeviceIndex, 1, baseChannel + 1, firstCan1);
        gotAny |= _pollOne(secondDeviceIndex, 0, baseChannel + 2, secondCan0);
        gotAny |= _pollOne(secondDeviceIndex, 1, baseChannel + 3, secondCan1);
        await Future<void>.delayed(
          gotAny ? Duration.zero : const Duration(milliseconds: 2),
        );
      }
    } catch (error, stack) {
      if (_running) {
        _setState(AtlasAdapterState.error);
        _frames.addError(error, stack);
      }
    } finally {
      calloc.free(firstCan0);
      calloc.free(firstCan1);
      calloc.free(secondCan0);
      calloc.free(secondCan1);
    }
  }

  bool _pollOne(
    int device,
    int physicalChannel,
    int logicalChannel,
    Pointer<_VciCanObj> buffer,
  ) {
    final pending = _getReceiveNum(deviceType, device, physicalChannel);
    if (pending <= 0) return false;
    final requested = pending.clamp(1, _maxReceiveBatch);
    final received = _receive(
      deviceType,
      device,
      physicalChannel,
      buffer,
      requested,
      0,
    );
    if (received <= 0) return false;

    for (var index = 0; index < received; index++) {
      final raw = buffer[index];
      final dlc = raw.dataLen.clamp(0, 8);
      final payload = <int>[for (var i = 0; i < dlc; i++) raw.data[i]];
      _frames.add(
        CanFrame(
          timestamp: DateTime.now(),
          channel: logicalChannel,
          id: raw.id,
          extended: raw.externFlag != 0,
          remote: raw.remoteFlag != 0,
          data: payload,
        ),
      );
    }
    return true;
  }

  Future<void> _closeOpened() async {
    for (final device in _openedDevices.reversed) {
      for (final physicalChannel in const <int>[1, 0]) {
        try {
          _resetCan(deviceType, device, physicalChannel);
        } catch (_) {}
      }
      try {
        _closeDevice(deviceType, device);
      } catch (_) {}
    }
    _openedDevices.clear();
  }

  @override
  Future<void> disconnect() async {
    _running = false;
    await _pollTask;
    _pollTask = null;
    await _closeOpened();
    _library = null;
    _setState(AtlasAdapterState.disconnected);
  }
}
