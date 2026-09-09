import 'package:flutter/material.dart';
import 'main_app.dart' as original;
import 'vehicle_identity_gate.dart';
export 'main_app.dart' hide main;
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const VehicleIdentityGate(child: original.ObdAtlasApp()));
}
