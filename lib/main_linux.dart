import 'dart:io';

import 'package:flutter/material.dart';

import 'adapters/atlas_adapter.dart';
import 'core/atlas_runtime.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  if (!Platform.isLinux) {
    throw UnsupportedError('main_linux.dart is the OBD Atlas Linux desktop entry point.');
  }
  runApp(const ObdAtlasLinuxApp());
}

class ObdAtlasLinuxApp extends StatelessWidget {
  const ObdAtlasLinuxApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'OBD Atlas • Linux',
      themeMode: ThemeMode.dark,
      darkTheme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.cyanAccent,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const LinuxHomePage(),
    );
  }
}

class LinuxHomePage extends StatefulWidget {
  const LinuxHomePage({super.key});

  @override
  State<LinuxHomePage> createState() => _LinuxHomePageState();
}

class _LinuxHomePageState extends State<LinuxHomePage> {
  int _index = 0;

  static const _destinations = <NavigationDestination>[
    NavigationDestination(icon: Icon(Icons.hub), label: 'Connect'),
    NavigationDestination(icon: Icon(Icons.fiber_manual_record), label: 'Capture'),
    NavigationDestination(icon: Icon(Icons.monitor_heart), label: 'Live'),
    NavigationDestination(icon: Icon(Icons.computer), label: 'PCG-1'),
  ];

  static const _pages = <Widget>[
    LinuxConnectPage(),
    LinuxCapturePage(),
    LinuxLivePage(),
    LinuxSystemPage(),
  ];

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 900;
    return Scaffold(
      appBar: AppBar(
        title: const Text('OBD ATLAS • LINUX'),
        actions: [
          AnimatedBuilder(
            animation: AtlasRuntime.instance,
            builder: (context, _) {
              final runtime = AtlasRuntime.instance;
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Chip(
                  avatar: Icon(runtime.anyConnected ? Icons.link : Icons.usb, size: 18),
                  label: Text(runtime.anyConnected
                      ? '${runtime.connectedChannelCount} CHANNELS CONNECTED'
                      : 'PCG-1 CAN READY'),
                ),
              );
            },
          ),
        ],
      ),
      body: Row(
        children: [
          if (wide)
            NavigationRail(
              selectedIndex: _index,
              labelType: NavigationRailLabelType.all,
              onDestinationSelected: (value) => setState(() => _index = value),
              destinations: _destinations
                  .map((item) => NavigationRailDestination(
                        icon: item.icon,
                        selectedIcon: item.selectedIcon ?? item.icon,
                        label: Text(item.label),
                      ))
                  .toList(),
            ),
          Expanded(child: _pages[_index]),
        ],
      ),
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              selectedIndex: _index,
              onDestinationSelected: (value) => setState(() => _index = value),
              destinations: _destinations,
            ),
    );
  }
}

class LinuxPageShell extends StatelessWidget {
  const LinuxPageShell({
    super.key,
    required this.title,
    required this.subtitle,
    required this.child,
  });

  final String title;
  final String subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 4),
        Text(subtitle, style: Theme.of(context).textTheme.bodyLarge),
        const SizedBox(height: 20),
        child,
      ],
    );
  }
}

class LinuxConnectPage extends StatefulWidget {
  const LinuxConnectPage({super.key});

  @override
  State<LinuxConnectPage> createState() => _LinuxConnectPageState();
}

class _LinuxConnectPageState extends State<LinuxConnectPage> {
  List<String> _interfaces = const <String>[];
  String? _selectedInterface;
  int _socketCanAtlasChannel = 5;
  bool _scanningSocketCan = false;
  bool _connectingSocketCan = false;

  List<int> _uc2Devices = const <int>[];
  int? _selectedUc2;
  int _uc2AtlasChannel = 1;
  int _uc2Bitrate = 500000;
  bool _scanningUc2 = false;
  bool _connectingUc2 = false;
  bool _connectingUc2Pair = false;

  Future<void> _scanSocketCan() async {
    setState(() => _scanningSocketCan = true);
    try {
      final interfaces = await AtlasRuntime.instance.scanSocketCanInterfaces();
      if (!mounted) return;
      setState(() {
        _interfaces = interfaces;
        if (_selectedInterface == null || !interfaces.contains(_selectedInterface)) {
          _selectedInterface = interfaces.isEmpty ? null : interfaces.first;
        }
      });
      if (interfaces.isEmpty && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No active SocketCAN interfaces found.')),
        );
      }
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _scanningSocketCan = false);
    }
  }

  Future<void> _connectSocketCan() async {
    final interface = _selectedInterface;
    if (interface == null) return;
    setState(() => _connectingSocketCan = true);
    try {
      await AtlasRuntime.instance.connectSocketCan(
        interface,
        channel: _socketCanAtlasChannel,
      );
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _connectingSocketCan = false);
    }
  }

  Future<void> _scanUc2() async {
    setState(() => _scanningUc2 = true);
    try {
      final devices = await AtlasRuntime.instance.scanLinuxUc2Devices();
      if (!mounted) return;
      setState(() {
        _uc2Devices = devices;
        if (_selectedUc2 == null || !devices.contains(_selectedUc2)) {
          _selectedUc2 = devices.isEmpty ? null : devices.first;
        }
      });
      final lib = AtlasRuntime.instance.linuxUc2LibraryPath;
      if (devices.isEmpty) {
        _showMessage('No 0471:1200 UC2 / LYS USBCAN adapters found.');
      } else if (lib == null) {
        _showMessage('UC2 detected, but ARM64 libusbcan.so was not found.');
      } else {
        _showMessage('${devices.length} UC2 adapter(s) detected • native ARM64 library ready.');
      }
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _scanningUc2 = false);
    }
  }

  Future<void> _connectUc2() async {
    final device = _selectedUc2;
    if (device == null) return;
    setState(() => _connectingUc2 = true);
    try {
      await AtlasRuntime.instance.connectLinuxUc2(
        device,
        bitrate: _uc2Bitrate,
        channel: _uc2AtlasChannel,
        physicalCanChannel: 0,
      );
      _showMessage('UC2 device $device CAN0 connected to Atlas CH$_uc2AtlasChannel.');
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _connectingUc2 = false);
    }
  }

  Future<void> _connectUc2Pair() async {
    if (_uc2Devices.length < 2) {
      _showMessage('Scan UC2 first. Two adapters are required.');
      return;
    }
    setState(() => _connectingUc2Pair = true);
    try {
      await AtlasRuntime.instance.connectLinuxUc2Pair(
        bitrate: _uc2Bitrate,
        baseChannel: 1,
        firstDeviceIndex: _uc2Devices[0],
        secondDeviceIndex: _uc2Devices[1],
      );
      _showMessage('Dual UC2 session connected • four physical CAN channels → Atlas CH1–CH4.');
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _connectingUc2Pair = false);
    }
  }

  void _showError(Object error) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        final uc2Busy = _connectingUc2 || _connectingUc2Pair;
        return LinuxPageShell(
          title: 'Linux CAN Connections',
          subtitle: 'PCG-1 five-channel foundation: four native UC2 CAN channels plus SocketCAN SWCAN.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(Icons.usb),
                        title: Text('UC2 / LYS USBCAN • 0471:1200'),
                        subtitle: Text('Two USBCAN2 adapters • CAN0 + CAN1 on each • Atlas CH1–CH4'),
                      ),
                      Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          FilledButton.icon(
                            onPressed: _scanningUc2 ? null : _scanUc2,
                            icon: _scanningUc2
                                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                                : const Icon(Icons.search),
                            label: const Text('Scan UC2'),
                          ),
                          FilledButton.icon(
                            onPressed: uc2Busy || _uc2Devices.length < 2 ? null : _connectUc2Pair,
                            icon: _connectingUc2Pair
                                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                                : const Icon(Icons.hub),
                            label: const Text('Connect 4 UC2 CAN → CH1–CH4'),
                          ),
                          SizedBox(
                            width: 190,
                            child: DropdownButtonFormField<int>(
                              key: ValueKey('uc2-$_selectedUc2'),
                              initialValue: _selectedUc2,
                              decoration: const InputDecoration(labelText: 'UC2 device'),
                              items: _uc2Devices
                                  .map((index) => DropdownMenuItem(value: index, child: Text('Device $index')))
                                  .toList(),
                              onChanged: uc2Busy ? null : (value) => setState(() => _selectedUc2 = value),
                            ),
                          ),
                          SizedBox(
                            width: 180,
                            child: DropdownButtonFormField<int>(
                              initialValue: _uc2Bitrate,
                              decoration: const InputDecoration(labelText: 'CAN bitrate'),
                              items: const [
                                DropdownMenuItem(value: 125000, child: Text('125 kbit/s')),
                                DropdownMenuItem(value: 250000, child: Text('250 kbit/s')),
                                DropdownMenuItem(value: 500000, child: Text('500 kbit/s')),
                                DropdownMenuItem(value: 800000, child: Text('800 kbit/s')),
                                DropdownMenuItem(value: 1000000, child: Text('1 Mbit/s')),
                              ],
                              onChanged: uc2Busy ? null : (value) => setState(() => _uc2Bitrate = value ?? 500000),
                            ),
                          ),
                          _channelPicker(
                            value: _uc2AtlasChannel,
                            enabled: !uc2Busy,
                            onChanged: (value) => setState(() => _uc2AtlasChannel = value),
                          ),
                          FilledButton.tonalIcon(
                            onPressed: uc2Busy || _selectedUc2 == null ? null : _connectUc2,
                            icon: const Icon(Icons.link),
                            label: const Text('Connect one UC2 CAN0'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _uc2Devices.length >= 2
                            ? 'Recommended: connect all four UC2 CAN controllers as one coordinated session; CH5 remains free for SWCAN.'
                            : 'Scan for both UC2 adapters to enable the four-channel coordinated session.',
                      ),
                      const SizedBox(height: 8),
                      SelectableText(
                        runtime.linuxUc2LibraryPath == null
                            ? 'ARM64 library: NOT FOUND'
                            : 'ARM64 library: ${runtime.linuxUc2LibraryPath}',
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(Icons.settings_ethernet),
                        title: Text('SocketCAN / SWCAN'),
                        subtitle: Text('CANable can0 • 33.333 kbit/s listen-only • recommended Atlas CH5'),
                      ),
                      Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          FilledButton.icon(
                            onPressed: _scanningSocketCan ? null : _scanSocketCan,
                            icon: _scanningSocketCan
                                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                                : const Icon(Icons.search),
                            label: const Text('Scan SocketCAN'),
                          ),
                          SizedBox(
                            width: 230,
                            child: DropdownButtonFormField<String>(
                              key: ValueKey('socket-$_selectedInterface'),
                              initialValue: _selectedInterface,
                              decoration: const InputDecoration(labelText: 'Linux CAN interface'),
                              items: _interfaces
                                  .map((name) => DropdownMenuItem(value: name, child: Text(name)))
                                  .toList(),
                              onChanged: _connectingSocketCan
                                  ? null
                                  : (value) => setState(() => _selectedInterface = value),
                            ),
                          ),
                          _channelPicker(
                            value: _socketCanAtlasChannel,
                            enabled: !_connectingSocketCan,
                            onChanged: (value) => setState(() => _socketCanAtlasChannel = value),
                          ),
                          FilledButton.icon(
                            onPressed: _connectingSocketCan || _selectedInterface == null ? null : _connectSocketCan,
                            icon: const Icon(Icons.link),
                            label: const Text('Connect SocketCAN'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              ...runtime.channels.values.map((slot) {
                final connected = slot.connected;
                final busy = slot.state == AtlasAdapterState.connecting;
                return Card(
                  child: ListTile(
                    leading: Icon(connected ? Icons.check_circle : busy ? Icons.sync : Icons.circle_outlined),
                    title: Text('CH${slot.channel} • ${slot.adapterName ?? slot.bus}'),
                    subtitle: Text(
                      connected
                          ? '${slot.adapter?.transport ?? 'CAN'} • ${slot.framesPerSecond} frames/s • ${slot.totalFrames} frames'
                          : slot.lastError ?? slot.state.name,
                    ),
                    trailing: slot.adapter == null
                        ? null
                        : FilledButton.tonalIcon(
                            onPressed: busy ? null : () => runtime.disconnectChannel(slot.channel),
                            icon: const Icon(Icons.link_off),
                            label: const Text('Disconnect'),
                          ),
                  ),
                );
              }),
              if (runtime.lastError != null) ...[
                const SizedBox(height: 8),
                Text(runtime.lastError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _channelPicker({
    required int value,
    required bool enabled,
    required ValueChanged<int> onChanged,
  }) {
    return SizedBox(
      width: 145,
      child: DropdownButtonFormField<int>(
        initialValue: value,
        decoration: const InputDecoration(labelText: 'Atlas channel'),
        items: List<DropdownMenuItem<int>>.generate(
          5,
          (index) => DropdownMenuItem(
            value: index + 1,
            child: Text('CH${index + 1}'),
          ),
        ),
        onChanged: enabled ? (selected) => onChanged(selected ?? value) : null,
      ),
    );
  }
}

class LinuxCapturePage extends StatelessWidget {
  const LinuxCapturePage({super.key});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        return LinuxPageShell(
          title: 'Passive Capture',
          subtitle: 'All connected Linux CAN transports feed the same Atlas candump-compatible evidence stream.',
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  Icon(runtime.isCapturing ? Icons.stop_circle : Icons.fiber_manual_record, size: 56),
                  const SizedBox(height: 12),
                  Text(runtime.isCapturing
                      ? 'Capture active'
                      : runtime.anyConnected
                          ? '${runtime.connectedChannelCount} channels ready'
                          : 'Connect at least one CAN interface'),
                  const SizedBox(height: 6),
                  Text('${runtime.totalFrames} total frames • ${runtime.framesPerSecond} frames/s'),
                  const SizedBox(height: 12),
                  if (!runtime.isCapturing)
                    FilledButton.icon(
                      onPressed: runtime.anyConnected ? runtime.startCapture : null,
                      icon: const Icon(Icons.play_arrow),
                      label: const Text('Start capture'),
                    )
                  else
                    FilledButton.icon(
                      onPressed: runtime.stopCapture,
                      icon: const Icon(Icons.stop),
                      label: const Text('Stop capture'),
                    ),
                  if (runtime.activeCaptureFile != null) ...[
                    const SizedBox(height: 10),
                    SelectableText(runtime.activeCaptureFile!.path),
                  ],
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class LinuxLivePage extends StatelessWidget {
  const LinuxLivePage({super.key});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        final frames = runtime.recentFrames.take(100).toList();
        return LinuxPageShell(
          title: 'Live CAN',
          subtitle: 'Raw CAN traffic before decoding or interpretation.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  _LinuxMetric(label: 'Frames/s', value: '${runtime.framesPerSecond}', icon: Icons.speed),
                  _LinuxMetric(label: 'Total', value: '${runtime.totalFrames}', icon: Icons.timeline),
                  _LinuxMetric(label: 'CAN IDs', value: '${runtime.seenIds.length}', icon: Icons.tag),
                  _LinuxMetric(label: 'Channels', value: '${runtime.connectedChannelCount}', icon: Icons.hub),
                ],
              ),
              const SizedBox(height: 16),
              Card(
                child: Column(
                  children: [
                    const ListTile(title: Text('Recent frames')),
                    if (frames.isEmpty)
                      const ListTile(title: Text('No frames received yet'))
                    else
                      ...frames.map(
                        (frame) => ListTile(
                          dense: true,
                          leading: Text(frame.bus),
                          title: Text(frame.idHex),
                          subtitle: Text(frame.dataHex.isEmpty ? '(remote frame)' : frame.dataHex),
                          trailing: Text('DLC ${frame.dlc}'),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class LinuxSystemPage extends StatelessWidget {
  const LinuxSystemPage({super.key});

  @override
  Widget build(BuildContext context) {
    final lib = AtlasRuntime.instance.linuxUc2LibraryPath;
    return LinuxPageShell(
      title: 'PCG-1 Linux Host',
      subtitle: 'Raspberry Pi / Linux is a first-class OBD Atlas deployment target.',
      child: Column(
        children: [
          const ListTile(
            leading: Icon(Icons.memory),
            title: Text('Architecture'),
            trailing: Text('Linux ARM64'),
          ),
          const ListTile(
            leading: Icon(Icons.settings_ethernet),
            title: Text('CAN transports'),
            trailing: Text('4× UC2 CAN + SWCAN'),
          ),
          ListTile(
            leading: const Icon(Icons.usb),
            title: const Text('UC2 ARM64 library'),
            subtitle: SelectableText(lib ?? 'Not found'),
            trailing: Icon(lib == null ? Icons.error_outline : Icons.check_circle),
          ),
          const ListTile(
            leading: Icon(Icons.storage),
            title: Text('Capture format'),
            trailing: Text('candump compatible'),
          ),
          const ListTile(
            leading: Icon(Icons.cloud_off),
            title: Text('Internet required at vehicle'),
            trailing: Text('NO'),
          ),
          const ListTile(
            leading: Icon(Icons.info_outline),
            title: Text('Linux foundation'),
            trailing: Text('PCG-1 Build 4 • five channels'),
          ),
        ],
      ),
    );
  }
}

class _LinuxMetric extends StatelessWidget {
  const _LinuxMetric({required this.label, required this.value, required this.icon});

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 210,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon),
              const SizedBox(height: 12),
              Text(value, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 4),
              Text(label),
            ],
          ),
        ),
      ),
    );
  }
}
