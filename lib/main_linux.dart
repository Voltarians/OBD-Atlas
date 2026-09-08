import 'dart:io';
import 'package:flutter/material.dart';
import 'main_linux_app.dart' as original;
import 'vehicle_identity_gate.dart';
export 'main_linux_app.dart' hide main;
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  if (!Platform.isLinux) {
    throw UnsupportedError('main_linux.dart is the OBD Atlas Linux desktop entry point.');
  }
  runApp(const VehicleIdentityGate(child: original.ObdAtlasLinuxApp()));
}
