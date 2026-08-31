import 'dart:async';
import 'dart:io';

import 'package:atlas_gs_usb/atlas_gs_usb.dart';
import 'package:flutter/foundation.dart';

import '../adapters/atlas_adapter.dart';
import '../adapters/gs_usb_adapter.dart';
import '../adapters/slcan_adapter.dart';
import 'can_frame.dart';
import 'local_store.dart';

class AtlasChannelStatus {
  AtlasChannelStatus(this.channel);

  final int channel;
  AtlasAdapter? adapter;
  AtlasAdapterState state = AtlasAdapterState.disconnected;
  String? adapterName;
  String? lastError;
  int totalFrames = 0;
  int framesThisSecond = 0;
  int framesPerSecond = 0;
  final Set<int> seenIds = <int>{};
  StreamSubscription<CanFrame>? frameSubscription;
  StreamSubscription<AtlasAdapterState>? stateSubscription;

  String get bus => 'can${channel - 1}';
  bool get connected => state == AtlasAdapterState.connected;
}

class AtlasRuntime extends ChangeNotifier {
  AtlasRuntime._() {
    for (var channel = 1; channel <= 5; channel++) {
      channels[channel] = AtlasChannelStatus(channel);
    }
  }

  static final AtlasRuntime instance = AtlasRuntime._();

  final Map<int, AtlasChannelStatus> channels = <int, AtlasChannelStatus>{};
  final List<CanFrame> recentFrames = <CanFrame>[];
  final Set<String> seenIds = <String>{};

  int totalFrames = 0;
  int framesThisSecond = 0;
  int framesPerSecond = 0;
  Timer? _rateTimer;

  IOSink? _captureSink;
  File? activeCaptureFile;
  bool get isCapturing => _captureSink != null;

  List<String> scanSlcanPorts() => SlcanAdapter.availablePorts();
  Future<List<GsUsbDevice>> scanGsUsbDevices() => GsUsbAdapter.availableDevices();

  int get connectedChannelCount => channels.values.where((channel) => channel.connected).length;
  bool get anyConnected => connectedChannelCount > 0;

  AtlasAdapterState get adapterState {
    if (channels.values.any((channel) => channel.state == AtlasAdapterState.error)) {
      return AtlasAdapterState.error;
    }
    if (channels.values.any((channel) => channel.state == AtlasAdapterState.connecting)) {
      return AtlasAdapterState.connecting;
    }
    if (anyConnected) return AtlasAdapterState.connected;
    return AtlasAdapterState.disconnected;
  }

  String? get adapterName {
    final active = channels.values.where((channel) => channel.adapterName != null).map((channel) => channel.adapterName!).toList();
    return active.isEmpty ? null : active.join(', ');
  }

  String? get lastError {
    final errors = channels.values.where((channel) => channel.lastError != null).map((channel) => 'CH${channel.channel}: ${channel.lastError}').toList();
    return errors.isEmpty ? null : errors.join('\n');
  }

  Future<void> connectSlcan(String portName, {int bitrate = 500000, int channel = 1}) async {
    final adapter = SlcanAdapter(portName, bitrate: bitrate, channel: channel);
    await _connectAdapter(adapter, channel);
  }

  Future<void> connectGsUsb(GsUsbDevice device, {int bitrate = 500000, int channel = 1}) async {
    final adapter = GsUsbAdapter(device, bitrate: bitrate, channel: channel);
    await _connectAdapter(adapter, channel);
  }

  Future<void> _connectAdapter(AtlasAdapter adapter, int channel) async {
    if (channel < 1 || channel > 5) {
      throw ArgumentError.value(channel, 'channel', 'Atlas supports channels 1 through 5.');
    }

    await disconnectChannel(channel);
    final slot = channels[channel]!;
    slot.lastError = null;
    slot.adapter = adapter;
    slot.adapterName = adapter.displayName;
    slot.state = AtlasAdapterState.connecting;
    notifyListeners();

    slot.stateSubscription = adapter.states.listen((state) {
      slot.state = state;
      notifyListeners();
    });
    slot.frameSubscription = adapter.frames.listen(
      _onFrame,
      onError: (Object error) {
        slot.lastError = error.toString();
        slot.state = AtlasAdapterState.error;
        notifyListeners();
      },
    );

    try {
      await adapter.connect();
      _startRateTimer();
    } catch (error) {
      slot.lastError = error.toString();
      slot.state = AtlasAdapterState.error;
      notifyListeners();
      rethrow;
    }
  }

  void _onFrame(CanFrame frame) {
    final slot = channels[frame.channel];
    totalFrames++;
    framesThisSecond++;
    seenIds.add('${frame.channel}:${frame.id}');

    if (slot != null) {
      slot.totalFrames++;
      slot.framesThisSecond++;
      slot.seenIds.add(frame.id);
    }

    recentFrames.insert(0, frame);
    if (recentFrames.length > 500) recentFrames.removeLast();
    _captureSink?.writeln(frame.toCandump());
    notifyListeners();
  }

  void _startRateTimer() {
    if (_rateTimer != null) return;
    _rateTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      framesPerSecond = framesThisSecond;
      framesThisSecond = 0;
      for (final slot in channels.values) {
        slot.framesPerSecond = slot.framesThisSecond;
        slot.framesThisSecond = 0;
      }
      notifyListeners();
    });
  }

  Future<File> startCapture() async {
    if (!anyConnected) {
      throw StateError('Connect at least one Atlas channel before starting a capture.');
    }
    if (isCapturing) return activeCaptureFile!;
    final file = await AtlasLocalStore.instance.createCaptureFile();
    activeCaptureFile = file;
    _captureSink = file.openWrite(mode: FileMode.writeOnlyAppend);
    notifyListeners();
    return file;
  }

  Future<File?> stopCapture() async {
    final sink = _captureSink;
    final file = activeCaptureFile;
    _captureSink = null;
    activeCaptureFile = null;
    if (sink != null) {
      await sink.flush();
      await sink.close();
    }
    notifyListeners();
    return file;
  }

  Future<void> disconnectChannel(int channel) async {
    final slot = channels[channel];
    if (slot == null) return;

    await slot.frameSubscription?.cancel();
    await slot.stateSubscription?.cancel();
    slot.frameSubscription = null;
    slot.stateSubscription = null;

    final adapter = slot.adapter;
    slot.adapter = null;
    if (adapter != null) await adapter.disconnect();

    slot.adapterName = null;
    slot.state = AtlasAdapterState.disconnected;
    slot.lastError = null;
    slot.framesPerSecond = 0;
    slot.framesThisSecond = 0;

    if (!anyConnected) {
      _rateTimer?.cancel();
      _rateTimer = null;
      framesPerSecond = 0;
      framesThisSecond = 0;
    }
    notifyListeners();
  }

  Future<void> disconnect() async {
    await stopCapture();
    for (var channel = 1; channel <= 5; channel++) {
      await disconnectChannel(channel);
    }
    _rateTimer?.cancel();
    _rateTimer = null;
    framesPerSecond = 0;
    framesThisSecond = 0;
    notifyListeners();
  }
}
