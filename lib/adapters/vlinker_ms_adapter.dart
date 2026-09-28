import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:libserialport/libserialport.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

/// Receive-only vLinker MS transport for paired Bluetooth/serial COM ports.
///
/// The first implementation targets the 500 kbit/s HS-CAN path used by the
/// Volt test workflow. It uses the STN-style raw monitor command set already
/// validated by Atlas' OBDLink work and preserves raw CAN frames only.
class VlinkerMsAdapter implements AtlasAdapter {
  VlinkerMsAdapter(
    this.portName, {
    this.channel = 1,
    this.baudRate = 115200,
  }) : assert(channel >= 1 && channel <= 5);

  final String portName;
  final int channel;
  final int baudRate;

  final _frames = StreamController<CanFrame>.broadcast();
  final _states = StreamController<AtlasAdapterState>.broadcast();
  final _responses = StreamController<String>.broadcast();

  SerialPort? _port;
  SerialPortReader? _reader;
  StreamSubscription<Uint8List>? _subscription;
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  String _buffer = '';
  String _responseBuffer = '';
  bool _awaitingPrompt = false;
  bool _monitoring = false;
  Completer<void>? _firstFrame;

  @override
  String get id => 'vlinker-ms:ch$channel:$portName';

  @override
  String get displayName => 'CH$channel vLinker MS $portName';

  @override
  String get transport => 'vLinker MS serial';

  @override
  AtlasAdapterState get state => _state;

  @override
  Stream<CanFrame> get frames => _frames.stream;

  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  static List<String> availablePorts() => SerialPort.availablePorts;

  void _setState(AtlasAdapterState value) {
    _state = value;
    _states.add(value);
  }

  @override
  Future<void> connect() async {
    if (_state == AtlasAdapterState.connected) return;
    _setState(AtlasAdapterState.connecting);
    _firstFrame = Completer<void>();

    final port = SerialPort(portName);
    if (!port.openReadWrite()) {
      _setState(AtlasAdapterState.error);
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
        _setState(AtlasAdapterState.error);
        _frames.addError(error, stack);
      },
      cancelOnError: false,
    );

    try {
      await _command('ATZ', timeout: const Duration(seconds: 4));
      await _command('ATE0');
      await _command('ATL0');
      await _command('ATS0');
      await _command('ATH1');
      await _command('ATD0');
      await _command('ATAL');
      await _command('ATCFC0');

      // Raw 11-bit 500 kbit/s HS-CAN, matching the proven OBDLink path.
      await _command('STP 31');
      await _command('STCMM 0');
      await _command('STFAC');
      await _command('STFPA 000,000');

      _monitoring = true;
      _write('STM');

      await _firstFrame!.future.timeout(
        const Duration(seconds: 6),
        onTimeout: () => throw TimeoutException(
          'vLinker MS monitor started but no CAN frames were received. '
          'Confirm the adapter is paired, the correct COM port is selected, '
          'and the vehicle HS-CAN bus is active.',
        ),
      );
      _setState(AtlasAdapterState.connected);
    } catch (_) {
      await disconnect();
      rethrow;
    }
  }

  Future<String> _command(
    String command, {
    Duration timeout = const Duration(seconds: 2),
  }) async {
    _responseBuffer = '';
    _awaitingPrompt = true;
    final future = _responses.stream.first.timeout(
      timeout,
      onTimeout: () => throw TimeoutException('No prompt after $command', timeout),
    );
    try {
      _write(command);
      final response = await future;
      final upper = response.toUpperCase();
      if (upper.contains('?') ||
          upper.contains('ERROR') ||
          upper.contains('UNABLE TO CONNECT')) {
        throw StateError('vLinker MS rejected $command: ${response.trim()}');
      }
      return response;
    } finally {
      _awaitingPrompt = false;
    }
  }

  void _write(String command) {
    final port = _port;
    if (port == null || !port.isOpen) {
      throw StateError('vLinker MS serial port is not open');
    }
    final bytes = Uint8List.fromList(ascii.encode('$command\r'));
    final written = port.write(bytes);
    if (written != bytes.length) {
      throw StateError('Short serial write for vLinker MS command $command');
    }
  }

  void _onBytes(Uint8List bytes) {
    final text = ascii.decode(bytes, allowInvalid: true);
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
      if (terminalError != null) {
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
    if (cleaned == '?') return 'vLinker MS rejected the raw monitor command.';
    if (cleaned.contains('BUFFER FULL')) {
      return 'vLinker MS buffer full: CAN traffic exceeded serial/Bluetooth throughput.';
    }
    if (cleaned.contains('UART RX OVERFLOW')) {
      return 'vLinker MS UART receive overflow.';
    }
    if (cleaned.contains('STOPPED')) return 'vLinker MS monitoring stopped.';
    if (cleaned.contains('NO DATA')) return 'vLinker MS monitoring ended with no data.';
    return null;
  }

  static CanFrame? parseMonitorLine(String line, {int channel = 1}) {
    if (channel < 1 || channel > 5) return null;
    final cleaned = line.trim().toUpperCase();
    if (cleaned.isEmpty ||
        cleaned == 'OK' ||
        cleaned.startsWith('AT') ||
        cleaned.startsWith('ST') ||
        cleaned.contains('SEARCHING') ||
        cleaned.contains('STOPPED') ||
        cleaned.contains('BUFFER FULL') ||
        cleaned.contains('NO DATA')) {
      return null;
    }

    // ATS0 + ATD0 compact STM format: 3 hex ID chars followed by 0..8 bytes.
    if (RegExp(r'^[0-9A-F]+$').hasMatch(cleaned)) {
      final idLength = cleaned.length.isOdd ? 3 : 8;
      if (cleaned.length < idLength ||
          (cleaned.length - idLength).isOdd ||
          cleaned.length - idLength > 16) {
        return null;
      }
      final id = int.tryParse(cleaned.substring(0, idLength), radix: 16);
      if (id == null || id > 0x1FFFFFFF) return null;
      final data = <int>[];
      for (var cursor = idLength; cursor < cleaned.length; cursor += 2) {
        final byte = int.tryParse(cleaned.substring(cursor, cursor + 2), radix: 16);
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

    // Tolerate spaced monitor output with displayed DLC.
    final tokens = cleaned.split(RegExp(r'\s+'));
    if (tokens.isEmpty) return null;
    final idText = tokens.first;
    if (!(idText.length == 3 || idText.length == 8)) return null;
    final id = int.tryParse(idText, radix: 16);
    if (id == null || id > 0x1FFFFFFF || tokens.length < 2) return null;
    final dlc = int.tryParse(tokens[1], radix: 16);
    if (dlc == null || dlc < 0 || dlc > 8 || tokens.length < 2 + dlc) {
      return null;
    }
    final data = <int>[];
    for (var index = 0; index < dlc; index++) {
      final token = tokens[2 + index];
      if (token.length != 2) return null;
      final byte = int.tryParse(token, radix: 16);
      if (byte == null) return null;
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
    final port = _port;
    if (port != null && port.isOpen && _monitoring) {
      try {
        port.write(Uint8List.fromList(const <int>[13]));
        await Future<void>.delayed(const Duration(milliseconds: 100));
      } catch (_) {}
    }
    await _subscription?.cancel();
    _subscription = null;
    _reader?.close();
    _reader = null;
    if (port != null && port.isOpen) port.close();
    port?.dispose();
    _port = null;
    _monitoring = false;
    _buffer = '';
    _responseBuffer = '';
    _awaitingPrompt = false;
    _firstFrame = null;
    _setState(AtlasAdapterState.disconnected);
  }
}
