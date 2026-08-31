import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import 'adapters/atlas_adapter.dart';
import 'core/atlas_runtime.dart';
import 'core/local_store.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ObdAtlasApp());
}

class ObdAtlasApp extends StatelessWidget {
  const ObdAtlasApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'OBD Atlas',
      themeMode: ThemeMode.dark,
      darkTheme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.cyanAccent,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const AtlasHomePage(),
    );
  }
}

class AtlasHomePage extends StatefulWidget {
  const AtlasHomePage({super.key});

  @override
  State<AtlasHomePage> createState() => _AtlasHomePageState();
}

class _AtlasHomePageState extends State<AtlasHomePage> {
  int _selectedIndex = 0;

  static const _destinations = <NavigationDestination>[
    NavigationDestination(icon: Icon(Icons.directions_car), label: 'Vehicle'),
    NavigationDestination(icon: Icon(Icons.cable), label: 'Connect'),
    NavigationDestination(icon: Icon(Icons.fiber_manual_record), label: 'Capture'),
    NavigationDestination(icon: Icon(Icons.monitor_heart), label: 'Live'),
    NavigationDestination(icon: Icon(Icons.storage), label: 'Library'),
    NavigationDestination(icon: Icon(Icons.settings), label: 'Settings'),
  ];

  final _pages = const <Widget>[
    VehiclePage(),
    ConnectPage(),
    CapturePage(),
    LiveDataPage(),
    LibraryPage(),
    SettingsPage(),
  ];

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final body = Row(
      children: [
        if (wide)
          NavigationRail(
            selectedIndex: _selectedIndex,
            labelType: NavigationRailLabelType.all,
            onDestinationSelected: (index) => setState(() => _selectedIndex = index),
            destinations: _destinations
                .map((item) => NavigationRailDestination(
                      icon: item.icon,
                      selectedIcon: item.selectedIcon ?? item.icon,
                      label: Text(item.label),
                    ))
                .toList(),
          ),
        Expanded(child: _pages[_selectedIndex]),
      ],
    );

    return Scaffold(
      appBar: AppBar(
        title: const Text('OBD ATLAS'),
        actions: [
          AnimatedBuilder(
            animation: AtlasRuntime.instance,
            builder: (context, _) {
              final connected = AtlasRuntime.instance.adapterState == AtlasAdapterState.connected;
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Chip(
                  avatar: Icon(connected ? Icons.usb : Icons.offline_bolt, size: 18),
                  label: Text(connected ? 'ADAPTER CONNECTED' : 'OFFLINE READY'),
                ),
              );
            },
          )
        ],
      ),
      body: body,
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              selectedIndex: _selectedIndex,
              onDestinationSelected: (index) => setState(() => _selectedIndex = index),
              destinations: _destinations,
            ),
    );
  }
}

class PageShell extends StatelessWidget {
  const PageShell({super.key, required this.title, required this.subtitle, required this.child});
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

class VehiclePage extends StatelessWidget {
  const VehiclePage({super.key});

  @override
  Widget build(BuildContext context) {
    return PageShell(
      title: 'Vehicle Workspace',
      subtitle: 'Identify the vehicle, preserve research context, and keep every session tied to one machine.',
      child: Wrap(
        spacing: 12,
        runSpacing: 12,
        children: const [
          _MetricCard(label: 'Vehicle', value: 'Not selected', icon: Icons.directions_car),
          _MetricCard(label: 'VIN', value: '—', icon: Icons.pin),
          _MetricCard(label: 'Platform', value: 'Unknown', icon: Icons.account_tree),
          _MetricCard(label: 'Sessions', value: '0', icon: Icons.history),
        ],
      ),
    );
  }
}

class ConnectPage extends StatefulWidget {
  const ConnectPage({super.key});

  @override
  State<ConnectPage> createState() => _ConnectPageState();
}

class _ConnectPageState extends State<ConnectPage> {
  List<String> _ports = const [];
  String? _selectedPort;
  int _bitrate = 500000;

  void _scan() {
    final ports = AtlasRuntime.instance.scanSlcanPorts();
    setState(() {
      _ports = ports;
      if (_selectedPort == null || !ports.contains(_selectedPort)) {
        _selectedPort = ports.isEmpty ? null : ports.first;
      }
    });
  }

  Future<void> _connect() async {
    final port = _selectedPort;
    if (port == null) return;
    try {
      await AtlasRuntime.instance.connectSlcan(port, bitrate: _bitrate);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        final connected = runtime.adapterState == AtlasAdapterState.connected;
        return PageShell(
          title: 'Connect',
          subtitle: 'SLCAN is the first real transport. candleLight/gs_usb remains a separate native USB transport.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _StatusTile(
                name: 'USB CAN / CANable (SLCAN)',
                detail: connected ? '${runtime.adapterName} • $_bitrate bit/s' : runtime.adapterState.name,
                icon: Icons.usb,
              ),
              const _StatusTile(name: 'candleLight / gs_usb', detail: 'Native USB transport pending', icon: Icons.usb_rounded),
              const _StatusTile(name: 'ELM / OBDLink', detail: 'Transport pending', icon: Icons.bluetooth),
              const _StatusTile(name: 'J2534 / VCX', detail: 'Windows transport pending', icon: Icons.memory),
              const SizedBox(height: 12),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  FilledButton.icon(onPressed: _scan, icon: const Icon(Icons.search), label: const Text('Scan serial ports')),
                  SizedBox(
                    width: 220,
                    child: DropdownButtonFormField<String>(
                      initialValue: _selectedPort,
                      decoration: const InputDecoration(labelText: 'SLCAN port'),
                      items: _ports.map((port) => DropdownMenuItem(value: port, child: Text(port))).toList(),
                      onChanged: connected ? null : (value) => setState(() => _selectedPort = value),
                    ),
                  ),
                  SizedBox(
                    width: 180,
                    child: DropdownButtonFormField<int>(
                      initialValue: _bitrate,
                      decoration: const InputDecoration(labelText: 'CAN bitrate'),
                      items: const [
                        DropdownMenuItem(value: 125000, child: Text('125 kbit/s')),
                        DropdownMenuItem(value: 250000, child: Text('250 kbit/s')),
                        DropdownMenuItem(value: 500000, child: Text('500 kbit/s')),
                        DropdownMenuItem(value: 1000000, child: Text('1 Mbit/s')),
                      ],
                      onChanged: connected ? null : (value) => setState(() => _bitrate = value ?? 500000),
                    ),
                  ),
                  if (!connected)
                    FilledButton.icon(
                      onPressed: _selectedPort == null ? null : _connect,
                      icon: const Icon(Icons.link),
                      label: const Text('Connect SLCAN'),
                    )
                  else
                    FilledButton.tonalIcon(
                      onPressed: AtlasRuntime.instance.disconnect,
                      icon: const Icon(Icons.link_off),
                      label: const Text('Disconnect'),
                    ),
                ],
              ),
              if (runtime.lastError != null) ...[
                const SizedBox(height: 12),
                Text(runtime.lastError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
            ],
          ),
        );
      },
    );
  }
}

class CapturePage extends StatelessWidget {
  const CapturePage({super.key});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        final connected = runtime.adapterState == AtlasAdapterState.connected;
        return PageShell(
          title: 'Passive Capture',
          subtitle: 'Raw CAN traffic is preserved locally before interpretation.',
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  Icon(runtime.isCapturing ? Icons.stop_circle : Icons.fiber_manual_record, size: 56),
                  const SizedBox(height: 12),
                  Text(runtime.isCapturing ? 'Capture active' : connected ? 'Adapter ready' : 'No adapter connected'),
                  const SizedBox(height: 6),
                  Text('${runtime.totalFrames} total frames • ${runtime.framesPerSecond} frames/s'),
                  const SizedBox(height: 12),
                  if (!runtime.isCapturing)
                    FilledButton.icon(
                      onPressed: connected
                          ? () async {
                              try {
                                await runtime.startCapture();
                              } catch (error) {
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
                              }
                            }
                          : null,
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
                    const SizedBox(height: 8),
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

class LiveDataPage extends StatelessWidget {
  const LiveDataPage({super.key});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AtlasRuntime.instance,
      builder: (context, _) {
        final runtime = AtlasRuntime.instance;
        final frames = runtime.recentFrames.take(50).toList();
        return PageShell(
          title: 'Live Data',
          subtitle: 'Raw frame visibility first; decoding layers can bind to the same canonical stream later.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  _MetricCard(label: 'Frames/s', value: '${runtime.framesPerSecond}', icon: Icons.speed),
                  _MetricCard(label: 'Total frames', value: '${runtime.totalFrames}', icon: Icons.timeline),
                  _MetricCard(label: 'CAN IDs', value: '${runtime.seenIds.length}', icon: Icons.tag),
                  _MetricCard(label: 'Buffered', value: '${runtime.recentFrames.length}', icon: Icons.memory),
                ],
              ),
              const SizedBox(height: 16),
              Card(
                child: Column(
                  children: [
                    const ListTile(title: Text('Recent raw CAN frames')),
                    if (frames.isEmpty)
                      const ListTile(title: Text('No frames received yet'))
                    else
                      ...frames.map((frame) => ListTile(
                            dense: true,
                            leading: Text(frame.bus),
                            title: Text(frame.idHex),
                            subtitle: Text(frame.dataHex.isEmpty ? '(remote frame)' : frame.dataHex),
                            trailing: Text('DLC ${frame.dlc}'),
                          )),
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

class LibraryPage extends StatefulWidget {
  const LibraryPage({super.key});

  @override
  State<LibraryPage> createState() => _LibraryPageState();
}

class _LibraryPageState extends State<LibraryPage> {
  late Future<List<FileSystemEntity>> _logs;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  void _refresh() => _logs = AtlasLocalStore.instance.listLogs();

  Future<void> _import() async {
    final picked = await FilePicker.platform.pickFiles(
      allowMultiple: false,
      type: FileType.custom,
      allowedExtensions: const ['log', 'csv', 'txt', 'json', 'asc', 'trc'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    await AtlasLocalStore.instance.importLog(File(path));
    if (!mounted) return;
    setState(_refresh);
  }

  @override
  Widget build(BuildContext context) {
    return PageShell(
      title: 'Atlas Library',
      subtitle: 'Local vehicle captures remain available with no internet connection.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(onPressed: _import, icon: const Icon(Icons.file_open), label: const Text('Import capture')),
          ),
          const SizedBox(height: 12),
          FutureBuilder<List<FileSystemEntity>>(
            future: _logs,
            builder: (context, snapshot) {
              if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
              final logs = snapshot.data!;
              if (logs.isEmpty) return const Card(child: ListTile(title: Text('No local captures yet')));
              return Column(
                children: logs.map((entry) {
                  final fileName = entry.uri.pathSegments.where((e) => e.isNotEmpty).last;
                  final stat = entry.statSync();
                  return Card(
                    child: ListTile(
                      leading: const Icon(Icons.description),
                      title: Text(fileName),
                      subtitle: Text('${stat.size} bytes • ${stat.modified.toLocal()}'),
                    ),
                  );
                }).toList(),
              );
            },
          ),
        ],
      ),
    );
  }
}

class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    return PageShell(
      title: 'Settings',
      subtitle: 'Core application behavior is local by default. Internet services are not required for operation.',
      child: Column(
        children: const [
          SwitchListTile(value: true, onChanged: null, title: Text('Offline-first mode'), subtitle: Text('Permanent architectural default')),
          SwitchListTile(value: true, onChanged: null, title: Text('Preserve raw captures'), subtitle: Text('Keep source evidence before decoding')),
          ListTile(leading: Icon(Icons.cloud_off), title: Text('Cloud dependency'), trailing: Text('NONE')),
        ],
      ),
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.label, required this.value, required this.icon});
  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 220,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon),
              const SizedBox(height: 18),
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

class _StatusTile extends StatelessWidget {
  const _StatusTile({required this.name, required this.detail, required this.icon});
  final String name;
  final String detail;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: Icon(icon),
        title: Text(name),
        subtitle: Text(detail),
        trailing: const Icon(Icons.circle_outlined),
      ),
    );
  }
}