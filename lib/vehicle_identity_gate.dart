import 'package:flutter/material.dart';

import 'core/atlas_runtime.dart';
import 'core/local_store.dart';
import 'core/vehicle_identity.dart';

/// Shared offline-first entry gate for Android, Windows and Linux.
/// It never transmits diagnostic requests or uploads captures.
class VehicleIdentityGate extends StatefulWidget {
  const VehicleIdentityGate({super.key, required this.child});
  final Widget child;

  @override
  State<VehicleIdentityGate> createState() => _VehicleIdentityGateState();
}

class _VehicleIdentityGateState extends State<VehicleIdentityGate> {
  VehicleIdentity _vehicle = VehicleIdentity.unknown;
  bool _loading = true;
  bool _editing = true;
  bool _saving = false;
  String? _error;
  late final TextEditingController _make;
  late final TextEditingController _model;
  late final TextEditingController _year;
  late final TextEditingController _generation;
  late final TextEditingController _vin;

  @override
  void initState() {
    super.initState();
    _make = TextEditingController(text: 'Chevrolet');
    _model = TextEditingController(text: 'Volt');
    _year = TextEditingController(text: '2013');
    _generation = TextEditingController();
    _vin = TextEditingController();
    _load();
  }

  Future<void> _load() async {
    try {
      final vehicle = await AtlasLocalStore.instance.loadVehicle();
      if (!mounted) return;
      _populate(vehicle);
      setState(() {
        _vehicle = vehicle;
        _editing = vehicle.isUnknown;
        _loading = false;
      });
    } catch (error) {
      if (mounted) setState(() { _error = '$error'; _loading = false; });
    }
  }

  void _populate(VehicleIdentity vehicle) {
    if (vehicle.isUnknown) return;
    _make.text = vehicle.make;
    _model.text = vehicle.model;
    _year.text = vehicle.modelYear?.toString() ?? '';
    _generation.text = vehicle.generation?.toString() ?? '';
    _vin.text = vehicle.vin ?? '';
  }

  @override
  void dispose() {
    _make.dispose();
    _model.dispose();
    _year.dispose();
    _generation.dispose();
    _vin.dispose();
    super.dispose();
  }

  Future<void> _save(VehicleIdentity vehicle) async {
    if (AtlasRuntime.instance.capture.hasOpenCapture) {
      setState(() => _error = 'Stop the current capture before changing vehicles.');
      return;
    }
    setState(() { _saving = true; _error = null; });
    try {
      await AtlasLocalStore.instance.selectVehicle(vehicle);
      if (!mounted) return;
      setState(() { _vehicle = vehicle; _editing = false; });
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _saveSelected() {
    try {
      final year = int.tryParse(_year.text.trim());
      if (year == null) throw const FormatException('Enter the vehicle model year.');
      final generationText = _generation.text.trim();
      final generation = generationText.isEmpty ? null : int.tryParse(generationText);
      if (generationText.isNotEmpty && generation == null) {
        throw const FormatException('Generation must be a number or blank.');
      }
      final vehicle = VehicleIdentity.selected(
        make: _make.text, model: _model.text, modelYear: year,
        generation: generation, vin: _vin.text.isEmpty ? null : _vin.text,
      );
      _save(vehicle);
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'OBD Atlas • Vehicle Identity',
      themeMode: ThemeMode.dark,
      darkTheme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.cyanAccent, brightness: Brightness.dark),
        useMaterial3: true,
      ),
      home: _loading
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : _editing ? _identityEditor() : _workspace(),
    );
  }

  Widget _workspace() {
    return Scaffold(
      body: Column(children: [
        Material(
          elevation: 1,
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
              child: Row(children: [
                const Icon(Icons.directions_car, size: 18),
                const SizedBox(width: 8),
                Expanded(child: Text(_vehicle.displayName, overflow: TextOverflow.ellipsis)),
                AnimatedBuilder(
                  animation: AtlasRuntime.instance.capture,
                  builder: (context, _) => TextButton.icon(
                    onPressed: AtlasRuntime.instance.capture.hasOpenCapture ? null : () {
                      _populate(_vehicle);
                      setState(() { _error = null; _editing = true; });
                    },
                    icon: const Icon(Icons.swap_horiz, size: 18),
                    label: const Text('Change vehicle'),
                  ),
                ),
              ]),
            ),
          ),
        ),
        Expanded(child: widget.child),
      ]),
    );
  }

  Widget _identityEditor() {
    return Scaffold(
      appBar: AppBar(title: const Text('Select vehicle')),
      body: Center(child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: ListView(padding: const EdgeInsets.all(20), children: [
          Text('Vehicle identity', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 8),
          const Text('Select the vehicle before recording. All sessions are separated by make, model, generation and model year. A new session is required when changing vehicles.'),
          const SizedBox(height: 16),
          Wrap(spacing: 8, runSpacing: 8, children: [
            _preset('2013 Volt', 'Chevrolet', 'Volt', '2013', ''),
            _preset('2018 Volt', 'Chevrolet', 'Volt', '2018', ''),
            _preset('Ampera', 'Opel', 'Ampera', '2014', ''),
            _preset('ELR', 'Cadillac', 'ELR', '2014', ''),
          ]),
          const SizedBox(height: 16),
          TextField(controller: _make, decoration: const InputDecoration(labelText: 'Make', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(controller: _model, decoration: const InputDecoration(labelText: 'Model', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(controller: _year, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Model year', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(controller: _generation, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Generation (optional for other vehicles)', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(controller: _vin, maxLength: 17, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(labelText: 'VIN (optional, kept in local profile only)', border: OutlineInputBorder())),
          const Text('Identity is user-selected, not automatically verified. A VIN entry does not prove make/model. No vehicle-identification commands are sent by this screen.'),
          const SizedBox(height: 12),
          const Text('Public upload is disabled by default. A future submission must pass server-side vehicle review and a separate privacy/consent check.'),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 20),
          FilledButton.icon(onPressed: _saving ? null : _saveSelected, icon: const Icon(Icons.save), label: const Text('Use this vehicle')),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _saving ? null : () => _save(VehicleIdentity.unknown),
            icon: const Icon(Icons.help_outline),
            label: const Text('Capture unidentified vehicle locally'),
          ),
          if (!_vehicle.isUnknown)
            TextButton(onPressed: _saving ? null : () => setState(() => _editing = false), child: const Text('Cancel')),
        ]),
      )),
    );
  }

  Widget _preset(String label, String make, String model, String year, String generation) {
    return ActionChip(label: Text(label), onPressed: () {
      _make.text = make;
      _model.text = model;
      _year.text = year;
      _generation.text = generation;
      _vin.clear();
      setState(() => _error = null);
    });
  }
}
