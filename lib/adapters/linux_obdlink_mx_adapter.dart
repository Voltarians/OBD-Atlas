import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

/// Receive-only OBDLink transport for Linux Bluetooth RFCOMM ports.
///
/// A Python standard-library helper owns the RFCOMM file so an ARM64
/// libserialport failure cannot crash the Flutter process.
class LinuxObdlinkMxAdapter implements AtlasAdapter {
  LinuxObdlinkMxAdapter(
    this.portName, {
    this.channel = 1,
    this.baudRate = 115200,
    this.protocol = 6,
  }) : assert(channel >= 1 && channel <= 5);

  final String portName;
  final int channel;
  final int baudRate;
  final int protocol;

  final _frames = StreamController<CanFrame>.broadcast();
  final _states = StreamController<AtlasAdapterState>.broadcast();
  final _responses = StreamController<String>.broadcast();
  Process? _process;
  StreamSubscription<String>? _stdoutSubscription;
  StreamSubscription<String>? _stderrSubscription;
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  String _buffer = '';
  String _responseBuffer = '';
  bool _awaitingPrompt = false;
  bool _monitoring = false;
  bool _disconnecting = false;

  @override
  String get id => 'obdlink-mx:ch$channel:$portName';
  @override
  String get displayName => 'CH$channel OBDLink MX+ $portName';
  @override
  String get transport => 'OBDLink MX+ RFCOMM';
  @override
  AtlasAdapterState get state => _state;
  @override
  Stream<CanFrame> get frames => _frames.stream;
  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  static List<String> availablePorts() {
    try {
      final ports = Directory('/dev')
          .listSync()
          .map((entry) => entry.path)
          .where((path) => RegExp(r'/rfcomm\d+$').hasMatch(path))
          .toList()
        ..sort();
      return ports;
    } on FileSystemException {
      return const <String>[];
    }
  }

  void _setState(AtlasAdapterState value) {
    _state = value;
    _states.add(value);
  }

  @override
  Future<void> connect() async {
    if (_state == AtlasAdapterState.connected) return;
    _setState(AtlasAdapterState.connecting);
    _disconnecting = false;
    final ready = Completer<void>();
    final process = await Process.start(
      'python3',
      <String>['-u', '-c', _rfcommHelper, portName, '$baudRate'],
    );
    _process = process;
    _stdoutSubscription = process.stdout
        .transform(const AsciiDecoder(allowInvalid: true))
        .listen(_onText, onError: _onTransportError);
    _stderrSubscription = process.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
      if (line == 'READY' && !ready.isCompleted) {
        ready.complete();
      } else if (line.isNotEmpty && !ready.isCompleted) {
        ready.completeError(StateError('RFCOMM helper: $line'));
      }
    });
    unawaited(process.exitCode.then((code) {
      if (!_disconnecting && _state != AtlasAdapterState.disconnected) {
        final error = StateError('RFCOMM helper exited with code $code');
        _setState(AtlasAdapterState.error);
        _frames.addError(error);
      }
    }));

    try {
      await ready.future.timeout(
        const Duration(seconds: 10),
        onTimeout: () => throw TimeoutException(
          'Timed out opening $portName. Confirm the MX+ is powered and paired.',
        ),
      );
      await _command('ATZ', timeout: const Duration(seconds: 4));
      await _command('ATE0');
      await _command('ATL0');
      await _command('ATS1');
      await _command('ATH1');
      await _command('ATD1');
      await _command('ATAL');
      await _command('ATCFC0');
      await _command('ATSP$protocol');
      _monitoring = true;
      _write('ATMA');
      _setState(AtlasAdapterState.connected);
    } catch (_) {
      await disconnect();
      rethrow;
    }
  }

  void _onTransportError(Object error, StackTrace stack) {
    _setState(AtlasAdapterState.error);
    _frames.addError(error, stack);
  }

  Future<String> _command(
    String command, {
    Duration timeout = const Duration(seconds: 2),
  }) async {
    _responseBuffer = '';
    _awaitingPrompt = true;
    final responseFuture = _responses.stream.first.timeout(
      timeout,
      onTimeout: () => throw TimeoutException('No prompt after $command', timeout),
    );
    late final String response;
    try {
      _write(command);
      response = await responseFuture;
    } finally {
      _awaitingPrompt = false;
    }
    final upper = response.toUpperCase();
    if (upper.contains('?') ||
        upper.contains('ERROR') ||
        upper.contains('UNABLE TO CONNECT')) {
      throw StateError('OBDLink rejected $command: ${response.trim()}');
    }
    return response;
  }

  void _write(String command) {
    final process = _process;
    if (process == null) throw StateError('RFCOMM helper is not running');
    process.stdin.add(ascii.encode('$command\r'));
  }

  void _onText(String text) {
    if (_awaitingPrompt) {
      _responseBuffer += text;
      if (_responseBuffer.contains('>')) {
        final completed = _responseBuffer;
        _responseBuffer = '';
        _responses.add(completed);
      }
    }
    _buffer += text.replaceAll('>', '\r');
    while (true) {
      final match = RegExp(r'[\r\n]').firstMatch(_buffer);
      if (match == null) break;
      final line = _buffer.substring(0, match.start).trim();
      _buffer = _buffer.substring(match.end);
      if (!_monitoring || line.isEmpty) continue;
      final frame = parseMonitorLine(line, channel: channel);
      if (frame != null) _frames.add(frame);
    }
  }

  static CanFrame? parseMonitorLine(String line, {int channel = 1}) {
    if (channel < 1 || channel > 5) return null;
    final cleaned = line.trim().toUpperCase();
    if (cleaned.isEmpty ||
        cleaned == 'OK' ||
        cleaned.startsWith('AT') ||
        cleaned.contains('SEARCHING') ||
        cleaned.contains('STOPPED') ||
        cleaned.contains('BUFFER FULL') ||
        cleaned.contains('NO DATA')) {
      return null;
    }
    final tokens = cleaned.split(RegExp(r'\s+'));
    if (tokens.isEmpty) return null;
    String idText;
    int cursor;
    if (tokens[0].length == 3 || tokens[0].length == 8) {
      idText = tokens[0];
      cursor = 1;
    } else if (tokens.length >= 4 &&
        tokens.take(4).every((part) => part.length == 2)) {
      idText = tokens.take(4).join();
      cursor = 4;
    } else {
      return null;
    }
    final id = int.tryParse(idText, radix: 16);
    if (id == null || id > 0x1FFFFFFF || cursor >= tokens.length) return null;
    final dlc = int.tryParse(tokens[cursor], radix: 16);
    if (dlc == null || dlc < 0 || dlc > 8) return null;
    cursor++;
    if (tokens.length - cursor < dlc) return null;
    final data = <int>[];
    for (var index = 0; index < dlc; index++) {
      final token = tokens[cursor + index];
      if (token.length != 2) return null;
      final byte = int.tryParse(token, radix: 16);
      if (byte == null || byte > 0xFF) return null;
      data.add(byte);
    }
    return CanFrame(
      timestamp: DateTime.now(),
      id: id,
      data: data,
      extended: idText.length == 8,
      channel: channel,
    );
  }

  @override
  Future<void> disconnect() async {
    _disconnecting = true;
    final process = _process;
    if (process != null) {
      if (_monitoring) {
        try {
          process.stdin.add(const <int>[13]);
          await process.stdin.flush();
          await Future<void>.delayed(const Duration(milliseconds: 100));
        } catch (_) {}
      }
      try {
        await process.stdin.close();
      } catch (_) {}
      process.kill(ProcessSignal.sigterm);
      try {
        await process.exitCode.timeout(const Duration(seconds: 2));
      } on TimeoutException {
        process.kill(ProcessSignal.sigkill);
      }
    }
    await _stdoutSubscription?.cancel();
    await _stderrSubscription?.cancel();
    _stdoutSubscription = null;
    _stderrSubscription = null;
    _process = null;
    _monitoring = false;
    _buffer = '';
    _responseBuffer = '';
    _awaitingPrompt = false;
    _setState(AtlasAdapterState.disconnected);
  }

  static const _rfcommHelper = r'''
import os
import select
import signal
import sys
import termios

path = sys.argv[1]
baud = int(sys.argv[2])
speeds = {
    9600: termios.B9600,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}
if baud not in speeds:
    raise ValueError("unsupported baud rate")

fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
attrs = termios.tcgetattr(fd)
attrs[0] = 0
attrs[1] = 0
attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
attrs[3] = 0
attrs[4] = speeds[baud]
attrs[5] = speeds[baud]
attrs[6][termios.VMIN] = 0
attrs[6][termios.VTIME] = 1
termios.tcsetattr(fd, termios.TCSANOW, attrs)

def stop(_signum, _frame):
    raise KeyboardInterrupt

signal.signal(signal.SIGTERM, stop)
print("READY", file=sys.stderr, flush=True)
try:
    while True:
        readable, _, _ = select.select([fd, sys.stdin.buffer], [], [], 0.25)
        if fd in readable:
            data = os.read(fd, 4096)
            if data:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
        if sys.stdin.buffer in readable:
            data = os.read(sys.stdin.fileno(), 4096)
            if not data:
                break
            os.write(fd, data)
except KeyboardInterrupt:
    pass
finally:
    os.close(fd)
''';
}
