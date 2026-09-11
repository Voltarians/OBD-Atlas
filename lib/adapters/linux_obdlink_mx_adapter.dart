import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

enum ObdlinkMxCanBus {
  highSpeedCan(
    protocolNumber: 31,
    displayName: 'HS-CAN • pins 6/14 • 500 kbit/s',
    shortName: 'HS-CAN',
  ),
  singleWireCan(
    protocolNumber: 61,
    displayName: 'SWCAN • pin 1 • 33.3 kbit/s',
    shortName: 'SWCAN',
  );

  const ObdlinkMxCanBus({
    required this.protocolNumber,
    required this.displayName,
    required this.shortName,
  });

  final int protocolNumber;
  final String displayName;
  final String shortName;
}

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
    this.fastMonitor = true,
    this.canBus = ObdlinkMxCanBus.highSpeedCan,
  }) : assert(channel >= 1 && channel <= 5);

  final String portName;
  final int channel;
  final int baudRate;
  final int protocol;
  final bool fastMonitor;
  final ObdlinkMxCanBus canBus;

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
  Completer<void>? _firstFrame;

  @override
  String get id => 'obdlink-mx:ch$channel:$portName';
  @override
  String get displayName =>
      'CH$channel OBDLink MX+ ${canBus.shortName} $portName';
  @override
  String get transport => 'OBDLink MX+ RFCOMM';
  @override
  AtlasAdapterState get state => _state;
  @override
  Stream<CanFrame> get frames => _frames.stream;
  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  static Future<List<String>> availablePorts() async {
    final targets = <String>[];
    try {
      final ports = Directory('/dev')
          .listSync()
          .map((entry) => entry.path)
          .where((path) => RegExp(r'/rfcomm\d+$').hasMatch(path))
          .toList()
        ..sort();
      targets.addAll(ports);
    } on FileSystemException {
      // Direct paired-device discovery below can still provide a target.
    }

    // Direct RFCOMM sockets avoid root-owned /dev/rfcomm devices. Pairing is
    // still a one-time BlueZ operation because passkey confirmation is manual.
    try {
      final result = await Process.run(
        'bluetoothctl',
        const <String>['devices', 'Paired'],
      ).timeout(const Duration(seconds: 4));
      if (result.exitCode == 0) {
        targets.addAll(parsePairedDeviceLines('${result.stdout}'));
      }
    } on Object {
      // BlueZ may be absent; manually bound /dev/rfcomm ports remain usable.
    }
    return targets.toSet().toList()..sort();
  }

  static List<String> parsePairedDeviceLines(String output) {
    final targets = <String>[];
    for (final line in const LineSplitter().convert(output)) {
      final match = RegExp(
        r'^Device\s+([0-9A-Fa-f:]{17})\s+(.+)$',
      ).firstMatch(line.trim());
      if (match == null) continue;
      final name = match.group(2)!.toUpperCase();
      if (!name.contains('OBDLINK') && !name.contains('MX+')) continue;
      targets.add('rfcomm://${match.group(1)!.toUpperCase()}:1');
    }
    return targets;
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
    _firstFrame = Completer<void>();
    _log('CONNECT target=$portName bus=${canBus.shortName}');
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
        _log('ERROR $error');
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
      await _command(fastMonitor ? 'ATS0' : 'ATS1');
      await _command('ATH1');
      await _command(fastMonitor ? 'ATD0' : 'ATD1');
      await _command('ATAL');
      await _command('ATCFC0');
      if (fastMonitor) {
        for (final command in monitorSetupCommands(canBus)) {
          await _command(command);
        }
      } else {
        await _command('ATSP$protocol');
      }
      _monitoring = true;
      _write(fastMonitor ? 'STM' : 'ATMA');
      _log('TX ${fastMonitor ? 'STM' : 'ATMA'}');
      await _firstFrame!.future.timeout(
        const Duration(seconds: 6),
        onTimeout: () => throw TimeoutException(
          'MX+ ${canBus.shortName} monitor started but received no CAN frames. '
          'The adapter configuration or selected vehicle bus is not active.',
        ),
      );
      _setState(AtlasAdapterState.connected);
      _log('CONNECTED first-frame-received');
    } catch (error) {
      _log('CONNECT FAILED $error');
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
      _log('TX $command');
      _write(command);
      response = await responseFuture;
    } finally {
      _awaitingPrompt = false;
    }
    final upper = response.toUpperCase();
    _log('RX $command ${response.replaceAll(RegExp(r'[\r\n]+'), ' ').trim()}');
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
      final terminalError = monitorTerminalError(line);
      if (terminalError != null && !_disconnecting) {
        _monitoring = false;
        _setState(AtlasAdapterState.error);
        _frames.addError(StateError(terminalError));
        continue;
      }
      final frame = parseMonitorLine(line, channel: channel);
      if (frame != null) {
        if (_firstFrame?.isCompleted == false) _firstFrame!.complete();
        _frames.add(frame);
      }
    }
  }

  static String? monitorTerminalError(String line) {
    final cleaned = line.trim().toUpperCase();
    if (cleaned.contains('BUFFER FULL')) {
      return 'OBDLink buffer full: raw CAN traffic exceeded the RFCOMM '
          'text-stream throughput.';
    }
    if (cleaned.contains('UART RX OVERFLOW')) {
      return 'OBDLink UART receive overflow.';
    }
    if (cleaned.contains('STOPPED')) {
      return 'OBDLink monitoring stopped.';
    }
    if (cleaned.contains('NO DATA')) {
      return 'OBDLink monitoring ended with no data.';
    }
    return null;
  }

  static List<String> monitorSetupCommands(ObdlinkMxCanBus bus) {
    // OBDLink FRPM: protocol 31 is raw 11-bit HS-CAN at 500 kbit/s;
    // protocol 61 is raw 11-bit GM SWCAN at 33.3 kbit/s. STM preserves
    // raw CAN frames; STMA would treat them as ISO 15765 messages.
    return <String>[
      'STP ${bus.protocolNumber}',
      if (bus == ObdlinkMxCanBus.singleWireCan) 'STCSWM 3',
      'STCMM 0',
      'STFAC',
      'STFPA 000,000',
    ];
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
    // Compact STM mode uses ATS0/ATD0 to remove spaces and displayed DLC.
    // 11-bit output has an odd hex length (3 + 2*n); 29-bit output is even.
    if (RegExp(r'^[0-9A-F]+$').hasMatch(cleaned)) {
      final idLength = cleaned.length.isOdd ? 3 : 8;
      if (cleaned.length < idLength ||
          (cleaned.length - idLength).isOdd ||
          cleaned.length - idLength > 16) {
        return null;
      }
      final idText = cleaned.substring(0, idLength);
      final id = int.tryParse(idText, radix: 16);
      if (id == null || id > 0x1FFFFFFF) return null;
      final data = <int>[];
      for (var cursor = idLength; cursor < cleaned.length; cursor += 2) {
        final byte = int.tryParse(
          cleaned.substring(cursor, cursor + 2),
          radix: 16,
        );
        if (byte == null) return null;
        data.add(byte);
      }
      return CanFrame(
        timestamp: DateTime.now(),
        id: id,
        data: data,
        extended: idLength == 8,
        channel: channel,
      );
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
    _firstFrame = null;
    _setState(AtlasAdapterState.disconnected);
  }

  static void _log(String message) {
    try {
      final home = Platform.environment['HOME'];
      if (home == null || home.isEmpty) return;
      final directory = Directory('$home/Documents/OBD Atlas/logs')
        ..createSync(recursive: true);
      File('${directory.path}/obdlink-mx.log').writeAsStringSync(
        '${DateTime.now().toUtc().toIso8601String()} $message\n',
        mode: FileMode.append,
        flush: true,
      );
    } on Object {
      // Logging must never interrupt or terminate a vehicle-bus connection.
    }
  }

  static const _rfcommHelper = r'''
import os
import select
import signal
import socket
import sys
import termios

target = sys.argv[1]
baud = int(sys.argv[2])
speeds = {
    9600: termios.B9600,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}
if baud not in speeds:
    raise ValueError("unsupported baud rate")

transport = None
if target.startswith("rfcomm://"):
    endpoint = target[len("rfcomm://"):]
    address, channel_text = endpoint.rsplit(":", 1)
    transport = socket.socket(
        socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    transport.settimeout(10)
    transport.connect((address, int(channel_text)))
    transport.setblocking(False)
    fd = transport.fileno()
else:
    fd = os.open(target, os.O_RDWR | os.O_NOCTTY)
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
    if transport is not None:
        transport.close()
    else:
        os.close(fd)
''';
}
