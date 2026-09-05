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
                  avatar: Icon(runtime.anyConnected ? Icons.link : Icons.link_off, size: 18),
                  label: Text(runtime.anyConnected
                      ? '${runtime.connectedChannelCount} CHANNELS CONNECTED'
                      : 'SOCKETCAN READY'),
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
  int _selectedChannel = 1;
  bool _scanning = false;
  bool _connecting = false;

  Future<void> _scan() async {
    setState(() => _scanning = true);
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
          const SnackBar(
            content: Text('No active SocketCAN interfaces found. Attach/configure a CAN adapter, then scan again.'),
          ),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
      }
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  Future<void> _connect() async {
    final interface = _selectedInterface;
    if (interface == null) return;
    setState(() => _connecting = true);
    try {
      await AtlasRuntime.instance.connectSocketCan(interface, channel: _selectedChannel);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
      }
    } finally {
      if (mounted) setState(() => _connecting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        return LinuxPageShell(
          title: 'Linux CAN Connections',
          subtitle: 'PCG-1 uses the Linux SocketCAN layer so Atlas is not tied to one USB-adapter vendor.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      FilledButton.icon(
                        onPressed: _scanning ? null : _scan,
                        icon: _scanning
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.search),
                        label: const Text('Scan SocketCAN'),
                      ),
                      SizedBox(
                        width: 240,
                        child: DropdownButtonFormField<String>(
                          key: ValueKey(_selectedInterface),
                          initialValue: _selectedInterface,
                          decoration: const InputDecoration(labelText: 'Linux CAN interface'),
                          items: _interfaces
                              .map((name) => DropdownMenuItem(value: name, child: Text(name)))
                              .toList(),
                          onChanged: _connecting ? null : (value) => setState(() => _selectedInterface = value),
                        ),
                      ),
                      SizedBox(
                        width: 160,
                        child: DropdownButtonFormField<int>(
                          initialValue: _selectedChannel,
                          decoration: const InputDecoration(labelText: 'Atlas channel'),
                          items: List<DropdownMenuItem<int>>.generate(
                            5,
                            (index) => DropdownMenuItem(
                              value: index + 1,
                              child: Text('CH${index + 1}'),
                            ),
                          ),
                          onChanged: _connecting ? null : (value) => setState(() => _selectedChannel = value ?? 1),
                        ),
                      ),
                      FilledButton.icon(
                        onPressed: _connecting || _selectedInterface == null ? null : _connect,
                        icon: const Icon(Icons.link),
                        label: const Text('Connect'),
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
                          ? '${slot.adapter?.transport ?? 'SocketCAN'} • ${slot.framesPerSecond} frames/s • ${slot.totalFrames} frames'
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
          subtitle: 'All connected SocketCAN channels feed the same Atlas candump-compatible capture stream.',
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
                          : 'Connect at least one SocketCAN interface'),
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
          subtitle: 'Raw Linux CAN traffic before decoding or interpretation.',
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
    return const LinuxPageShell(
      title: 'PCG-1 Linux Host',
      subtitle: 'Raspberry Pi / Linux is a first-class OBD Atlas deployment target.',
      child: Column(
        children: [
          ListTile(
            leading: Icon(Icons.memory),
            title: Text('Architecture'),
            trailing: Text('Linux ARM64'),
          ),
          ListTile(
            leading: Icon(Icons.settings_ethernet),
            title: Text('Primary vehicle transport'),
            trailing: Text('SocketCAN'),
          ),
          ListTile(
            leading: Icon(Icons.storage),
            title: Text('Capture format'),
            trailing: Text('candump compatible'),
          ),
          ListTile(
            leading: Icon(Icons.cloud_off),
            title: Text('Internet required at vehicle'),
            trailing: Text('NO'),
          ),
          ListTile(
            leading: Icon(Icons.info_outline),
            title: Text('Linux foundation'),
            trailing: Text('PCG-1 Build 1'),
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
