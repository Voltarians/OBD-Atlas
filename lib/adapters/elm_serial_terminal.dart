import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:libserialport/libserialport.dart';

final class ElmTerminalReply {
  const ElmTerminalReply({
    required this.command,
    required this.startedAt,
    required this.elapsed,
    required this.rawResponse,
  });

  final String command;
  final DateTime startedAt;
  final Duration elapsed;
  final String rawResponse;

  bool get rejected => rawResponse.contains('?');

  Map<String, Object?> toJson() => <String, Object?>{
        'command': command,
        'startedAt': startedAt.toIso8601String(),
        'elapsedMs': elapsed.inMicroseconds / 1000.0,
        'rawResponse': rawResponse,
        'rejected': rejected,
      };
}

/// Direct serial ELM/STN adapter terminal for Atlas.
///
/// This surface intentionally permits only AT/ST adapter commands. It is meant
/// for adapter capability research, not raw ECU diagnostic/control traffic.
final class ElmSerialTerminal {
  ElmSerialTerminal({
    required this.portName,
    this.baudRate = 115200,
    this.timeout = const Duration(seconds: 4),
  });

  final String portName;
  final int baudRate;
  final Duration timeout;

  SerialPort? _port;
  SerialPortReader? _reader;
  StreamSubscription<Uint8List>? _subscription;
  Completer<String>? _pending;
  final StringBuffer _buffer = StringBuffer();

  bool get connected => _port?.isOpen == true;

  static List<String> availablePorts() => SerialPort.availablePorts;

  Future<void> connect() async {
    if (connected) return;
    final port = SerialPort(portName);
    if (!port.openReadWrite()) {
      throw StateError('Unable to open $portName: ${SerialPort.lastError}');
    }

    final config = SerialPortConfig()
      ..baudRate = baudRate
      ..bits = 8
      ..parity = SerialPortParity.none
      ..stopBits = 1
      ..setFlowControl(SerialPortFlowControl.none);
    port.config = config;
    config.dispose();

    _port = port;
    _reader = SerialPortReader(port);
    _subscription = _reader!.stream.listen(
      _onBytes,
      onError: (Object error, StackTrace stack) {
        final pending = _pending;
        if (pending != null && !pending.isCompleted) {
          pending.completeError(error, stack);
        }
      },
      cancelOnError: false,
    );
  }

  String validateCommand(String input) {
    final command =
        input.trim().replaceAll(RegExp(r'\s+'), ' ').toUpperCase();
    if (command.isEmpty) {
      throw const FormatException('Command is empty.');
    }
    if (!(command.startsWith('AT') || command.startsWith('ST'))) {
      throw const FormatException(
        'Atlas adapter terminal accepts only AT/ST adapter commands.',
      );
    }
    if (command.length > 128) {
      throw const FormatException('Command is too long.');
    }
    return command;
  }

  Future<ElmTerminalReply> send(String input) async {
    if (!connected) throw StateError('Serial terminal is not connected.');
    if (_pending != null) throw StateError('A terminal command is already pending.');

    final command = validateCommand(input);
    final startedAt = DateTime.now().toUtc();
    final watch = Stopwatch()..start();
    final response = Completer<String>();
    _pending = response;
    _buffer.clear();

    try {
      final bytes = Uint8List.fromList(ascii.encode('$command\r'));
      final written = _port!.write(bytes);
      if (written != bytes.length) {
        throw StateError('Short serial write for $command.');
      }
      final raw = await response.future.timeout(
        timeout,
        onTimeout: () => throw TimeoutException(
          'No ELM/STN prompt after $command.',
          timeout,
        ),
      );
      watch.stop();
      return ElmTerminalReply(
        command: command,
        startedAt: startedAt,
        elapsed: watch.elapsed,
        rawResponse: raw,
      );
    } finally {
      if (identical(_pending, response)) _pending = null;
    }
  }

  void _onBytes(Uint8List bytes) {
    for (final code in bytes) {
      final char = String.fromCharCode(code);
      if (char == '>') {
        final pending = _pending;
        if (pending != null && !pending.isCompleted) {
          pending.complete(_buffer.toString());
          _buffer.clear();
        }
      } else {
        _buffer.write(char);
      }
    }
  }

  Future<void> disconnect() async {
    final pending = _pending;
    if (pending != null && !pending.isCompleted) {
      pending.completeError(StateError('Terminal disconnected.'));
    }
    _pending = null;
    await _subscription?.cancel();
    _subscription = null;
    _reader = null;
    final port = _port;
    _port = null;
    if (port != null) {
      if (port.isOpen) port.close();
      port.dispose();
    }
    _buffer.clear();
  }
}
