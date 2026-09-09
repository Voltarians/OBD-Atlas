import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:libserialport/libserialport.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

/// Receive-only ELM327/OBDLink transport for Linux Bluetooth RFCOMM ports.
///
/// Atlas only sends adapter configuration commands followed by ATMA. It does
/// not issue OBD requests or transmit CAN frames to the vehicle.
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

  SerialPort? _port;
  SerialPortReader? _reader;
  StreamSubscription<Uint8List>? _subscription;
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  String _buffer = '';
  String _responseBuffer = '';
  bool _awaitingPrompt = false;
  bool _monitoring = false;

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
    final ports = SerialPort.availablePorts.toList()..sort();
    return ports;
  }

  void _setState(AtlasAdapterState value) {
    _state = value;
    _states.add(value);
  }

  @override
  Future<void> connect() async {
    if (_state == AtlasAdapterState.connected) return;
    _setState(AtlasAdapterState.connecting);

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
    if (upper.contains('?') || upper.contains('ERROR') || upper.contains('UNABLE TO CONNECT')) {
      throw StateError('OBDLink rejected $command: ${response.trim()}');
    }
    return response;
  }

  void _write(String command) {
    final port = _port;
    if (port == null || !port.isOpen) throw StateError('Serial port is not open');
    final bytes = Uint8List.fromList(ascii.encode('$command\r'));
    final written = port.write(bytes);
    if (written != bytes.length) {
      throw StateError('Short serial write for OBDLink command $command');
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
    } else if (tokens.length >= 4 && tokens.take(4).every((part) => part.length == 2)) {
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
    final port = _port;
    if (port != null && port.isOpen && _monitoring) {
      try {
        // A bare carriage return stops ATMA without transmitting a CAN frame.
        final stop = Uint8List.fromList(const <int>[13]);
        port.write(stop);
        await Future<void>.delayed(const Duration(milliseconds: 100));
      } catch (_) {}
    }
    _monitoring = false;
    await _subscription?.cancel();
    _subscription = null;
    _reader?.close();
    _reader = null;
    if (port != null && port.isOpen) port.close();
    port?.dispose();
    _port = null;
    _buffer = '';
    _responseBuffer = '';
    _awaitingPrompt = false;
    _setState(AtlasAdapterState.disconnected);
  }
}
