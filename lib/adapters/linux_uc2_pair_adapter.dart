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

class LinuxUc2PairAdapter implements AtlasAdapter {
  LinuxUc2PairAdapter({
    required this.bitrate,
    this.baseChannel = 1,
    this.firstDeviceIndex = 0,
    this.secondDeviceIndex = 1,
    this.physicalCanChannel = 0,
  });

  static const int deviceType = 4;
  static const int _maxReceiveBatch = 256;

  final int bitrate;
  final int baseChannel;
  final int firstDeviceIndex;
  final int secondDeviceIndex;
  final int physicalCanChannel;

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
  String get displayName => 'Dual UC2 / LYS USBCAN';

  @override
  String get transport => 'Native Linux ARM64 libusbcan • coordinated dual-device session';

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

      final timing = _timingForBitrate();
      for (final device in <int>[firstDeviceIndex, secondDeviceIndex]) {
        final openResult = _openDevice(deviceType, device, 0);
        if (openResult != 1) {
          throw StateError('VCI_OpenDevice failed for UC2 device $device.');
        }
        _openedDevices.add(device);

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
          final initResult = _initCan(deviceType, device, physicalCanChannel, config);
          if (initResult != 1) {
            throw StateError('VCI_InitCAN failed for UC2 device $device CAN$physicalCanChannel.');
          }
        } finally {
          calloc.free(config);
        }

        final startResult = _startCan(deviceType, device, physicalCanChannel);
        if (startResult != 1) {
          throw StateError('VCI_StartCAN failed for UC2 device $device CAN$physicalCanChannel.');
        }
      }

      // Do not begin receive polling until BOTH adapters have opened, initialized,
      // and started. This mirrors the bench sequence that succeeded on PCG-1.
      _running = true;
      _setState(AtlasAdapterState.connected);
      _pollTask = _pollBoth();
    } catch (_) {
      _setState(AtlasAdapterState.error);
      await _closeOpened();
      rethrow;
    }
  }

  Future<void> _pollBoth() async {
    final firstBuffer = calloc<_VciCanObj>(_maxReceiveBatch);
    final secondBuffer = calloc<_VciCanObj>(_maxReceiveBatch);
    try {
      while (_running) {
        var gotAny = false;
        gotAny |= _pollOne(firstDeviceIndex, baseChannel, firstBuffer);
        gotAny |= _pollOne(secondDeviceIndex, baseChannel + 1, secondBuffer);
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
      calloc.free(firstBuffer);
      calloc.free(secondBuffer);
    }
  }

  bool _pollOne(int device, int logicalChannel, Pointer<_VciCanObj> buffer) {
    final pending = _getReceiveNum(deviceType, device, physicalCanChannel);
    if (pending <= 0) return false;
    final requested = pending.clamp(1, _maxReceiveBatch);
    final received = _receive(
      deviceType,
      device,
      physicalCanChannel,
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
      try {
        _resetCan(deviceType, device, physicalCanChannel);
      } catch (_) {}
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
