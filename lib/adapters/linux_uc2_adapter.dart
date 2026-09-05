import 'dart:async';
import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

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

class LinuxUc2Adapter implements AtlasAdapter {
  LinuxUc2Adapter({
    required this.deviceIndex,
    required this.bitrate,
    required this.channel,
    this.physicalCanChannel = 0,
  });

  static const int deviceType = 4; // ZLG/LYS USBCAN2
  static const int _maxReceiveBatch = 256;

  final int deviceIndex;
  final int bitrate;
  final int channel;
  final int physicalCanChannel;

  final StreamController<CanFrame> _frames = StreamController<CanFrame>.broadcast();
  final StreamController<AtlasAdapterState> _states = StreamController<AtlasAdapterState>.broadcast();

  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  bool _running = false;
  bool _opened = false;
  Future<void>? _receiveTask;
  DynamicLibrary? _library;

  late _OpenDart _openDevice;
  late _CloseDart _closeDevice;
  late _InitDart _initCan;
  late _StartDart _startCan;
  late _ResetDart _resetCan;
  late _ReceiveNumDart _getReceiveNum;
  late _ReceiveDart _receive;

  @override
  String get id => 'linux-uc2-$deviceIndex-can$physicalCanChannel';

  @override
  String get displayName => 'UC2 / LYS USBCAN • device $deviceIndex';

  @override
  String get transport => 'Native Linux ARM64 libusbcan';

  @override
  AtlasAdapterState get state => _state;

  @override
  Stream<CanFrame> get frames => _frames.stream;

  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  static String? findLibraryPath() {
    if (!Platform.isLinux) return null;
    final override = Platform.environment['OBD_ATLAS_USBCAN_LIB'];
    final home = Platform.environment['HOME'];
    final candidates = <String>[
      if (override != null && override.isNotEmpty) override,
      if (home != null && home.isNotEmpty)
        '$home/promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so',
      '/usr/local/lib/libusbcan.so',
      '/usr/lib/aarch64-linux-gnu/libusbcan.so',
    ];
    for (final candidate in candidates) {
      if (File(candidate).existsSync()) return candidate;
    }
    return null;
  }

  static Future<List<int>> availableDeviceIndices() async {
    if (!Platform.isLinux) return const <int>[];
    try {
      final result = await Process.run('lsusb', const <String>[]);
      if (result.exitCode != 0) return const <int>[];
      final matches = result.stdout
          .toString()
          .split('\n')
          .where((line) => line.toLowerCase().contains('0471:1200'))
          .toList();
      return List<int>.generate(matches.length, (index) => index);
    } catch (_) {
      return const <int>[];
    }
  }

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
        throw ArgumentError.value(
          bitrate,
          'bitrate',
          'UC2 Linux transport currently supports 125k, 250k, 500k, 800k and 1M bit/s.',
        );
    }
  }

  void _bindLibrary(DynamicLibrary library) {
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
    if (!Platform.isLinux) {
      throw UnsupportedError('Native UC2 transport is available only on Linux.');
    }

    _setState(AtlasAdapterState.connecting);
    try {
      final libraryPath = findLibraryPath();
      if (libraryPath == null) {
        throw StateError(
          'libusbcan.so was not found. Set OBD_ATLAS_USBCAN_LIB or install the ARM64 library under ~/promethean/rust-can-zlg-lib/library/linux/aarch64/.',
        );
      }

      final library = DynamicLibrary.open(libraryPath);
      _library = library;
      _bindLibrary(library);

      final openResult = _openDevice(deviceType, deviceIndex, 0);
      if (openResult != 1) {
        throw StateError(
          'VCI_OpenDevice failed for UC2 device $deviceIndex. Check USB permissions for 0471:1200.',
        );
      }
      _opened = true;

      final timing = _timingForBitrate();
      final config = calloc<_VciInitConfig>();
      try {
        config.ref
          ..accCode = 0x00000000
          ..accMask = 0xffffffff
          ..reserved = 0
          ..filter = 1
          ..timing0 = timing.timing0
          ..timing1 = timing.timing1
          ..mode = 0;

        final initResult = _initCan(
          deviceType,
          deviceIndex,
          physicalCanChannel,
          config,
        );
        if (initResult != 1) {
          throw StateError('VCI_InitCAN failed for UC2 device $deviceIndex CAN$physicalCanChannel.');
        }
      } finally {
        calloc.free(config);
      }

      final startResult = _startCan(deviceType, deviceIndex, physicalCanChannel);
      if (startResult != 1) {
        throw StateError('VCI_StartCAN failed for UC2 device $deviceIndex CAN$physicalCanChannel.');
      }

      _running = true;
      _setState(AtlasAdapterState.connected);
      _receiveTask = _pollReceive();
    } catch (_) {
      _setState(AtlasAdapterState.error);
      if (_opened) {
        try {
          _closeDevice(deviceType, deviceIndex);
        } catch (_) {}
        _opened = false;
      }
      rethrow;
    }
  }

  Future<void> _pollReceive() async {
    final buffer = calloc<_VciCanObj>(_maxReceiveBatch);
    try {
      while (_running) {
        final pending = _getReceiveNum(deviceType, deviceIndex, physicalCanChannel);
        if (pending <= 0) {
          await Future<void>.delayed(const Duration(milliseconds: 2));
          continue;
        }

        final requested = pending.clamp(1, _maxReceiveBatch);
        final received = _receive(
          deviceType,
          deviceIndex,
          physicalCanChannel,
          buffer,
          requested,
          0,
        );

        if (received <= 0) {
          await Future<void>.delayed(const Duration(milliseconds: 1));
          continue;
        }

        for (var index = 0; index < received; index++) {
          final raw = buffer[index];
          final dlc = raw.dataLen.clamp(0, 8);
          final payload = <int>[
            for (var i = 0; i < dlc; i++) raw.data[i],
          ];
          _frames.add(
            CanFrame(
              timestamp: DateTime.now(),
              id: raw.id,
              data: payload,
              extended: raw.externFlag != 0,
              remote: raw.remoteFlag != 0,
              channel: channel,
            ),
          );
        }

        await Future<void>.delayed(Duration.zero);
      }
    } catch (error, stack) {
      if (_running) {
        _setState(AtlasAdapterState.error);
        _frames.addError(error, stack);
      }
    } finally {
      calloc.free(buffer);
    }
  }

  @override
  Future<void> disconnect() async {
    _running = false;
    await _receiveTask;
    _receiveTask = null;

    if (_opened) {
      try {
        _resetCan(deviceType, deviceIndex, physicalCanChannel);
      } catch (_) {}
      try {
        _closeDevice(deviceType, deviceIndex);
      } finally {
        _opened = false;
      }
    }
    _library = null;
    _setState(AtlasAdapterState.disconnected);
  }
}
