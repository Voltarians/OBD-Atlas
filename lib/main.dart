import 'dart:io';

import 'package:atlas_canalystii/atlas_canalystii.dart';
import 'package:atlas_gs_usb/atlas_gs_usb.dart';
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
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.cyanAccent, brightness: Brightness.dark),
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
    VehiclePage(), ConnectPage(), CapturePage(), LiveDataPage(), LibraryPage(), SettingsPage(),
  ];

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 900;
    return Scaffold(
      appBar: AppBar(
        title: const Text('OBD ATLAS'),
        actions: [AnimatedBuilder(
          animation: AtlasRuntime.instance,
          builder: (context, _) {
            final connected = AtlasRuntime.instance.adapterState == AtlasAdapterState.connected;
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Chip(
                avatar: Icon(connected ? Icons.usb : Icons.offline_bolt, size: 18),
                label: Text(connected ? '${AtlasRuntime.instance.connectedChannelCount} CHANNELS CONNECTED' : 'OFFLINE READY'),
              ),
            );
          },
        )],
      ),
      body: Row(children: [
        if (wide)
          NavigationRail(
            selectedIndex: _selectedIndex,
            labelType: NavigationRailLabelType.all,
            onDestinationSelected: (index) => setState(() => _selectedIndex = index),
            destinations: _destinations.map((item) => NavigationRailDestination(
              icon: item.icon,
              selectedIcon: item.selectedIcon ?? item.icon,
              label: Text(item.label),
            )).toList(),
          ),
        Expanded(child: _pages[_selectedIndex]),
      ]),
      bottomNavigationBar: wide ? null : NavigationBar(
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
  Widget build(BuildContext context) => ListView(
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

class VehiclePage extends StatelessWidget {
  const VehiclePage({super.key});
  @override
  Widget build(BuildContext context) => const PageShell(
    title: 'Vehicle Workspace',
    subtitle: 'Identify the vehicle, preserve research context, and keep every session tied to one machine.',
    child: Wrap(spacing: 12, runSpacing: 12, children: [
      _MetricCard(label: 'Vehicle', value: 'Not selected', icon: Icons.directions_car),
      _MetricCard(label: 'VIN', value: '—', icon: Icons.pin),
      _MetricCard(label: 'Platform', value: 'Unknown', icon: Icons.account_tree),
      _MetricCard(label: 'Sessions', value: '0', icon: Icons.history),
    ]),
  );
}

class ConnectPage extends StatefulWidget {
  const ConnectPage({super.key});
  @override
  State<ConnectPage> createState() => _ConnectPageState();
}

class _ConnectPageState extends State<ConnectPage> {
  List<String> _ports = const [];
  String? _selectedPort;
  List<GsUsbDevice> _gsDevices = const [];
  String? _selectedGsPath;
  List<CanalystiiDevice> _caDevices = const [];
  String? _selectedCaPath;
  int _bitrate = 500000;
  bool _scanningUsb = false;
  bool _scanningCa = false;
  bool _probingLys = false;
  bool _lysAvailable = false;

  void _scanSlcan() {
    final ports = AtlasRuntime.instance.scanSlcanPorts();
    setState(() {
      _ports = ports;
      if (_selectedPort == null || !ports.contains(_selectedPort)) _selectedPort = ports.isEmpty ? null : ports.first;
    });
  }

  Future<void> _scanGsUsb() async {
    setState(() => _scanningUsb = true);
    try {
      final devices = await AtlasRuntime.instance.scanGsUsbDevices();
      if (!mounted) return;
      setState(() {
        _gsDevices = devices;
        if (_selectedGsPath == null || !devices.any((d) => d.path == _selectedGsPath)) _selectedGsPath = devices.isEmpty ? null : devices.first.path;
      });
      if (devices.isEmpty && mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No candleLight/gs_usb device found.')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
    } finally {
      if (mounted) setState(() => _scanningUsb = false);
    }
  }

  Future<void> _scanCanalystii() async {
    setState(() => _scanningCa = true);
    try {
      final devices = await AtlasRuntime.instance.scanCanalystiiDevices();
      if (!mounted) return;
      setState(() {
        _caDevices = devices;
        if (_selectedCaPath == null || !devices.any((d) => d.path == _selectedCaPath)) _selectedCaPath = devices.isEmpty ? null : devices.first.path;
      });
      if (devices.isEmpty && mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No CANalyst-II 04D8:0053 device found.')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
    } finally {
      if (mounted) setState(() => _scanningCa = false);
    }
  }

  Future<void> _probeLys() async {
    setState(() => _probingLys = true);
    try {
      final found = await AtlasRuntime.instance.probeLysUsbcan();
      if (!mounted) return;
      setState(() => _lysAvailable = found);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(found ? 'LYS USBCAN-II detected through ControlCAN.dll.' : 'LYS USBCAN-II did not open.')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
    } finally {
      if (mounted) setState(() => _probingLys = false);
    }
  }

  Future<void> _connectGsUsb() async {
    final device = _gsDevices.where((d) => d.path == _selectedGsPath).firstOrNull;
    if (device == null) return;
    try { await AtlasRuntime.instance.connectGsUsb(device, bitrate: _bitrate, channel: 1); }
    catch (error) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString()))); }
  }

  Future<void> _connectSlcan() async {
    if (_selectedPort == null) return;
    try { await AtlasRuntime.instance.connectSlcan(_selectedPort!, bitrate: _bitrate, channel: 1); }
    catch (error) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString()))); }
  }

  Future<void> _connectCanalystii() async {
    final device = _caDevices.where((d) => d.path == _selectedCaPath).firstOrNull;
    if (device == null) return;
    try { await AtlasRuntime.instance.connectCanalystii(device, bitrate: _bitrate, baseChannel: 2); }
    catch (error) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString()))); }
  }

  Future<void> _connectLys() async {
    try { await AtlasRuntime.instance.connectLysUsbcan(bitrate: _bitrate, baseChannel: 4); }
    catch (error) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString()))); }
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: AtlasRuntime.instance,
    builder: (context, _) {
      final runtime = AtlasRuntime.instance;
      final ch1 = runtime.channels[1]!;
      final ch2 = runtime.channels[2]!;
      final ch3 = runtime.channels[3]!;
      final ch4 = runtime.channels[4]!;
      final ch5 = runtime.channels[5]!;
      final ch1Busy = ch1.state == AtlasAdapterState.connecting;
      final caBusy = ch2.state == AtlasAdapterState.connecting || ch3.state == AtlasAdapterState.connecting;
      final caConnected = ch2.connected && ch3.connected;
      final lysBusy = ch4.state == AtlasAdapterState.connecting || ch5.state == AtlasAdapterState.connecting;
      final lysConnected = ch4.connected && ch5.connected;
      return PageShell(
        title: 'Connect',
        subtitle: 'Five-channel offline capture: CANable on CH1, CANalyst-II on CH2+CH3, LYS USBCAN-II on CH4+CH5.',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _StatusTile(name: 'CH1 • candleLight / gs_usb', detail: ch1.adapter?.transport == 'candleLight / gs_usb' ? '${ch1.adapterName} • ${ch1.state.name} • $_bitrate bit/s' : 'Native WinUSB transport ready', icon: Icons.usb_rounded),
          const SizedBox(height: 8),
          Wrap(spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
            FilledButton.icon(onPressed: ch1.connected || ch1Busy || _scanningUsb ? null : _scanGsUsb, icon: _scanningUsb ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.usb), label: const Text('Scan gs_usb')),
            SizedBox(width: 330, child: DropdownButtonFormField<String>(key: ValueKey('gs-$_selectedGsPath'), initialValue: _selectedGsPath, decoration: const InputDecoration(labelText: 'candleLight / CANable'), items: _gsDevices.map((d) => DropdownMenuItem(value: d.path, child: Text(d.label))).toList(), onChanged: ch1.connected || ch1Busy ? null : (v) => setState(() => _selectedGsPath = v))),
            FilledButton.icon(onPressed: ch1.connected || ch1Busy || _selectedGsPath == null ? null : _connectGsUsb, icon: const Icon(Icons.link), label: const Text('Connect candleLight')),
          ]),
          const SizedBox(height: 18),
          _StatusTile(name: 'CH2 + CH3 • CANalyst-II dual', detail: caConnected ? '${ch2.adapterName} • ${ch2.state.name} / ${ch3.adapterName} • ${ch3.state.name} • $_bitrate bit/s' : 'Native WinUSB transport • VID 04D8:PID 0053 • two CAN channels', icon: Icons.hub),
          const SizedBox(height: 8),
          Wrap(spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
            FilledButton.icon(onPressed: caConnected || caBusy || _scanningCa ? null : _scanCanalystii, icon: _scanningCa ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.search), label: const Text('Scan CANalyst-II')),
            SizedBox(width: 360, child: DropdownButtonFormField<String>(key: ValueKey('ca-$_selectedCaPath'), initialValue: _selectedCaPath, decoration: const InputDecoration(labelText: 'Chuangxin CANalyst-II'), items: _caDevices.map((d) => DropdownMenuItem(value: d.path, child: Text(d.label))).toList(), onChanged: caConnected || caBusy ? null : (v) => setState(() => _selectedCaPath = v))),
            FilledButton.icon(onPressed: caConnected || caBusy || _selectedCaPath == null ? null : _connectCanalystii, icon: const Icon(Icons.link), label: const Text('Connect both CAN channels')),
            if (caConnected) FilledButton.tonalIcon(onPressed: () => runtime.disconnectChannel(2), icon: const Icon(Icons.link_off), label: const Text('Disconnect CANalyst-II')),
          ]),
          const SizedBox(height: 18),
          _StatusTile(name: 'CH4 + CH5 • LYS USBCAN-II dual', detail: lysConnected ? '${ch4.adapterName} • ${ch4.state.name} / ${ch5.adapterName} • ${ch5.state.name} • $_bitrate bit/s' : _lysAvailable ? 'ControlCAN VCI ready • VID 0471:PID 1200' : 'Requires x64 ControlCAN.dll beside obd_atlas.exe', icon: Icons.device_hub),
          const SizedBox(height: 8),
          Wrap(spacing: 12, runSpacing: 12, children: [
            FilledButton.icon(onPressed: lysConnected || lysBusy || _probingLys ? null : _probeLys, icon: _probingLys ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.search), label: const Text('Probe LYS USBCAN')),
            FilledButton.icon(onPressed: lysConnected || lysBusy || !_lysAvailable ? null : _connectLys, icon: const Icon(Icons.link), label: const Text('Connect CH4 + CH5')),
            if (lysConnected) FilledButton.tonalIcon(onPressed: () => runtime.disconnectChannel(4), icon: const Icon(Icons.link_off), label: const Text('Disconnect LYS')),
          ]),
          const SizedBox(height: 18),
          _StatusTile(name: 'CH1 • USB CAN / CANable (SLCAN)', detail: ch1.adapter?.transport == 'SLCAN' ? '${ch1.adapterName} • ${ch1.state.name} • $_bitrate bit/s' : 'Serial Lawicel transport ready', icon: Icons.cable),
          const SizedBox(height: 8),
          Wrap(spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
            FilledButton.icon(onPressed: ch1.connected || ch1Busy ? null : _scanSlcan, icon: const Icon(Icons.search), label: const Text('Scan serial ports')),
            SizedBox(width: 220, child: DropdownButtonFormField<String>(key: ValueKey('slcan-$_selectedPort'), initialValue: _selectedPort, decoration: const InputDecoration(labelText: 'SLCAN port'), items: _ports.map((p) => DropdownMenuItem(value: p, child: Text(p))).toList(), onChanged: ch1.connected || ch1Busy ? null : (v) => setState(() => _selectedPort = v))),
            FilledButton.icon(onPressed: ch1.connected || ch1Busy || _selectedPort == null ? null : _connectSlcan, icon: const Icon(Icons.link), label: const Text('Connect SLCAN')),
            if (ch1.connected) FilledButton.tonalIcon(onPressed: () => runtime.disconnectChannel(1), icon: const Icon(Icons.link_off), label: const Text('Disconnect CH1')),
          ]),
          const SizedBox(height: 18),
          SizedBox(width: 200, child: DropdownButtonFormField<int>(
            initialValue: _bitrate,
            decoration: const InputDecoration(labelText: 'CAN bitrate'),
            items: const [
              DropdownMenuItem(value: 125000, child: Text('125 kbit/s')),
              DropdownMenuItem(value: 250000, child: Text('250 kbit/s')),
              DropdownMenuItem(value: 500000, child: Text('500 kbit/s')),
              DropdownMenuItem(value: 1000000, child: Text('1 Mbit/s')),
            ],
            onChanged: (ch1Busy || caBusy || caConnected || lysBusy || lysConnected) ? null : (v) => setState(() => _bitrate = v ?? 500000),
          )),
          const SizedBox(height: 12),
          const _StatusTile(name: 'ELM / OBDLink', detail: 'Transport pending', icon: Icons.bluetooth),
          const _StatusTile(name: 'J2534 / VCX', detail: 'Windows transport pending', icon: Icons.memory),
          if (runtime.lastError != null) ...[
            const SizedBox(height: 12),
            Text(runtime.lastError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ]),
      );
    },
  );
}

class CapturePage extends StatelessWidget {
  const CapturePage({super.key});
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: AtlasRuntime.instance,
    builder: (context, _) {
      final runtime = AtlasRuntime.instance;
      final connected = runtime.adapterState == AtlasAdapterState.connected;
      return PageShell(
        title: 'Passive Capture',
        subtitle: 'Raw CAN traffic is preserved locally before interpretation.',
        child: Card(child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(children: [
            Icon(runtime.isCapturing ? Icons.stop_circle : Icons.fiber_manual_record, size: 56),
            const SizedBox(height: 12),
            Text(runtime.isCapturing ? 'Capture active' : connected ? '${runtime.connectedChannelCount} Atlas channels ready' : 'No adapter connected'),
            const SizedBox(height: 6),
            Text('${runtime.totalFrames} total frames • ${runtime.framesPerSecond} frames/s'),
            const SizedBox(height: 12),
            if (!runtime.isCapturing)
              FilledButton.icon(onPressed: connected ? runtime.startCapture : null, icon: const Icon(Icons.play_arrow), label: const Text('Start capture'))
            else
              FilledButton.icon(onPressed: runtime.stopCapture, icon: const Icon(Icons.stop), label: const Text('Stop capture')),
            if (runtime.activeCaptureFile != null) ...[
              const SizedBox(height: 8), SelectableText(runtime.activeCaptureFile!.path),
            ],
          ]),
        )),
      );
    },
  );
}

class LiveDataPage extends StatelessWidget {
  const LiveDataPage({super.key});
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: AtlasRuntime.instance,
    builder: (context, _) {
      final runtime = AtlasRuntime.instance;
      final frames = runtime.recentFrames.take(50).toList();
      return PageShell(
        title: 'Live Data',
        subtitle: 'Raw frame visibility first; decoding layers can bind to the same canonical stream later.',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Wrap(spacing: 12, runSpacing: 12, children: [
            _MetricCard(label: 'Frames/s', value: '${runtime.framesPerSecond}', icon: Icons.speed),
            _MetricCard(label: 'Total frames', value: '${runtime.totalFrames}', icon: Icons.timeline),
            _MetricCard(label: 'CAN IDs', value: '${runtime.seenIds.length}', icon: Icons.tag),
            _MetricCard(label: 'Channels', value: '${runtime.connectedChannelCount}', icon: Icons.hub),
          ]),
          const SizedBox(height: 16),
          Card(child: Column(children: [
            const ListTile(title: Text('Recent raw CAN frames')),
            if (frames.isEmpty)
              const ListTile(title: Text('No frames received yet'))
            else
              ...frames.map((f) => ListTile(dense: true, leading: Text(f.bus), title: Text(f.idHex), subtitle: Text(f.dataHex.isEmpty ? '(remote frame)' : f.dataHex), trailing: Text('DLC ${f.dlc}'))),
          ])),
        ]),
      );
    },
  );
}

class LibraryPage extends StatefulWidget {
  const LibraryPage({super.key});
  @override
  State<LibraryPage> createState() => _LibraryPageState();
}

class _LibraryPageState extends State<LibraryPage> {
  late Future<List<FileSystemEntity>> _logs;
  @override
  void initState() { super.initState(); _refresh(); }
  void _refresh() => _logs = AtlasLocalStore.instance.listLogs();
  Future<void> _import() async {
    final picked = await FilePicker.platform.pickFiles(allowMultiple: false, type: FileType.custom, allowedExtensions: const ['log', 'csv', 'txt', 'json', 'asc', 'trc']);
    final path = picked?.files.single.path;
    if (path == null) return;
    await AtlasLocalStore.instance.importLog(File(path));
    if (mounted) setState(_refresh);
  }
  @override
  Widget build(BuildContext context) => PageShell(
    title: 'Atlas Library',
    subtitle: 'Local vehicle captures remain available with no internet connection.',
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Align(alignment: Alignment.centerLeft, child: FilledButton.icon(onPressed: _import, icon: const Icon(Icons.file_open), label: const Text('Import capture'))),
      const SizedBox(height: 12),
      FutureBuilder<List<FileSystemEntity>>(
        future: _logs,
        builder: (context, snapshot) {
          if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
          final logs = snapshot.data!;
          if (logs.isEmpty) return const Card(child: ListTile(title: Text('No local captures yet')));
          return Column(children: logs.map((entry) {
            final fileName = entry.uri.pathSegments.where((e) => e.isNotEmpty).last;
            final stat = entry.statSync();
            return Card(child: ListTile(leading: const Icon(Icons.description), title: Text(fileName), subtitle: Text('${stat.size} bytes • ${stat.modified.toLocal()}')));
          }).toList());
        },
      ),
    ]),
  );
}

class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});
  @override
  Widget build(BuildContext context) => const PageShell(
    title: 'Settings',
    subtitle: 'Core application behavior is local by default. Internet services are not required for operation.',
    child: Column(children: [
      SwitchListTile(value: true, onChanged: null, title: Text('Offline-first mode'), subtitle: Text('Permanent architectural default')),
      SwitchListTile(value: true, onChanged: null, title: Text('Preserve raw captures'), subtitle: Text('Keep source evidence before decoding')),
      ListTile(leading: Icon(Icons.cloud_off), title: Text('Cloud dependency'), trailing: Text('NONE')),
      ListTile(leading: Icon(Icons.info_outline), title: Text('Build'), trailing: Text('6')),
    ]),
  );
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.label, required this.value, required this.icon});
  final String label;
  final String value;
  final IconData icon;
  @override
  Widget build(BuildContext context) => SizedBox(
    width: 220,
    child: Card(child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon), const SizedBox(height: 18),
        Text(value, style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4), Text(label),
      ]),
    )),
  );
}

class _StatusTile extends StatelessWidget {
  const _StatusTile({required this.name, required this.detail, required this.icon});
  final String name;
  final String detail;
  final IconData icon;
  @override
  Widget build(BuildContext context) => Card(child: ListTile(leading: Icon(icon), title: Text(name), subtitle: Text(detail), trailing: const Icon(Icons.circle_outlined)));
}
