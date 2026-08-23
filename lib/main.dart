import 'package:flutter/material.dart';

import 'src/research_models.dart';

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
  VehicleIdentity _identity = const VehicleIdentity();

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      _VehicleIdentityPage(
        identity: _identity,
        onChanged: (value) => setState(() => _identity = value),
      ),
      _DiscoveryPage(identity: _identity),
      _InventoryPage(identity: _identity),
      _LoggingPage(identity: _identity),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text('OBD Atlas 0.1'),
        actions: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Chip(label: Text(_identity.classified ? 'IDENTIFIED' : 'UNCLASSIFIED')),
          ),
          const Padding(
            padding: EdgeInsets.all(12),
            child: Chip(label: Text('PASSIVE')),
          ),
        ],
      ),
      body: pages[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (value) => setState(() => _index = value),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.badge), label: 'Identity'),
          NavigationDestination(icon: Icon(Icons.radar), label: 'Discovery'),
          NavigationDestination(icon: Icon(Icons.memory), label: 'ECUs'),
          NavigationDestination(icon: Icon(Icons.save), label: 'Logging'),
        ],
      ),
    );
  }
}

class _VehicleIdentityPage extends StatefulWidget {
  const _VehicleIdentityPage({required this.identity, required this.onChanged});
  final VehicleIdentity identity;
  final ValueChanged<VehicleIdentity> onChanged;

  @override
  State<_VehicleIdentityPage> createState() => _VehicleIdentityPageState();
}

class _VehicleIdentityPageState extends State<_VehicleIdentityPage> {
  late final TextEditingController _vin;
  late final TextEditingController _make;
  late final TextEditingController _model;
  late final TextEditingController _year;
  late final TextEditingController _generation;
  late final TextEditingController _powertrain;
  late final TextEditingController _configuration;
  final _privacySecret = TextEditingController();
  String _status = 'Retrieve or enter the VIN before vehicle research begins.';

  @override
  void initState() {
    super.initState();
    final value = widget.identity;
    _vin = TextEditingController(text: value.vin);
    _make = TextEditingController(text: value.make);
    _model = TextEditingController(text: value.model);
    _year = TextEditingController(text: value.modelYear?.toString());
    _generation = TextEditingController(text: value.generation);
    _powertrain = TextEditingController(text: value.powertrain);
    _configuration = TextEditingController(text: value.marketConfiguration);
  }

  void _confirm() {
    final vin = VinCodec.normalize(_vin.text);
    final year = int.tryParse(_year.text.trim());
    if (!VinCodec.formatValid(vin)) {
      setState(() => _status = 'VIN must contain 17 valid characters; I, O and Q are prohibited.');
      return;
    }
    if (_make.text.trim().isEmpty || _model.text.trim().isEmpty || year == null) {
      setState(() => _status = 'Make, model and numeric model year are required.');
      return;
    }
    if (_privacySecret.text.isEmpty) {
      setState(() => _status = 'Enter a local privacy key before confirming this vehicle.');
      return;
    }
    final identity = VehicleIdentity(
      vin: vin,
      vinHash: VinCodec.privacyHash(vin: vin, secret: _privacySecret.text),
      make: _make.text.trim(),
      model: _model.text.trim(),
      modelYear: year,
      generation: _optional(_generation.text),
      powertrain: _optional(_powertrain.text),
      marketConfiguration: _optional(_configuration.text),
      status: VehicleIdentityStatus.operatorConfirmed,
      operatorConfirmedUtc: DateTime.now().toUtc(),
    );
    widget.onChanged(identity);
    setState(() {
      _status = VinCodec.checkDigitValid(vin)
          ? 'Identity confirmed. Capture partition: ${identity.classificationKey}'
          : 'Identity confirmed with a VIN check-digit warning. Verify the VIN manually.';
    });
  }

  String? _optional(String value) => value.trim().isEmpty ? null : value.trim();

  void _clear() {
    for (final controller in [
      _vin, _make, _model, _year, _generation, _powertrain, _configuration,
    ]) {
      controller.clear();
    }
    _privacySecret.clear();
    widget.onChanged(const VehicleIdentity());
    setState(() => _status = 'Identity cleared. Captures will be quarantined as UNCLASSIFIED.');
  }

  @override
  void dispose() {
    for (final controller in [
      _vin, _make, _model, _year, _generation, _powertrain, _configuration,
      _privacySecret,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const _GateCard(
            title: 'Vehicle identity gate',
            detail:
                'Mode 09 VIN retrieval will populate this screen after adapter support lands. '
                'Make/model decoding will use the standalone vPIC database on your Proxmox server. '
                'Manual correction remains mandatory before classification.',
          ),
          TextField(
            controller: _vin,
            maxLength: 17,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(border: OutlineInputBorder(), labelText: 'VIN'),
          ),
          Row(
            children: [
              Expanded(child: _field(_make, 'Make')),
              const SizedBox(width: 12),
              Expanded(child: _field(_model, 'Model')),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _year,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    labelText: 'Model year',
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(child: _field(_generation, 'Generation/platform')),
            ],
          ),
          const SizedBox(height: 12),
          _field(_powertrain, 'Powertrain'),
          const SizedBox(height: 12),
          _field(_configuration, 'Trim, body, market and configuration'),
          const SizedBox(height: 12),
          TextField(
            controller: _privacySecret,
            obscureText: true,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              labelText: 'Local VIN privacy key',
              helperText: 'Creates a keyed VIN hash and is never uploaded.',
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              FilledButton.icon(
                onPressed: _confirm,
                icon: const Icon(Icons.verified),
                label: const Text('Confirm vehicle identity'),
              ),
              OutlinedButton.icon(
                onPressed: _clear,
                icon: const Icon(Icons.restart_alt),
                label: const Text('Clear identity'),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Text(_status),
          ),
        ],
      );

  Widget _field(TextEditingController controller, String label) => TextField(
        controller: controller,
        decoration: InputDecoration(border: const OutlineInputBorder(), labelText: label),
      );
}

class _DiscoveryPage extends StatelessWidget {
  const _DiscoveryPage({required this.identity});
  final VehicleIdentity identity;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _GateCard(
            title: identity.classified ? 'Identity gate passed' : 'Identity gate incomplete',
            detail: identity.classified
                ? 'Research will be stored under ${identity.classificationKey}'
                : 'Discovery may proceed, but evidence remains in UNCLASSIFIED quarantine.',
          ),
          const _GateCard(
            title: 'Adapter qualification',
            detail: 'Identity, voltage, protocol support, throughput and storage integrity',
          ),
          const _GateCard(
            title: 'Protocol discovery',
            detail: 'ISO 15765-4, ISO 14230-4, ISO 9141-2, J1850 VPW and PWM',
          ),
        ],
      );
}

class _InventoryPage extends StatelessWidget {
  const _InventoryPage({required this.identity});
  final VehicleIdentity identity;

  @override
  Widget build(BuildContext context) => Center(
        child: Text(
          identity.classified
              ? 'ECU observations will be attached to ${identity.classificationKey}.'
              : 'ECU observations remain UNCLASSIFIED until identity is confirmed.',
        ),
      );
}

class _LoggingPage extends StatelessWidget {
  const _LoggingPage({required this.identity});
  final VehicleIdentity identity;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _GateCard(
            title: identity.classified ? 'Classified capture' : 'Quarantined capture',
            detail: identity.classified
                ? identity.classificationKey
                : 'Stored under UNCLASSIFIED; cannot enter a vehicle research dataset.',
          ),
          const _GateCard(title: 'candump', detail: 'Atlas-compatible raw CAN output'),
          const _GateCard(title: 'CSV', detail: 'Timestamp, channel, identifier, DLC, data and status'),
          const _GateCard(
            title: 'Consent-based upload',
            detail: 'Off by default; raw VIN is prohibited from backend manifests',
          ),
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
