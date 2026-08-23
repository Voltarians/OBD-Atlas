import 'package:flutter/material.dart';

void main() => runApp(const ObdAtlasApp());

class ObdAtlasApp extends StatelessWidget {
  const ObdAtlasApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'OBD Atlas',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          colorSchemeSeed: Colors.cyan,
          useMaterial3: true,
        ),
        home: const ResearchHome(),
      );
}

class ResearchHome extends StatefulWidget {
  const ResearchHome({super.key});

  @override
  State<ResearchHome> createState() => _ResearchHomeState();
}

class _ResearchHomeState extends State<ResearchHome> {
  var _index = 0;

  static const _pages = <Widget>[
    _DiscoveryPage(),
    _InventoryPage(),
    _LoggingPage(),
  ];

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('OBD Atlas 0.1'),
          actions: const [
            Padding(
              padding: EdgeInsets.all(12),
              child: Chip(label: Text('PASSIVE')),
            ),
          ],
        ),
        body: _pages[_index],
        bottomNavigationBar: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: (value) => setState(() => _index = value),
          destinations: const [
            NavigationDestination(icon: Icon(Icons.radar), label: 'Discovery'),
            NavigationDestination(icon: Icon(Icons.memory), label: 'ECUs'),
            NavigationDestination(icon: Icon(Icons.save), label: 'Logging'),
          ],
        ),
      );
}

class _DiscoveryPage extends StatelessWidget {
  const _DiscoveryPage();

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: const [
          _GateCard(
            title: 'Adapter qualification',
            detail: 'Identity, voltage, protocol support, throughput and storage integrity',
          ),
          _GateCard(
            title: 'Protocol discovery',
            detail: 'ISO 15765-4, ISO 14230-4, ISO 9141-2, J1850 VPW and PWM',
          ),
          _GateCard(
            title: 'Safety boundary',
            detail: 'No clearing, control, security access or programming in version 0.1',
          ),
        ],
      );
}

class _InventoryPage extends StatelessWidget {
  const _InventoryPage();

  @override
  Widget build(BuildContext context) => const Center(
        child: Text('Connect a qualified adapter to build an evidence-backed ECU inventory.'),
      );
}

class _LoggingPage extends StatelessWidget {
  const _LoggingPage();

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: const [
          _GateCard(title: 'candump', detail: 'Atlas-compatible raw CAN output'),
          _GateCard(title: 'CSV', detail: 'Timestamp, channel, identifier, DLC, data and status'),
          _GateCard(title: 'Consent-based upload', detail: 'Off by default; VIN privacy review required'),
        ],
      );
}

class _GateCard extends StatelessWidget {
  const _GateCard({required this.title, required this.detail});
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => Card(
        child: ListTile(
          leading: const Icon(Icons.shield_outlined, color: Colors.cyanAccent),
          title: Text(title),
          subtitle: Text(detail),
        ),
      );
}
