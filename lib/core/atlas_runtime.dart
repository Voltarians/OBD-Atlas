import 'dart:async';
import 'dart:io';

import 'package:atlas_canalystii/atlas_canalystii.dart';
import 'package:atlas_gs_usb/atlas_gs_usb.dart';
import 'package:flutter/foundation.dart';

import '../adapters/atlas_adapter.dart';
import '../adapters/canalystii_adapter.dart';
import '../adapters/gs_usb_adapter.dart';
import '../adapters/linux_uc2_adapter.dart';
import '../adapters/linux_uc2_pair_adapter.dart';
import '../adapters/lys_usbcan_adapter.dart';
import '../adapters/slcan_adapter.dart';
import '../adapters/socketcan_adapter.dart';
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
  CanalystiiAdapter? _canalystAdapter;
  LysUsbcanAdapter? _lysAdapter;
  LinuxUc2PairAdapter? _linuxUc2PairAdapter;

  IOSink? _captureSink;
  File? activeCaptureFile;
  bool get isCapturing => _captureSink != null;

  List<String> scanSlcanPorts() => SlcanAdapter.availablePorts();
  Future<List<String>> scanSocketCanInterfaces() => SocketCanAdapter.availableInterfaces();
  Future<List<int>> scanLinuxUc2Devices() => LinuxUc2Adapter.availableDeviceIndices();
  String? get linuxUc2LibraryPath => LinuxUc2Adapter.findLibraryPath();
  Future<List<GsUsbDevice>> scanGsUsbDevices() => GsUsbAdapter.availableDevices();
  Future<List<CanalystiiDevice>> scanCanalystiiDevices() => CanalystiiAdapter.availableDevices();
  Future<bool> probeLysUsbcan() => LysUsbcanAdapter.probe();

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
    final active = channels.values
        .where((channel) => channel.adapterName != null)
        .map((channel) => channel.adapterName!)
        .toList();
    return active.isEmpty ? null : active.join(', ');
  }

  String? get lastError {
    final errors = channels.values
        .where((channel) => channel.lastError != null)
        .map((channel) => 'CH${channel.channel}: ${channel.lastError}')
        .toList();
    return errors.isEmpty ? null : errors.join('\n');
  }

  Future<void> connectSlcan(
    String portName, {
    int bitrate = 500000,
    int channel = 1,
  }) async {
    await _connectAdapter(
      SlcanAdapter(portName, bitrate: bitrate, channel: channel),
      channel,
    );
  }

  Future<void> connectSocketCan(String interfaceName, {int channel = 1}) async {
    await _connectAdapter(SocketCanAdapter(interfaceName, channel: channel), channel);
  }

  Future<void> connectLinuxUc2(
    int deviceIndex, {
    int bitrate = 500000,
    int channel = 1,
    int physicalCanChannel = 0,
  }) async {
    await _connectAdapter(
      LinuxUc2Adapter(
        deviceIndex: deviceIndex,
        bitrate: bitrate,
        channel: channel,
        physicalCanChannel: physicalCanChannel,
      ),
      channel,
    );
  }

  Future<void> connectLinuxUc2Pair({
    int bitrate = 500000,
    int baseChannel = 1,
    int firstDeviceIndex = 0,
    int secondDeviceIndex = 1,
  }) async {
    final adapter = LinuxUc2PairAdapter(
      bitrate: bitrate,
      baseChannel: baseChannel,
      firstDeviceIndex: firstDeviceIndex,
      secondDeviceIndex: secondDeviceIndex,
    );
    _linuxUc2PairAdapter = adapter;
    await _connectFourChannelAdapter(adapter, baseChannel);
  }

  Future<void> connectGsUsb(
    GsUsbDevice device, {
    int bitrate = 33333,
    int channel = 1,
  }) async {
    await _connectAdapter(
      GsUsbAdapter(device, bitrate: bitrate, channel: channel),
      channel,
    );
  }

  Future<void> connectCanalystii(
    CanalystiiDevice device, {
    int bitrate = 500000,
    int baseChannel = 2,
  }) async {
    final adapter = CanalystiiAdapter(
      device,
      bitrate: bitrate,
      baseChannel: baseChannel,
    );
    _canalystAdapter = adapter;
    await _connectDualAdapter(adapter, baseChannel);
  }

  Future<void> connectLysUsbcan({
    int bitrate = 500000,
    int baseChannel = 4,
  }) async {
    final adapter = LysUsbcanAdapter(
      bitrate: bitrate,
      baseChannel: baseChannel,
    );
    _lysAdapter = adapter;
    await _connectDualAdapter(adapter, baseChannel);
  }

  Future<void> _connectFourChannelAdapter(AtlasAdapter adapter, int baseChannel) async {
    if (baseChannel < 1 || baseChannel + 3 > 5) {
      throw ArgumentError.value(
        baseChannel,
        'baseChannel',
        'Four-channel UC2 session needs four consecutive Atlas channel slots.',
      );
    }

    for (var channel = baseChannel; channel <= baseChannel + 3; channel++) {
      await disconnectChannel(channel);
    }

    final slots = <AtlasChannelStatus>[
      channels[baseChannel]!,
      channels[baseChannel + 1]!,
      channels[baseChannel + 2]!,
      channels[baseChannel + 3]!,
    ];
    final names = <String>[
      '${adapter.displayName} • Device 0 / CAN0',
      '${adapter.displayName} • Device 0 / CAN1',
      '${adapter.displayName} • Device 1 / CAN0',
      '${adapter.displayName} • Device 1 / CAN1',
    ];

    for (var index = 0; index < slots.length; index++) {
      final slot = slots[index];
      slot.adapter = adapter;
      slot.adapterName = names[index];
      slot.state = AtlasAdapterState.connecting;
      slot.lastError = null;
    }
    notifyListeners();

    slots.first.stateSubscription = adapter.states.listen((state) {
      for (final slot in slots) {
        slot.state = state;
      }
      notifyListeners();
    });
    slots.first.frameSubscription = adapter.frames.listen(
      _onFrame,
      onError: (Object error) {
        for (final slot in slots) {
          slot.lastError = error.toString();
          slot.state = AtlasAdapterState.error;
        }
        notifyListeners();
      },
    );

    try {
      await adapter.connect();
      _startRateTimer();
    } catch (error) {
      for (final slot in slots) {
        slot.lastError = error.toString();
        slot.state = AtlasAdapterState.error;
      }
      notifyListeners();
      rethrow;
    }
  }

  Future<void> _connectDualAdapter(AtlasAdapter adapter, int baseChannel) async {
    if (baseChannel < 1 || baseChannel >= 5) {
      throw ArgumentError.value(
        baseChannel,
        'baseChannel',
        'Dual adapter needs two Atlas channel slots.',
      );
    }
    await disconnectChannel(baseChannel);
    await disconnectChannel(baseChannel + 1);
    final first = channels[baseChannel]!;
    final second = channels[baseChannel + 1]!;
    first.adapter = adapter;
    second.adapter = adapter;
    first.adapterName = '${adapter.displayName} • CAN1';
    second.adapterName = '${adapter.displayName} • CAN2';
    first.state = AtlasAdapterState.connecting;
    second.state = AtlasAdapterState.connecting;
    first.lastError = null;
    second.lastError = null;
    notifyListeners();

    first.stateSubscription = adapter.states.listen((state) {
      first.state = state;
      second.state = state;
      notifyListeners();
    });
    first.frameSubscription = adapter.frames.listen(
      _onFrame,
      onError: (Object error) {
        first.lastError = error.toString();
        second.lastError = error.toString();
        first.state = AtlasAdapterState.error;
        second.state = AtlasAdapterState.error;
        notifyListeners();
      },
    );

    try {
      await adapter.connect();
      _startRateTimer();
    } catch (error) {
      first.lastError = error.toString();
      second.lastError = error.toString();
      first.state = AtlasAdapterState.error;
      second.state = AtlasAdapterState.error;
      notifyListeners();
      rethrow;
    }
  }

  Future<void> _connectAdapter(AtlasAdapter adapter, int channel) async {
    if (channel < 1 || channel > 5) {
      throw ArgumentError.value(
        channel,
        'channel',
        'Atlas supports channels 1 through 5.',
      );
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

  Future<void> _disconnectSharedAdapter(AtlasAdapter adapter) async {
    final affected = channels.values
        .where((slot) => identical(slot.adapter, adapter))
        .toList();
    for (final slot in affected) {
      await slot.frameSubscription?.cancel();
      await slot.stateSubscription?.cancel();
      slot.frameSubscription = null;
      slot.stateSubscription = null;
    }
    await adapter.disconnect();
    for (final slot in affected) {
      slot.adapter = null;
      slot.adapterName = null;
      slot.state = AtlasAdapterState.disconnected;
      slot.lastError = null;
      slot.framesPerSecond = 0;
      slot.framesThisSecond = 0;
    }
    if (identical(adapter, _canalystAdapter)) _canalystAdapter = null;
    if (identical(adapter, _lysAdapter)) _lysAdapter = null;
    if (identical(adapter, _linuxUc2PairAdapter)) _linuxUc2PairAdapter = null;
  }

  Future<void> disconnectChannel(int channel) async {
    final slot = channels[channel];
    if (slot == null) return;

    if (_canalystAdapter != null && identical(slot.adapter, _canalystAdapter)) {
      await _disconnectSharedAdapter(_canalystAdapter!);
    } else if (_lysAdapter != null && identical(slot.adapter, _lysAdapter)) {
      await _disconnectSharedAdapter(_lysAdapter!);
    } else if (_linuxUc2PairAdapter != null && identical(slot.adapter, _linuxUc2PairAdapter)) {
      await _disconnectSharedAdapter(_linuxUc2PairAdapter!);
    } else {
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
    }

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
    if (_canalystAdapter != null) {
      await _disconnectSharedAdapter(_canalystAdapter!);
    }
    if (_lysAdapter != null) {
      await _disconnectSharedAdapter(_lysAdapter!);
    }
    if (_linuxUc2PairAdapter != null) {
      await _disconnectSharedAdapter(_linuxUc2PairAdapter!);
    }
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
