import 'dart:async';
import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

const int _vciUsbCan2 = 4;
const int _statusOk = 1;

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
typedef _ReceiveNative = Uint32 Function(Uint32, Uint32, Uint32, Pointer<_VciCanObj>, Uint32, Int32);
typedef _ReceiveDart = int Function(int, int, int, Pointer<_VciCanObj>, int, int);

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
  DynamicLibrary? _library;
  _CloseDart? _close;
  _ResetDart? _reset;

  static String? _resolvedDllPath;

  static List<String> get dllCandidates {
    final env = Platform.environment['OBD_ATLAS_CONTROLCAN_DLL'];
    final executableDir = File(Platform.resolvedExecutable).parent.path;
    final currentDir = Directory.current.path;
    return <String>{
      if (env != null && env.trim().isNotEmpty) env.trim(),
      '$executableDir${Platform.pathSeparator}ControlCAN.dll',
      '$currentDir${Platform.pathSeparator}ControlCAN.dll',
    }.toList();
  }

  static String? locateDll() {
    if (!Platform.isWindows) return null;
    if (_resolvedDllPath != null && File(_resolvedDllPath!).existsSync()) return _resolvedDllPath;
    for (final path in dllCandidates) {
      if (File(path).existsSync()) {
        _resolvedDllPath = path;
        return path;
      }
    }
    return null;
  }

  static Future<bool> probe() async {
    if (!Platform.isWindows) return false;
    final path = locateDll();
    if (path == null) {
      throw StateError('ControlCAN.dll not found. Put the x64 DLL beside obd_atlas.exe or set OBD_ATLAS_CONTROLCAN_DLL.');
    }
    final library = DynamicLibrary.open(path);
    final open = library.lookupFunction<_OpenNative, _OpenDart>('VCI_OpenDevice');
    final close = library.lookupFunction<_CloseNative, _CloseDart>('VCI_CloseDevice');
    final result = open(_vciUsbCan2, 0, 0);
    if (result != _statusOk) return false;
    close(_vciUsbCan2, 0);
    return true;
  }

  @override
  String get id => 'lys-usbcan-$deviceIndex';

  @override
  String get displayName => 'LYS USBCAN-II • 0471:1200';

  @override
  String get transport => 'ControlCAN VCI';

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

  static int _rawTiming(int bitrate) {
    switch (bitrate) {
      case 1000000:
        return 0x1400;
      case 800000:
        return 0x1600;
      case 500000:
        return 0x1C00;
      case 250000:
        return 0x1C01;
      case 125000:
        return 0x1C03;
      case 100000:
        return 0x1C04;
      case 50000:
        return 0x1C09;
      case 20000:
        return 0x1C18;
      case 10000:
        return 0x1C31;
      default:
        throw ArgumentError.value(bitrate, 'bitrate', 'Unsupported ControlCAN bitrate');
    }
  }

  @override
  Future<void> connect() async {
    if (!Platform.isWindows) throw UnsupportedError('LYS USBCAN-II is currently supported on Windows only.');
    if (_state == AtlasAdapterState.connected) return;
    _setState(AtlasAdapterState.connecting);

    try {
      final path = locateDll();
      if (path == null) {
        throw StateError('ControlCAN.dll not found. Put the x64 DLL beside obd_atlas.exe or set OBD_ATLAS_CONTROLCAN_DLL.');
      }
      final library = DynamicLibrary.open(path);
      final open = library.lookupFunction<_OpenNative, _OpenDart>('VCI_OpenDevice');
      final close = library.lookupFunction<_CloseNative, _CloseDart>('VCI_CloseDevice');
      final init = library.lookupFunction<_InitNative, _InitDart>('VCI_InitCAN');
      final start = library.lookupFunction<_StartNative, _StartDart>('VCI_StartCAN');
      final receive = library.lookupFunction<_ReceiveNative, _ReceiveDart>('VCI_Receive');
      _ResetDart? reset;
      try {
        reset = library.lookupFunction<_ResetNative, _ResetDart>('VCI_ResetCAN');
      } catch (_) {
        reset = null;
      }

      if (open(_vciUsbCan2, deviceIndex, 0) != _statusOk) {
        throw StateError('VCI_OpenDevice failed for LYS USBCAN-II.');
      }

      final config = calloc<_VciInitConfig>();
      try {
        final raw = _rawTiming(bitrate);
        config.ref
          ..accCode = 0
          ..accMask = 0xFFFFFFFF
          ..reserved = 0
          ..filter = 1
          ..timing0 = raw & 0xFF
          ..timing1 = (raw >> 8) & 0xFF
          ..mode = 0;

        for (var channel = 0; channel < 2; channel++) {
          if (init(_vciUsbCan2, deviceIndex, channel, config) != _statusOk) {
            throw StateError('VCI_InitCAN failed for physical channel $channel.');
          }
          if (start(_vciUsbCan2, deviceIndex, channel) != _statusOk) {
            throw StateError('VCI_StartCAN failed for physical channel $channel.');
          }
        }
      } catch (_) {
        close(_vciUsbCan2, deviceIndex);
        rethrow;
      } finally {
        calloc.free(config);
      }

      _library = library;
      _close = close;
      _reset = reset;
      _running = true;
      _setState(AtlasAdapterState.connected);
      _pollTask = _poll(receive);
    } catch (_) {
      _setState(AtlasAdapterState.error);
      rethrow;
    }
  }

  Future<void> _poll(_ReceiveDart receive) async {
    const batchSize = 256;
    final buffer = calloc<_VciCanObj>(batchSize);
    try {
      while (_running) {
        var gotAny = false;
        for (var physical = 0; physical < 2 && _running; physical++) {
          final received = receive(_vciUsbCan2, deviceIndex, physical, buffer, batchSize, 0);
          if (received <= 0 || received > batchSize) continue;
          gotAny = true;
          for (var i = 0; i < received; i++) {
            final native = buffer.elementAt(i).ref;
            final dlc = native.dataLen.clamp(0, 8);
            final payload = <int>[for (var n = 0; n < dlc; n++) native.data[n]];
            _frames.add(CanFrame(
              timestamp: DateTime.now(),
              channel: baseChannel + physical,
              id: native.id,
              extended: native.externFlag != 0,
              remote: native.remoteFlag != 0,
              data: payload,
            ));
          }
        }
        if (!gotAny) await Future<void>.delayed(const Duration(milliseconds: 1));
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
    await _pollTask;
    _pollTask = null;
    final reset = _reset;
    if (reset != null) {
      for (var channel = 1; channel >= 0; channel--) {
        reset(_vciUsbCan2, deviceIndex, channel);
      }
    }
    _close?.call(_vciUsbCan2, deviceIndex);
    _close = null;
    _reset = null;
    _library = null;
    _setState(AtlasAdapterState.disconnected);
  }
}
