import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:libserialport/libserialport.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

class SlcanAdapter implements AtlasAdapter {
  SlcanAdapter(
    this.portName, {
    this.bitrate = 500000,
    this.baudRate = 115200,
    this.channel = 1,
  }) : assert(channel >= 1 && channel <= 5);

  final String portName;
  final int bitrate;
  final int baudRate;
  final int channel;

  final _frames = StreamController<CanFrame>.broadcast();
  final _states = StreamController<AtlasAdapterState>.broadcast();

  SerialPort? _port;
  SerialPortReader? _reader;
  StreamSubscription<Uint8List>? _subscription;
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  String _buffer = '';

  @override
  String get id => 'slcan:ch$channel:$portName';

  @override
  String get displayName => 'CH$channel SLCAN $portName';

  @override
  String get transport => 'SLCAN serial';

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
      },
      cancelOnError: false,
    );

    try {
      await _command('C');
      await _command(_bitrateCommand(bitrate));
      await _command('O');
      _setState(AtlasAdapterState.connected);
    } catch (_) {
      await disconnect();
      rethrow;
    }
  }

  Future<void> _command(String command) async {
    final port = _port;
    if (port == null || !port.isOpen) throw StateError('Serial port is not open');
    final bytes = Uint8List.fromList(ascii.encode('$command\r'));
    final written = port.write(bytes);
    if (written != bytes.length) throw StateError('Short serial write for SLCAN command $command');
    await Future<void>.delayed(const Duration(milliseconds: 60));
  }

  String _bitrateCommand(int rate) {
    const commands = <int, String>{
      10000: 'S0',
      20000: 'S1',
      50000: 'S2',
      100000: 'S3',
      125000: 'S4',
      250000: 'S5',
      500000: 'S6',
      800000: 'S7',
      1000000: 'S8',
    };
    final command = commands[rate];
    if (command == null) throw ArgumentError.value(rate, 'bitrate', 'Unsupported standard SLCAN bitrate');
    return command;
  }

  void _onBytes(Uint8List bytes) {
    _buffer += ascii.decode(bytes, allowInvalid: true);
    while (true) {
      final end = _buffer.indexOf('\r');
      if (end < 0) break;
      final line = _buffer.substring(0, end).trim();
      _buffer = _buffer.substring(end + 1);
      final frame = parseLine(line, channel: channel);
      if (frame != null) _frames.add(frame);
    }
  }

  static CanFrame? parseLine(String line, {int channel = 1}) {
    if (line.length < 5 || channel < 1 || channel > 5) return null;
    final kind = line[0];
    final extended = kind == 'T' || kind == 'R';
    final remote = kind == 'r' || kind == 'R';
    if (!(kind == 't' || kind == 'T' || kind == 'r' || kind == 'R')) return null;

    final idChars = extended ? 8 : 3;
    final dlcIndex = 1 + idChars;
    if (line.length <= dlcIndex) return null;

    final id = int.tryParse(line.substring(1, dlcIndex), radix: 16);
    final dlc = int.tryParse(line.substring(dlcIndex, dlcIndex + 1), radix: 16);
    if (id == null || dlc == null || dlc > 8) return null;

    final data = <int>[];
    if (!remote) {
      final payloadStart = dlcIndex + 1;
      final payloadEnd = payloadStart + dlc * 2;
      if (line.length < payloadEnd) return null;
      for (var i = payloadStart; i < payloadEnd; i += 2) {
        final byte = int.tryParse(line.substring(i, i + 2), radix: 16);
        if (byte == null) return null;
        data.add(byte);
      }
    }

    return CanFrame(
      timestamp: DateTime.now(),
      id: id,
      data: data,
      extended: extended,
      remote: remote,
      channel: channel,
    );
  }

  @override
  Future<void> disconnect() async {
    final port = _port;
    if (port != null && port.isOpen) {
      try {
        await _command('C');
      } catch (_) {}
    }
    await _subscription?.cancel();
    _subscription = null;
    _reader?.close();
    _reader = null;
    if (port != null && port.isOpen) port.close();
    port?.dispose();
    _port = null;
    _buffer = '';
    _setState(AtlasAdapterState.disconnected);
  }
}
