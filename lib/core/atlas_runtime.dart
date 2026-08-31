import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../adapters/atlas_adapter.dart';
import '../adapters/slcan_adapter.dart';
import 'can_frame.dart';
import 'local_store.dart';

class AtlasRuntime extends ChangeNotifier {
  AtlasRuntime._();
  static final AtlasRuntime instance = AtlasRuntime._();

  AtlasAdapter? _adapter;
  StreamSubscription<CanFrame>? _frameSubscription;
  StreamSubscription<AtlasAdapterState>? _stateSubscription;
  AtlasAdapterState adapterState = AtlasAdapterState.disconnected;
  String? adapterName;
  String? lastError;

  final List<CanFrame> recentFrames = <CanFrame>[];
  final Set<int> seenIds = <int>{};
  int totalFrames = 0;
  int framesThisSecond = 0;
  int framesPerSecond = 0;
  Timer? _rateTimer;

  IOSink? _captureSink;
  File? activeCaptureFile;
  bool get isCapturing => _captureSink != null;

  List<String> scanSlcanPorts() => SlcanAdapter.availablePorts();

  Future<void> connectSlcan(String portName, {int bitrate = 500000}) async {
    await disconnect();
    lastError = null;
    final adapter = SlcanAdapter(portName, bitrate: bitrate);
    _adapter = adapter;
    adapterName = adapter.displayName;
    adapterState = AtlasAdapterState.connecting;
    notifyListeners();

    _stateSubscription = adapter.states.listen((state) {
      adapterState = state;
      notifyListeners();
    });
    _frameSubscription = adapter.frames.listen(_onFrame);

    try {
      await adapter.connect();
      _startRateTimer();
    } catch (error) {
      lastError = error.toString();
      adapterState = AtlasAdapterState.error;
      notifyListeners();
      rethrow;
    }
  }

  void _onFrame(CanFrame frame) {
    totalFrames++;
    framesThisSecond++;
    seenIds.add(frame.id);
    recentFrames.insert(0, frame);
    if (recentFrames.length > 250) recentFrames.removeLast();
    _captureSink?.writeln(frame.toCandump());
    notifyListeners();
  }

  void _startRateTimer() {
    _rateTimer?.cancel();
    _rateTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      framesPerSecond = framesThisSecond;
      framesThisSecond = 0;
      notifyListeners();
    });
  }

  Future<File> startCapture() async {
    if (_adapter == null || adapterState != AtlasAdapterState.connected) {
      throw StateError('Connect an adapter before starting a capture.');
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

  Future<void> disconnect() async {
    await stopCapture();
    _rateTimer?.cancel();
    _rateTimer = null;
    framesPerSecond = 0;
    framesThisSecond = 0;
    await _frameSubscription?.cancel();
    await _stateSubscription?.cancel();
    _frameSubscription = null;
    _stateSubscription = null;
    final adapter = _adapter;
    _adapter = null;
    if (adapter != null) await adapter.disconnect();
    adapterName = null;
    adapterState = AtlasAdapterState.disconnected;
    notifyListeners();
  }
}
