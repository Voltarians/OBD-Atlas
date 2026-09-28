import 'dart:async';
import 'dart:convert';
import 'dart:io';

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
  AtlasAdapterState _state = AtlasAdapterState.disconnected;
  String _buffer = '';
  String _responseBuffer = '';
  bool _awaitingPrompt = false;
  bool _monitoring = false;
  bool _disconnecting = false;
  Completer<void>? _firstFrame;

  @override
  String get id => 'vlinker-ms:ch$channel:$portName';

  @override
  String get displayName => 'CH$channel vLinker MS $portName';

  @override
  String get transport => 'vLinker MS isolated serial';

  @override
  AtlasAdapterState get state => _state;

  @override
  Stream<CanFrame> get frames => _frames.stream;

  @override
  Stream<AtlasAdapterState> get states => _states.stream;

  static List<String> availablePorts() {
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
          .where((line) => RegExp(r'^COM\d+$', caseSensitive: false).hasMatch(line))
          .map((line) => line.toUpperCase())
          .toSet()
          .toList()
        ..sort(_compareComPorts);
      return ports;
    } on Object {
      return const <String>[];
    }
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
    if (!Platform.isWindows) {
      throw UnsupportedError(
        'vLinker MS isolated serial transport currently targets Windows.',
      );
    }

    _setState(AtlasAdapterState.connecting);
    _disconnecting = false;
    _firstFrame = Completer<void>();
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
      _write('STM');

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
    final process = _process;
    if (process == null) {
      throw StateError('vLinker MS isolated serial helper is not running');
    }
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
