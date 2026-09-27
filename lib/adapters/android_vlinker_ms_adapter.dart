import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_classic_bluetooth/flutter_classic_bluetooth.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

class AndroidBluetoothDevice {
  const AndroidBluetoothDevice({
    required this.name,
    required this.address,
  });

  final String name;
  final String address;

  String get label => name.trim().isEmpty ? address : '$name • $address';
}

class AndroidVlinkerMsAdapter implements AtlasAdapter {
  AndroidVlinkerMsAdapter({
    required this.address,
    this.deviceName = 'vLinker MS',
    this.channel = 1,
  });

  final String address;
  final String deviceName;
  final int channel;

  final FlutterClassicBluetooth _bluetooth = FlutterClassicBluetooth();
  final StreamController<CanFrame> _frames =
      StreamController<CanFrame>.broadcast();
  final StreamController<AtlasAdapterState> _states =
      StreamController<AtlasAdapterState>.broadcast();

  dynamic _connection;
  StreamSubscription<dynamic>? _inputSubscription;
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  String _rxBuffer = '';

  static const MethodChannel _permissionChannel =
      MethodChannel('obd_atlas/bluetooth_permissions');

  static Future<void> _ensureBluetoothPermissions() async {
    if (!Platform.isAndroid) return;
    final granted = await _permissionChannel.invokeMethod<bool>(
          'ensureBluetoothPermissions',
        ) ??
        false;
    if (!granted) {
      throw StateError(
        'Nearby devices permission is required for Bluetooth OBD adapters.',
      );
    }
  }

  static Future<List<AndroidBluetoothDevice>> pairedDevices() async {
    if (!Platform.isAndroid) return const <AndroidBluetoothDevice>[];
    await _ensureBluetoothPermissions();
    final bluetooth = FlutterClassicBluetooth();
    final devices = await bluetooth.getPairedDevices();
    return devices
        .map(
          (device) => AndroidBluetoothDevice(
            name: device.displayName,
            address: device.address,
          ),
        )
        .toList(growable: false);
  }

  @override
  String get id => 'android-vlinker-ms:$address';

  @override
  String get displayName => deviceName;

  @override
  String get transport => 'Android Bluetooth Classic RFCOMM';

  @override
  AtlasAdapterState get state => _state;

  @override
  Stream<CanFrame> get frames => _frames.stream;

  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  void _setState(AtlasAdapterState value) {
    _state = value;
    if (!_states.isClosed) _states.add(value);
  }

  @override
  Future<void> connect() async {
    if (!Platform.isAndroid) {
      throw UnsupportedError(
        'Android vLinker MS Bluetooth transport is available only on Android.',
      );
    }
    await _ensureBluetoothPermissions();

    if (_state == AtlasAdapterState.connected ||
        _state == AtlasAdapterState.connecting) {
      return;
    }

    _setState(AtlasAdapterState.connecting);
    debugPrint('Atlas vLinker MS: opening RFCOMM $address');
    try {
      final connection = await _bluetooth.connect(
        address: address,
        timeout: const Duration(seconds: 10),
      );
      _connection = connection;
      debugPrint('Atlas vLinker MS: RFCOMM connected');

      await _initializeElmStn(connection);

      _inputSubscription = connection.input.listen(
        _onBytes,
        onError: (Object error, StackTrace stack) {
          debugPrint('Atlas vLinker MS: input error: $error');
          if (!_frames.isClosed) _frames.addError(error, stack);
          _setState(AtlasAdapterState.error);
        },
        onDone: () {
          debugPrint('Atlas vLinker MS: RFCOMM input closed');
          if (_state != AtlasAdapterState.disconnected) {
            _setState(AtlasAdapterState.disconnected);
          }
        },
        cancelOnError: false,
      );

      debugPrint('Atlas vLinker MS: starting passive ATMA monitor');
      await connection.output.writeString('ATMA\r');
      await connection.output.allSent.timeout(const Duration(seconds: 2));
      _setState(AtlasAdapterState.connected);
      debugPrint('Atlas vLinker MS: passive monitor active');
    } catch (error) {
      debugPrint('Atlas vLinker MS: connect/init failed: $error');
      _setState(AtlasAdapterState.error);
      rethrow;
    }
  }

  Future<void> _initializeElmStn(dynamic connection) async {
    debugPrint('Atlas vLinker MS: ATZ');
    final reset = await connection.sendAndReceive(
      'ATZ',
      where: (String line) {
        final value = line.trim().toUpperCase();
        return value.isNotEmpty && value != 'ATZ';
      },
      timeout: const Duration(seconds: 3),
    );
    debugPrint('Atlas vLinker MS: ATZ -> $reset');

    for (final command in const <String>[
      'ATE0',
      'ATL0',
      'ATS1',
      'ATH1',
      'ATSP6',
    ]) {
      debugPrint('Atlas vLinker MS: $command');
      final response = await connection.sendAndReceive(
        command,
        where: (String line) => line.trim().toUpperCase() == 'OK',
        timeout: const Duration(seconds: 2),
      );
      debugPrint('Atlas vLinker MS: $command -> $response');
    }

    debugPrint('Atlas vLinker MS: ATDP');
    final protocol = await connection.sendAndReceive(
      'ATDP',
      where: (String line) {
        final value = line.trim().toUpperCase();
        return value.isNotEmpty && value != 'ATDP' && value != 'OK';
      },
      timeout: const Duration(seconds: 2),
    );
    debugPrint('Atlas vLinker MS: protocol -> $protocol');
  }

  void _onBytes(dynamic chunk) {
    final bytes = chunk is List<int> ? chunk : List<int>.from(chunk as Iterable);
    _rxBuffer += latin1.decode(bytes, allowInvalid: true);

    final normalized = _rxBuffer.replaceAll('>', '\n');
    final parts = normalized.split(RegExp(r'[\r\n]+'));
    _rxBuffer = parts.removeLast();

    for (final raw in parts) {
      _parseLine(raw);
    }
  }

  void _parseLine(String raw) {
    var line = raw.trim().toUpperCase();
    if (line.isEmpty) return;

    if (line.startsWith('AT') ||
        line == 'OK' ||
        line == '?' ||
        line.contains('SEARCHING') ||
        line.contains('NO DATA') ||
        line.contains('STOPPED') ||
        line.contains('ELM327') ||
        line.contains('STN') ||
        line.contains('VLINKER') ||
        line.contains('ISO 15765')) {
      return;
    }

    line = line.replaceAll(RegExp(r'\s+'), ' ');
    final tokens = line.split(' ');
    if (tokens.length < 2) return;

    final idText = tokens.first;
    if (!RegExp(r'^[0-9A-F]{3}$|^[0-9A-F]{8}$').hasMatch(idText)) return;

    final id = int.tryParse(idText, radix: 16);
    if (id == null) return;

    final data = <int>[];
    for (final token in tokens.skip(1)) {
      if (!RegExp(r'^[0-9A-F]{2}$').hasMatch(token)) return;
      final value = int.tryParse(token, radix: 16);
      if (value == null) return;
      data.add(value);
    }

    if (data.isEmpty || data.length > 8) return;

    _frames.add(
      CanFrame(
        timestamp: DateTime.now().toUtc(),
        id: id,
        data: data,
        extended: idText.length == 8,
        channel: channel,
      ),
    );
  }

  @override
  Future<void> disconnect() async {
    final connection = _connection;
    _connection = null;

    try {
      if (connection != null) {
        try {
          await connection.output.writeString('\r');
          await connection.output.allSent;
          await Future<void>.delayed(const Duration(milliseconds: 80));
        } catch (_) {
          // Best-effort stop before closing the RFCOMM socket.
        }
        await connection.close();
        connection.dispose();
      }
    } finally {
      await _inputSubscription?.cancel();
      _inputSubscription = null;
      _rxBuffer = '';
      _setState(AtlasAdapterState.disconnected);
    }
  }
}
