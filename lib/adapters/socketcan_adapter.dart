import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

/// Linux SocketCAN adapter for OBD Atlas.
///
/// The first implementation deliberately uses the standard can-utils
/// `candump -L` stream instead of binding OBD Atlas to a vendor USB API.
/// Any Linux CAN interface that is already exposed through SocketCAN can
/// therefore feed the same canonical Atlas frame stream.
class SocketCanAdapter implements AtlasAdapter {
  SocketCanAdapter(this.interfaceName, {this.channel = 1});

  final String interfaceName;
  final int channel;

  final StreamController<CanFrame> _frames = StreamController<CanFrame>.broadcast();
  final StreamController<AtlasAdapterState> _states = StreamController<AtlasAdapterState>.broadcast();

  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  Process? _candump;
  StreamSubscription<String>? _stdoutSubscription;
  StreamSubscription<String>? _stderrSubscription;
  bool _disconnecting = false;

  @override
  String get id => 'socketcan:$interfaceName';

  @override
  String get displayName => 'SocketCAN $interfaceName';

  @override
  String get transport => 'SocketCAN';

  @override
  AtlasAdapterState get state => _state;

  @override
  Stream<CanFrame> get frames => _frames.stream;

  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  static Future<List<String>> availableInterfaces() async {
    if (!Platform.isLinux) return const <String>[];

    final net = Directory('/sys/class/net');
    if (!await net.exists()) return const <String>[];

    final interfaces = <String>[];
    await for (final entry in net.list(followLinks: false)) {
      final name = entry.uri.pathSegments.where((part) => part.isNotEmpty).lastOrNull;
      if (name == null) continue;

      try {
        // ARPHRD_CAN = 280. This includes hardware CAN, vcan and slcan
        // once they are registered with the kernel CAN networking stack.
        final type = (await File('/sys/class/net/$name/type').readAsString()).trim();
        if (type == '280') interfaces.add(name);
      } catch (_) {
        // Ignore transient sysfs entries while adapters are being attached.
      }
    }

    interfaces.sort();
    return interfaces;
  }

  @override
  Future<void> connect() async {
    if (_state == AtlasAdapterState.connected || _state == AtlasAdapterState.connecting) return;
    if (!Platform.isLinux) {
      throw UnsupportedError('SocketCAN is available only on Linux.');
    }

    _setState(AtlasAdapterState.connecting);
    _disconnecting = false;

    final interfaces = await availableInterfaces();
    if (!interfaces.contains(interfaceName)) {
      _setState(AtlasAdapterState.error);
      throw StateError('SocketCAN interface $interfaceName is not available. Bring it up before connecting Atlas.');
    }

    try {
      _candump = await Process.start(
        'candump',
        <String>['-L', interfaceName],
        runInShell: false,
      );
    } on ProcessException catch (error) {
      _setState(AtlasAdapterState.error);
      throw StateError('Unable to start candump. Install can-utils first. ${error.message}');
    }

    _stdoutSubscription = _candump!.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(_handleCandumpLine, onError: _handleStreamError);

    _stderrSubscription = _candump!.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
          if (line.trim().isNotEmpty && !_disconnecting) {
            _frames.addError(StateError('candump: $line'));
          }
        });

    _candump!.exitCode.then((code) {
      if (_disconnecting) return;
      if (code != 0) {
        _setState(AtlasAdapterState.error);
        _frames.addError(StateError('candump exited with status $code on $interfaceName.'));
      } else {
        _setState(AtlasAdapterState.disconnected);
      }
    });

    _setState(AtlasAdapterState.connected);
  }

  void _handleCandumpLine(String line) {
    final match = RegExp(r'^\(([^)]+)\)\s+(\S+)\s+([0-9A-Fa-f]+)#(.*)$').firstMatch(line.trim());
    if (match == null) return;

    final timestampSeconds = double.tryParse(match.group(1)!);
    final bus = match.group(2)!;
    final idHex = match.group(3)!;
    var payload = match.group(4)!;

    final id = int.tryParse(idHex, radix: 16);
    if (timestampSeconds == null || id == null) return;

    var remote = false;
    if (payload.startsWith('R')) {
      remote = true;
      payload = '';
    } else if (payload.startsWith('#')) {
      // CAN FD candump notation is ID##<flags><data>. CanFrame does not yet
      // expose FD flags, so preserve the payload bytes and discard the flag
      // nibble for this first Linux foundation.
      payload = payload.length >= 2 ? payload.substring(2) : '';
    }

    if (payload.length.isOdd) return;
    final data = <int>[];
    for (var offset = 0; offset < payload.length; offset += 2) {
      final byte = int.tryParse(payload.substring(offset, offset + 2), radix: 16);
      if (byte == null) return;
      data.add(byte);
    }

    final micros = (timestampSeconds * Duration.microsecondsPerSecond).round();
    _frames.add(CanFrame(
      timestamp: DateTime.fromMicrosecondsSinceEpoch(micros),
      id: id,
      data: data,
      extended: idHex.length > 3,
      remote: remote,
      channel: channel,
      bus: bus,
    ));
  }

  void _handleStreamError(Object error, StackTrace stackTrace) {
    if (_disconnecting) return;
    _setState(AtlasAdapterState.error);
    _frames.addError(error, stackTrace);
  }

  void _setState(AtlasAdapterState value) {
    _state = value;
    if (!_states.isClosed) _states.add(value);
  }

  @override
  Future<void> disconnect() async {
    if (_state == AtlasAdapterState.disconnected && _candump == null) return;

    _disconnecting = true;
    await _stdoutSubscription?.cancel();
    await _stderrSubscription?.cancel();
    _stdoutSubscription = null;
    _stderrSubscription = null;

    final process = _candump;
    _candump = null;
    if (process != null) {
      process.kill(ProcessSignal.sigterm);
      try {
        await process.exitCode.timeout(const Duration(seconds: 2));
      } on TimeoutException {
        process.kill(ProcessSignal.sigkill);
      }
    }

    _setState(AtlasAdapterState.disconnected);
  }
}

extension _LastOrNull<T> on Iterable<T> {
  T? get lastOrNull => isEmpty ? null : last;
}
