import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atlas_android_rfcomm/atlas_android_rfcomm.dart';

import '../core/can_frame.dart';
import 'atlas_adapter.dart';

/// Receive-only vLinker MS transport for Windows Bluetooth/serial COM ports.
///
/// The COM port is intentionally owned by an isolated PowerShell/.NET helper
/// process. This keeps native Windows serial-driver or CRT failures outside the
/// Flutter process so a failed/retried Bluetooth SPP connection cannot take
/// Atlas down with it.
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

  Process? _process;
  StreamSubscription<String>? _stdoutSubscription;
  StreamSubscription<String>? _stderrSubscription;
  StreamSubscription<Uint8List>? _androidBytesSubscription;
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  String _buffer = '';
  String _responseBuffer = '';
  bool _awaitingPrompt = false;
  bool _monitoring = false;
  bool _disconnecting = false;
  Completer<void>? _firstFrame;
  Timer? _androidBankTimer;
  bool _rotatingAndroidBank = false;
  bool _characterizingAndroid = false;
  final Map<int, int> _androidCharacterizationCounts = <int, int>{};
  List<List<int>> _androidFilterBanks = const <List<int>>[];
  int _androidBankIndex = 0;

  static const double productionTargetFps = 1500;
  static const int productionMaxExactFilters = 32;
  static const Duration androidCharacterizationDuration = Duration(seconds: 2);
  static const Duration androidBankRotationInterval = Duration(seconds: 5);

  @override
  String get id => 'vlinker-ms:ch$channel:$portName';

  @override
  String get displayName => 'CH$channel vLinker MS $portName';

  @override
  String get transport => Platform.isAndroid
      ? 'vLinker MS Android RFCOMM'
      : 'vLinker MS isolated serial';

  @override
  AtlasAdapterState get state => _state;

  @override
  Stream<CanFrame> get frames => _frames.stream;

  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  static Future<List<String>> availablePorts() async {
    if (Platform.isAndroid) {
      final granted = await AtlasAndroidRfcomm.requestConnectPermission();
      if (!granted) {
        throw StateError(
          'Bluetooth permission is required to use the vLinker MS on Android.',
        );
      }
      final devices = await AtlasAndroidRfcomm.pairedDevices();
      return devices
          .where((device) {
            final name = device.name.toLowerCase();
            return name.contains('vlinker') ||
                name.contains('obd') ||
                name.contains('stn');
          })
          .map((device) => device.label)
          .toList(growable: false);
    }

    if (!Platform.isWindows) return const <String>[];
    try {
      final result = Process.runSync(
        'powershell.exe',
        const <String>[
          '-NoProfile',
          '-NonInteractive',
          '-Command',
          'Get-CimInstance Win32_SerialPort | Select-Object -ExpandProperty DeviceID',
        ],
        stdoutEncoding: utf8,
        stderrEncoding: utf8,
      );
      if (result.exitCode != 0) return const <String>[];
      final ports = const LineSplitter()
          .convert('${result.stdout}')
          .map((line) => line.trim())
          .where(
            (line) => RegExp(
              r'^COM\d+$',
              caseSensitive: false,
            ).hasMatch(line),
          )
          .map((line) => line.toUpperCase())
          .toSet()
          .toList()
        ..sort(_compareComPorts);
      return ports;
    } on Object {
      return const <String>[];
    }
  }

  static String? androidAddressFromLabel(String value) {
    final match = RegExp(
      r'([0-9A-F]{2}:){5}[0-9A-F]{2}',
      caseSensitive: false,
    ).firstMatch(value);
    return match?.group(0)?.toUpperCase();
  }

  static String _encodePowerShellCommand(String command) {
    final bytes = <int>[];
    for (final codeUnit in command.codeUnits) {
      bytes
        ..add(codeUnit & 0xFF)
        ..add((codeUnit >> 8) & 0xFF);
    }
    return base64.encode(bytes);
  }

  static int _compareComPorts(String a, String b) {
    int number(String value) =>
        int.tryParse(value.replaceFirst(RegExp(r'^COM', caseSensitive: false), '')) ??
        1 << 30;
    return number(a).compareTo(number(b));
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

    if (Platform.isAndroid) {
      await _connectAndroid();
      return;
    }

    if (!Platform.isWindows) {
      _setState(AtlasAdapterState.error);
      throw UnsupportedError(
        'vLinker MS is currently supported on Windows and Android.',
      );
    }

    final ready = Completer<void>();
    final encodedCommand = _encodePowerShellCommand(_serialBridgePowerShell);

    late final Process process;
    try {
      process = await Process.start(
        'powershell.exe',
        <String>[
          '-NoProfile',
          '-NonInteractive',
          '-ExecutionPolicy',
          'Bypass',
          '-EncodedCommand',
          encodedCommand,
        ],
        environment: <String, String>{
          ...Platform.environment,
          'ATLAS_PORT': portName,
          'ATLAS_BAUD': '$baudRate',
        },
      );
    } catch (error) {
      _setState(AtlasAdapterState.error);
      throw StateError('Unable to start isolated serial helper: $error');
    }

    _process = process;
    _stdoutSubscription = process.stdout
        .transform(const AsciiDecoder(allowInvalid: true))
        .listen(_onText, onError: _onTransportError);
    _stderrSubscription = process.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
      final trimmed = line.trim();
      if (trimmed == 'READY') {
        if (!ready.isCompleted) ready.complete();
      } else if (trimmed.startsWith('ERROR ')) {
        if (!ready.isCompleted) {
          ready.completeError(StateError(trimmed.substring(6)));
        } else if (!_disconnecting) {
          _setState(AtlasAdapterState.error);
          _frames.addError(StateError(trimmed.substring(6)));
        }
      }
    });

    unawaited(process.exitCode.then((code) {
      if (!ready.isCompleted) {
        ready.completeError(
          StateError('vLinker MS serial helper exited before READY (code $code).'),
        );
      }
      if (!_disconnecting && _state != AtlasAdapterState.disconnected) {
        final error = StateError(
          'vLinker MS isolated serial helper exited with code $code.',
        );
        _setState(AtlasAdapterState.error);
        _frames.addError(error);
      }
    }));

    try {
      await ready.future.timeout(
        const Duration(seconds: 10),
        onTimeout: () => throw TimeoutException(
          'Timed out opening $portName. Confirm the vLinker MS is paired and '
          'that this is the Windows outgoing Bluetooth serial COM port.',
        ),
      );

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
      await _write('STM');

      await _firstFrame!.future.timeout(
        const Duration(seconds: 6),
        onTimeout: () => throw TimeoutException(
          'vLinker MS monitor started but no CAN frames were received. '
          'Confirm the correct outgoing COM port is selected and the '
          'vehicle HS-CAN bus is active.',
        ),
      );
      _setState(AtlasAdapterState.connected);
    } catch (_) {
      await disconnect();
      rethrow;
    }
  }

  void _onTransportError(Object error, StackTrace stack) {
    if (_disconnecting) return;
    _setState(AtlasAdapterState.error);
    _frames.addError(error, stack);
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
      await _write(command);
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

  Future<void> _write(String command) async {
    final bytes = Uint8List.fromList(ascii.encode('$command\r'));
    if (Platform.isAndroid) {
      await AtlasAndroidRfcomm.write(bytes);
      return;
    }

    final process = _process;
    if (process == null) {
      throw StateError('vLinker MS isolated serial helper is not running');
    }
    process.stdin.add(bytes);
  }

  Future<void> _connectAndroid() async {
    final granted = await AtlasAndroidRfcomm.requestConnectPermission();
    if (!granted) {
      _setState(AtlasAdapterState.error);
      throw StateError(
        'Bluetooth permission is required to connect the vLinker MS.',
      );
    }

    final address = androidAddressFromLabel(portName);
    if (address == null) {
      _setState(AtlasAdapterState.error);
      throw StateError('No Bluetooth address found in $portName');
    }

    _androidBytesSubscription = AtlasAndroidRfcomm.bytes.listen(
      (bytes) => _onText(ascii.decode(bytes, allowInvalid: true)),
      onError: (Object error, StackTrace stack) =>
          _onTransportError(error, stack),
    );

    try {
      await AtlasAndroidRfcomm.connect(address).timeout(
        const Duration(seconds: 12),
        onTimeout: () => throw TimeoutException(
          'Timed out connecting to vLinker MS $address over Android RFCOMM.',
        ),
      );

      await _command('ATZ', timeout: const Duration(seconds: 4));
      await _command('ATE0');
      await _command('ATL0');
      await _command('ATS0');
      await _command('ATH1');
      await _command('ATD0');
      await _command('ATAL');
      await _command('ATCFC0');
      await _command('STP 31');
      await _command('STCMM 0');

      // Android Bluetooth cannot sustain unrestricted Gen-1 Volt HS-CAN
      // indefinitely. Take a short full-pass census, then switch to exact
      // filters packed below the measured 1,500 fps production envelope.
      await _characterizeAndroidHsCan();
      _firstFrame = Completer<void>();
      await _startAndroidProductionBank(0);

      await _firstFrame!.future.timeout(
        const Duration(seconds: 6),
        onTimeout: () => throw TimeoutException(
          'vLinker MS production filter bank started but no HS-CAN frames '
          'were received. Confirm the vehicle bus is active.',
        ),
      );
      _setState(AtlasAdapterState.connected);
      _startAndroidBankRotation();
    } catch (_) {
      await disconnect();
      rethrow;
    }
  }

  static List<List<int>> planProductionFilterBanks(
    Map<int, int> frameCounts,
    Duration sampleDuration, {
    double targetFramesPerSecond = productionTargetFps,
    int maxExactFilters = productionMaxExactFilters,
    double headroom = 0.85,
  }) {
    if (frameCounts.isEmpty || sampleDuration <= Duration.zero) {
      return const <List<int>>[];
    }
    if (targetFramesPerSecond <= 0 ||
        maxExactFilters <= 0 ||
        headroom <= 0 ||
        headroom > 1) {
      throw ArgumentError('Invalid production filter-bank limits.');
    }

    final sampleSeconds =
        sampleDuration.inMicroseconds / Duration.microsecondsPerSecond;
    final budget = targetFramesPerSecond * headroom;
    final entries = frameCounts.entries
        .where((entry) => entry.key >= 0 && entry.key <= 0x7FF && entry.value > 0)
        .map(
          (entry) => (
            id: entry.key,
            fps: entry.value / sampleSeconds,
          ),
        )
        .toList()
      ..sort((a, b) {
        final byRate = b.fps.compareTo(a.fps);
        return byRate != 0 ? byRate : a.id.compareTo(b.id);
      });

    final banks = <List<int>>[];
    final bankRates = <double>[];

    for (final entry in entries) {
      var placed = false;
      for (var index = 0; index < banks.length; index++) {
        if (banks[index].length >= maxExactFilters) continue;
        if (bankRates[index] + entry.fps > budget) continue;
        banks[index].add(entry.id);
        bankRates[index] += entry.fps;
        placed = true;
        break;
      }
      if (!placed) {
        banks.add(<int>[entry.id]);
        bankRates.add(entry.fps);
      }
    }

    for (final bank in banks) {
      bank.sort();
    }
    return banks;
  }

  Future<void> _characterizeAndroidHsCan() async {
    _androidBankTimer?.cancel();
    _androidBankTimer = null;
    _androidCharacterizationCounts.clear();
    _androidFilterBanks = const <List<int>>[];
    _androidBankIndex = 0;

    await _command('STFAC');
    await _command('STFPA 000,000');

    _characterizingAndroid = true;
    _monitoring = true;
    await _write('STM');
    await Future<void>.delayed(androidCharacterizationDuration);
    await _stopAndroidMonitor();
    _characterizingAndroid = false;

    _androidFilterBanks = planProductionFilterBanks(
      _androidCharacterizationCounts,
      androidCharacterizationDuration,
    );
    if (_androidFilterBanks.isEmpty) {
      throw StateError(
        'vLinker MS characterization received no usable 11-bit HS-CAN IDs.',
      );
    }
  }

  Future<void> _stopAndroidMonitor() async {
    if (!_monitoring) return;
    _monitoring = false;
    _responseBuffer = '';
    _awaitingPrompt = true;
    final future = _responses.stream.first.timeout(
      const Duration(seconds: 2),
      onTimeout: () => throw TimeoutException(
        'Timed out stopping vLinker MS monitor for filter reconfiguration.',
      ),
    );
    try {
      await AtlasAndroidRfcomm.write(
        Uint8List.fromList(const <int>[13]),
      );
      await future;
    } finally {
      _awaitingPrompt = false;
    }
  }

  Future<void> _startAndroidProductionBank(int bankIndex) async {
    if (_androidFilterBanks.isEmpty) {
      throw StateError('No vLinker MS production filter banks are available.');
    }
    final index = bankIndex % _androidFilterBanks.length;
    final bank = _androidFilterBanks[index];

    await _command('STFPC');
    for (final id in bank) {
      final idText = id.toRadixString(16).toUpperCase().padLeft(3, '0');
      await _command('STFPA $idText,7FF');
    }

    _androidBankIndex = index;
    _monitoring = true;
    await _write('STM');
  }

  void _startAndroidBankRotation() {
    _androidBankTimer?.cancel();
    if (_androidFilterBanks.length <= 1) return;
    _androidBankTimer = Timer.periodic(androidBankRotationInterval, (_) {
      unawaited(_rotateAndroidProductionBank());
    });
  }

  Future<void> _rotateAndroidProductionBank() async {
    if (_rotatingAndroidBank ||
        _disconnecting ||
        _state != AtlasAdapterState.connected ||
        _androidFilterBanks.length <= 1) {
      return;
    }
    _rotatingAndroidBank = true;
    try {
      await _stopAndroidMonitor();
      await _startAndroidProductionBank(
        (_androidBankIndex + 1) % _androidFilterBanks.length,
      );
    } catch (error, stack) {
      if (!_disconnecting) {
        _setState(AtlasAdapterState.error);
        _frames.addError(error, stack);
      }
    } finally {
      _rotatingAndroidBank = false;
    }
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
      if (terminalError != null) {
        _monitoring = false;
        _setState(AtlasAdapterState.error);
        _frames.addError(StateError(terminalError));
        continue;
      }

      final frame = parseMonitorLine(line, channel: channel);
      if (frame != null) {
        if (_characterizingAndroid && !frame.extended) {
          _androidCharacterizationCounts.update(
            frame.id,
            (count) => count + 1,
            ifAbsent: () => 1,
          );
        }
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
    _disconnecting = true;

    if (Platform.isAndroid) {
      _androidBankTimer?.cancel();
      _androidBankTimer = null;
      _rotatingAndroidBank = false;
      _characterizingAndroid = false;
      if (_monitoring) {
        try {
          await AtlasAndroidRfcomm.write(
            Uint8List.fromList(const <int>[13]),
          );
          await Future<void>.delayed(const Duration(milliseconds: 100));
        } catch (_) {}
      }
      await _androidBytesSubscription?.cancel();
      _androidBytesSubscription = null;
      try {
        await AtlasAndroidRfcomm.close();
      } catch (_) {}
      _monitoring = false;
      _buffer = '';
      _responseBuffer = '';
      _awaitingPrompt = false;
      _firstFrame = null;
      _setState(AtlasAdapterState.disconnected);
      return;
    }

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

      try {
        await process.exitCode.timeout(const Duration(seconds: 2));
      } on TimeoutException {
        process.kill();
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

  static const String _serialBridgePowerShell = r'''
$source = @"
using System;
using System.IO;
using System.IO.Ports;

public static class AtlasSerialBridge
{
    public static int Run(string portName, int baud)
    {
        using (var port = new SerialPort(
            portName, baud, Parity.None, 8, StopBits.One))
        {
            port.Handshake = Handshake.None;
            port.ReadTimeout = 250;
            port.WriteTimeout = 1000;
            port.DtrEnable = false;
            port.RtsEnable = false;
            port.Open();

            var output = Console.OpenStandardOutput();
            port.DataReceived += (sender, args) =>
            {
                try
                {
                    int available = port.BytesToRead;
                    if (available <= 0) return;
                    var buffer = new byte[available];
                    int read = port.Read(buffer, 0, buffer.Length);
                    if (read > 0)
                    {
                        output.Write(buffer, 0, read);
                        output.Flush();
                    }
                }
                catch
                {
                }
            };

            Console.Error.WriteLine("READY");
            Console.Error.Flush();

            var input = Console.OpenStandardInput();
            var inbound = new byte[1024];
            while (true)
            {
                int read = input.Read(inbound, 0, inbound.Length);
                if (read <= 0) break;
                port.Write(inbound, 0, read);
            }
        }
        return 0;
    }
}
"@

try {
    Add-Type -TypeDefinition $source -Language CSharp
    $portName = $env:ATLAS_PORT
    $baud = [int]$env:ATLAS_BAUD
    exit [AtlasSerialBridge]::Run($portName, $baud)
}
catch {
    $message = $_.Exception.GetBaseException().Message
    [Console]::Error.WriteLine("ERROR " + $message)
    [Console]::Error.Flush()
    exit 2
}
''';
}
